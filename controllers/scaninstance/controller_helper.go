package scaninstance

import (
	"context"
	"fmt"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/util/retry"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	"github.com/trilioData/threat-scanning-architecture/internal"
	"github.com/trilioData/threat-scanning-architecture/pkg/helpers"
)

func (r *Reconciler) reconcileScanInstanceDeleteFinalizer(ctx context.Context, scanInstance,
	originalScanInstance *v1.ScanInstance) (continueReconcile bool, err error) {

	if scanInstance.ObjectMeta.DeletionTimestamp.IsZero() &&
		!internal.ContainsString(scanInstance.Finalizers, internal.ScanInstanceDeleteFinalizer) {
		finalizers := scanInstance.ObjectMeta.Finalizers
		finalizers = append(finalizers, internal.ScanInstanceDeleteFinalizer)
		retErr := retry.RetryOnConflict(retry.DefaultRetry, func() error {
			err = r.Get(ctx, types.NamespacedName{Name: scanInstance.Name}, scanInstance)
			if err != nil {
				return err
			}
			scanInstance.ObjectMeta.Finalizers = finalizers
			return r.Update(ctx, scanInstance)
		})
		if retErr != nil {
			return continueReconcile, fmt.Errorf("error while updating finalizer: %w", retErr)
		}
		scanInstance.DeepCopyInto(originalScanInstance)
	} else if !scanInstance.ObjectMeta.DeletionTimestamp.IsZero() &&
		internal.ContainsString(scanInstance.ObjectMeta.Finalizers, internal.ScanInstanceDeleteFinalizer) {
		r.Log.Infof("cleaning up scan instance resources for scanInstance:%s", scanInstance.Name)

		// Cleanup scan instance resources
		if err := r.cleanupScanInstanceResources(ctx, scanInstance); err != nil {
			return continueReconcile, fmt.Errorf("error while cleaning scan instance resources: %w", err)
		}

		// Remove finalizer with retry to handle ResourceVersion conflicts
		retErr := retry.RetryOnConflict(retry.DefaultRetry, func() error {
			// Refetch the scan instance to get the latest ResourceVersion
			err = r.Get(ctx, types.NamespacedName{Name: scanInstance.Name}, scanInstance)
			if err != nil {
				// If scan instance is already deleted, no need to remove finalizer
				if apierrors.IsNotFound(err) {
					return nil
				}
				return err
			}
			scanInstance.ObjectMeta.Finalizers = internal.RemoveString(scanInstance.ObjectMeta.Finalizers, internal.ScanInstanceDeleteFinalizer)
			return r.Update(ctx, scanInstance)
		})
		if retErr != nil {
			return continueReconcile, fmt.Errorf("error while updating finalizer: %w", retErr)
		}
		return continueReconcile, nil
	}

	return true, nil
}

func (r *Reconciler) cleanupScanInstanceResources(ctx context.Context, scanInstance *v1.ScanInstance) error {
	// Delete pre-scan job if exists
	preScanJobName := helpers.GetScanInstanceResourceName(internal.ScanInstancePreScanPrefix, scanInstance.Name)
	preScanJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      preScanJobName,
	}, preScanJob); err == nil {
		// Use Background propagation to delete pods along with the job
		backgroundPolicy := metav1.DeletePropagationBackground
		if err := r.Client.Delete(ctx, preScanJob, &client.DeleteOptions{PropagationPolicy: &backgroundPolicy}); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting pre-scan job: %w", err)
		}
		r.Log.Infof("Deleted pre-scan job: %s", preScanJobName)
	}

	// Delete scan job if exists
	scanJobName := helpers.GetScanInstanceResourceName(internal.ScanInstanceScanJobPrefix, scanInstance.Name)
	scanJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      scanJobName,
	}, scanJob); err == nil {
		backgroundPolicy := metav1.DeletePropagationBackground
		if err := r.Client.Delete(ctx, scanJob, &client.DeleteOptions{PropagationPolicy: &backgroundPolicy}); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting scan job: %w", err)
		}
		r.Log.Infof("Deleted scan job: %s", scanJobName)
	}

	// Delete scan configmap if exists
	configMapName := helpers.GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, scanInstance.Name)
	configMap := &corev1.ConfigMap{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      configMapName,
	}, configMap); err == nil {
		if err := r.Client.Delete(ctx, configMap); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting scan configmap: %w", err)
		}
		r.Log.Infof("Deleted scan configmap: %s", configMapName)
	}

	// Delete scan secret if exists
	secretName := helpers.GetScanInstanceResourceName(internal.ScanInstanceScanSecretPrefix, scanInstance.Name)
	secret := &corev1.Secret{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      secretName,
	}, secret); err == nil {
		if err := r.Client.Delete(ctx, secret); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting scan secret: %w", err)
		}
		r.Log.Infof("Deleted scan secret: %s", secretName)
	}

	// Delete Redis deployment if exists
	redisDeployName := helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisDeployPrefix, scanInstance.Name)
	redisDeploy := &appsv1.Deployment{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      redisDeployName,
	}, redisDeploy); err == nil {
		backgroundPolicy := metav1.DeletePropagationBackground
		if err := r.Client.Delete(ctx, redisDeploy, &client.DeleteOptions{PropagationPolicy: &backgroundPolicy}); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting redis deployment: %w", err)
		}
		r.Log.Infof("Deleted redis deployment: %s", redisDeployName)
	}

	// Delete Redis service if exists
	redisSvcName := helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisServicePrefix, scanInstance.Name)
	redisSvc := &corev1.Service{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      redisSvcName,
	}, redisSvc); err == nil {
		if err := r.Client.Delete(ctx, redisSvc); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting redis service: %w", err)
		}
		r.Log.Infof("Deleted redis service: %s", redisSvcName)
	}

	// TODO: Delete cleanup job for reports when implemented

	return nil
}

func (r *Reconciler) getPreScanJob(ctx context.Context, scanInstance *v1.ScanInstance) (*batchv1.Job, error) {
	preScanJob := &batchv1.Job{}

	preScanJobKey := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      helpers.GetScanInstanceResourceName(internal.ScanInstancePreScanPrefix, scanInstance.Name),
	}

	if err := r.Client.Get(ctx, preScanJobKey, preScanJob); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, nil
		}
		return nil, err
	}

	return preScanJob, nil
}

func (r *Reconciler) createPreScanJob(ctx context.Context, scanInstance *v1.ScanInstance) (*batchv1.Job, error) {
	// Extract information from ScanInstance for prescan job
	// Webhook ensures target exists and is available before ScanInstance creation
	targetName := scanInstance.Spec.BackupTarget.Name
	backupUID := scanInstance.Spec.BackupRef.UID
	backupPath := scanInstance.Spec.BackupRef.Path

	// Fetch target to get backup type
	target := &v1.Target{}
	if err := r.Client.Get(ctx, types.NamespacedName{Name: targetName}, target); err != nil {
		return nil, fmt.Errorf("error fetching target %s: %w", targetName, err)
	}

	// Create pre-scan job spec with target object (includes backup type)
	preScanJob, err := helpers.GetPreScanJob(ctx, r.Client, scanInstance, target, backupUID, backupPath)
	if err != nil {
		return nil, fmt.Errorf("error creating pre-scan job spec: %w", err)
	}

	// Propagate all labels from ScanInstance to Job (merge with existing)
	if scanInstance.Labels != nil {
		if preScanJob.Labels == nil {
			preScanJob.Labels = make(map[string]string)
		}
		for k, v := range scanInstance.Labels {
			// Don't override controller-managed labels
			if _, exists := preScanJob.Labels[k]; !exists {
				preScanJob.Labels[k] = v
			}
		}
	}

	// Propagate all annotations from ScanInstance to Job (merge with existing)
	if scanInstance.Annotations != nil {
		if preScanJob.Annotations == nil {
			preScanJob.Annotations = make(map[string]string)
		}
		for k, v := range scanInstance.Annotations {
			// Don't override controller-managed annotations
			if _, exists := preScanJob.Annotations[k]; !exists {
				preScanJob.Annotations[k] = v
			}
		}
	}

	// Create the job
	if err := r.Client.Create(ctx, preScanJob); err != nil {
		r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanJobCreateFailed",
			"Pre-scan job creation failed for ScanInstance: %s", scanInstance.Name)
		return nil, fmt.Errorf("error creating pre-scan job: %w", err)
	}

	return preScanJob, nil
}

func (r *Reconciler) updateScanInstanceStatus(ctx context.Context, scanInstance, originalScanInstance *v1.ScanInstance, status v1.ScanInstanceStatus) error {
	if status == "" {
		return nil
	}
	scanInstance.Status.Status = status

	r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "StatusUpdate",
		"ScanInstance status updated to: %s", status)

	if err := r.Client.Status().Patch(ctx, scanInstance, client.MergeFrom(originalScanInstance)); err != nil {
		return err
	}
	scanInstance.DeepCopyInto(originalScanInstance)
	return nil
}

func (r *Reconciler) updateScanInstanceCondition(ctx context.Context, scanInstance, originalScanInstance *v1.ScanInstance,
	phase v1.ScanPhase, status v1.Status, reason string) error {

	// Check if this exact condition already exists to prevent duplicates
	// This can happen if multiple reconciliations occur before the condition is persisted
	if scanInstance.HasCondition(phase, status) {
		// Condition already exists, no need to add again
		return nil
	}

	condition := v1.ScanInstanceCondition{
		Phase:     phase,
		Status:    status,
		Timestamp: &metav1.Time{Time: metav1.Now().Time},
		Reason:    reason,
	}

	scanInstance.Status.Condition = append(scanInstance.Status.Condition, condition)

	if err := r.Client.Status().Patch(ctx, scanInstance, client.MergeFrom(originalScanInstance)); err != nil {
		return err
	}
	scanInstance.DeepCopyInto(originalScanInstance)
	return nil
}

// createScanJob creates a scan job for the given ScanInstance
func (r *Reconciler) createScanJob(ctx context.Context, scanInstance *v1.ScanInstance, secretName string) (*batchv1.Job, error) {
	// Get scan job spec
	scanJob, err := helpers.GetScanJob(ctx, r.Client, scanInstance, secretName)
	if err != nil {
		return nil, err
	}

	// Set owner reference to ScanInstance
	if err := ctrl.SetControllerReference(scanInstance, scanJob, r.Scheme); err != nil {
		return nil, fmt.Errorf("error setting owner reference: %w", err)
	}

	// Check if job already exists (idempotency)
	existingJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: scanJob.Namespace,
		Name:      scanJob.Name,
	}, existingJob); err == nil {
		// Job already exists, return it
		return existingJob, nil
	} else if !apierrors.IsNotFound(err) {
		return nil, fmt.Errorf("error checking for existing scan job: %w", err)
	}

	// Merge any additional labels/annotations if needed
	if scanInstance.Labels != nil {
		if scanJob.Labels == nil {
			scanJob.Labels = make(map[string]string)
		}
		for k, v := range scanInstance.Labels {
			if _, exists := scanJob.Labels[k]; !exists {
				scanJob.Labels[k] = v
			}
		}
	}

	if scanInstance.Annotations != nil {
		if scanJob.Annotations == nil {
			scanJob.Annotations = make(map[string]string)
		}
		for k, v := range scanInstance.Annotations {
			if _, exists := scanJob.Annotations[k]; !exists {
				scanJob.Annotations[k] = v
			}
		}
	}

	// Create the job
	if err := r.Client.Create(ctx, scanJob); err != nil {
		r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "ScanJobCreateFailed",
			"Scan job creation failed for ScanInstance: %s", scanInstance.Name)
		return nil, fmt.Errorf("error creating scan job: %w", err)
	}

	return scanJob, nil
}

// getScanJob retrieves the scan job for the given ScanInstance
func (r *Reconciler) getScanJob(ctx context.Context, scanInstance *v1.ScanInstance) (*batchv1.Job, error) {
	jobName := helpers.GetScanInstanceResourceName(internal.ScanInstanceScanJobPrefix, scanInstance.Name)
	scanJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      jobName,
	}, scanJob); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, nil
		}
		return nil, err
	}
	return scanJob, nil
}

// reconcileRedisDeployment handles the Redis deployment phase
func (r *Reconciler) reconcileRedisDeployment(ctx context.Context, scanInstance, originalScanInstance *v1.ScanInstance) (ctrl.Result, error) {
	log := r.Log.WithField("scanInstance", scanInstance.Name)

	// Check if Redis deployment phase is already in progress or completed (idempotency)
	if scanInstance.HasCondition(v1.RedisDeployment, v1.Ready) {
		log.Debug("Redis deployment already ready, proceeding to scan phase")
		return ctrl.Result{}, nil
	}

	// Check if Redis deployment phase has failed (terminal state for this phase)
	if scanInstance.HasCondition(v1.RedisDeployment, v1.Failed) {
		log.Info("Redis deployment has failed")
		// Update overall status to failed if not already
		if scanInstance.Status.Status != v1.ScanFailed {
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}
		return ctrl.Result{}, nil
	}

	// Update condition to RedisDeployment InProgress if not already set
	if !scanInstance.HasCondition(v1.RedisDeployment, v1.InProgress) {
		if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.RedisDeployment, v1.InProgress,
			"Creating Redis deployment"); uErr != nil {
			return ctrl.Result{}, uErr
		}
		log.Info("Updated condition to RedisDeployment InProgress")
	}

	// Get or create Redis deployment
	redisDeploy, err := r.getRedisDeployment(ctx, scanInstance)
	if err != nil {
		r.Log.WithError(err).Error("error while getting Redis deployment")
		return ctrl.Result{}, err
	}

	if redisDeploy == nil {
		// Create Redis deployment
		redisDeploy, err = r.createRedisDeployment(ctx, scanInstance)
		if err != nil {
			r.Log.WithError(err).Error("error occurred while creating Redis deployment")
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.RedisDeployment, v1.Failed,
				fmt.Sprintf("Failed to create Redis deployment: %v", err)); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
			return ctrl.Result{}, err
		}

		log.Infof("Created Redis deployment: %s", redisDeploy.Name)
	}

	// Get or create Redis service
	redisSvc, err := r.getRedisService(ctx, scanInstance)
	if err != nil {
		r.Log.WithError(err).Error("error while getting Redis service")
		return ctrl.Result{}, err
	}

	if redisSvc == nil {
		// Create Redis service
		redisSvc, err = r.createRedisService(ctx, scanInstance)
		if err != nil {
			r.Log.WithError(err).Error("error occurred while creating Redis service")
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.RedisDeployment, v1.Failed,
				fmt.Sprintf("Failed to create Redis service: %v", err)); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
			return ctrl.Result{}, err
		}

		log.Infof("Created Redis service: %s", redisSvc.Name)
	}

	// Check if Redis deployment is ready
	if r.isRedisDeploymentReady(redisDeploy) {
		// Update condition to RedisDeployment Ready
		if !scanInstance.HasCondition(v1.RedisDeployment, v1.Ready) {
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.RedisDeployment, v1.Ready,
				"Redis deployment is ready"); uErr != nil {
				return ctrl.Result{}, uErr
			}

			r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "RedisDeploymentReady",
				"Redis deployment is ready for ScanInstance: %s", scanInstance.Name)

			log.Info("Redis deployment is ready, updated condition")

			// Requeue immediately to proceed to scan job creation
			// We need explicit requeue here because deployment watcher won't fire again
			// (deployment is already ready and won't have further status changes)
			return ctrl.Result{Requeue: true}, nil
		}

		// Condition already exists, proceed
		return ctrl.Result{}, nil
	}

	// Redis deployment not ready yet
	// Don't requeue - deployment watcher will trigger reconciliation when deployment status changes
	log.Debug("Redis deployment not ready yet, waiting for deployment watcher to trigger reconciliation")
	return ctrl.Result{}, nil
}

// processScanJobStatus processes the status of the scan job and updates ScanInstance accordingly
func (r *Reconciler) processScanJobStatus(ctx context.Context, scanInstance, originalScanInstance *v1.ScanInstance, scanJob *batchv1.Job) (ctrl.Result, error) {
	log := r.Log.WithField("scanInstance", scanInstance.Name).WithField("scanJob", scanJob.Name)

	jobStatus := helpers.GetJobStatusWithPodCheck(ctx, r.Client, scanJob)
	log.Debugf("Found scan job with name: %s and status: %v", scanJob.Name, jobStatus)

	switch jobStatus {
	case v1.Completed:
		// Scan completed successfully
		// Check idempotency - only update if condition doesn't exist
		if !scanInstance.HasCondition(v1.Scanning, v1.Completed) {
			r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "ScanCompleted",
				"Scan completed successfully for ScanInstance: %s", scanInstance.Name)

			// Set report path in status before marking as completed
			reportPath := helpers.GetReportPath(scanInstance)
			if scanInstance.Status.Report != reportPath {
				scanInstance.Status.Report = reportPath
				if err := r.Client.Status().Update(ctx, scanInstance); err != nil {
					log.WithError(err).Error("Failed to update report path in status")
					return ctrl.Result{}, fmt.Errorf("failed to update report path: %w", err)
				}
				log.Infof("Updated report path in status: %s", reportPath)
			}

			// Mark entire ScanInstance as completed
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanCompleted); uErr != nil {
				return ctrl.Result{}, uErr
			}

			log.Infof("Scan completed successfully, ScanInstance marked as completed")

			// Add Scanning/Completed condition
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Completed,
				"Scan completed successfully"); uErr != nil {
				return ctrl.Result{}, uErr
			}

			// Trigger janitor job to cleanup resources
			if err := r.createJanitorJob(ctx, scanInstance); err != nil {
				log.WithError(err).Warn("Failed to create janitor job, resources will be cleaned up when ScanInstance is deleted")
			} else {
				log.Info("Janitor job created successfully for cleanup")
			}
		}

	case v1.Failed:
		// Scan failed
		// Check idempotency - only update if condition doesn't exist
		if !scanInstance.HasCondition(v1.Scanning, v1.Failed) {
			// Refetch job to get latest annotations (scan container may update them)
			latestJob, err := r.getScanJob(ctx, scanInstance)
			if err != nil {
				log.WithError(err).Error("error refetching scan job for error annotation")
				latestJob = scanJob
			}
			if latestJob == nil {
				latestJob = scanJob
			}

			// Read error message from job annotation if available
			errorReason := "Scan job failed"
			if latestJob.Annotations != nil {
				if errMsg, ok := latestJob.Annotations[internal.ScanErrorAnnotation]; ok && errMsg != "" {
					errorReason = errMsg
				}
			}

			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
				errorReason); uErr != nil {
				return ctrl.Result{}, uErr
			}

			// Generate event with the error message
			r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "ScanFailed",
				"Scan failed for ScanInstance %s: %s", scanInstance.Name, errorReason)

			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}

		// Keep failed job for debugging - it will be cleaned up when ScanInstance is deleted
		log.Debug("Scan job failed, keeping job for debugging")

	case v1.InProgress:
		// Scan still in progress
		if scanInstance.Status.Status != v1.ScanInProgress {
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanInProgress); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}

		// Check if job is stuck
		if helpers.IsJobPendingDeadlineExceeded(scanJob, internal.GetScanJobTimeoutSeconds()) {
			// Check idempotency - only update if no failed condition exists
			if !scanInstance.HasCondition(v1.Scanning, v1.Failed) {
				if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
					"Scan job pending deadline exceeded"); uErr != nil {
					return ctrl.Result{}, uErr
				}

				r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "ScanTimeout",
					"Scan job timed out for ScanInstance: %s", scanInstance.Name)

				if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
					return ctrl.Result{}, uErr
				}
			}

			// Keep stuck job for debugging
			log.Debug("Scan job exceeded pending deadline, keeping job for debugging")
			return ctrl.Result{}, nil
		}

		// Don't requeue - job watcher will trigger reconciliation when job status changes
		log.Debug("Scan job still in progress, waiting for job watcher to trigger reconciliation")
	}

	return ctrl.Result{}, nil
}

// reconcileScanPhase handles the scan phase after prescan completes
func (r *Reconciler) reconcileScanPhase(ctx context.Context, scanInstance, originalScanInstance *v1.ScanInstance) (ctrl.Result, error) {
	log := r.Log.WithField("scanInstance", scanInstance.Name)

	// Check if we've already moved to Scanning phase (idempotency)
	if !scanInstance.HasCondition(v1.Scanning, v1.InProgress) &&
		!scanInstance.HasCondition(v1.Scanning, v1.Completed) &&
		!scanInstance.HasCondition(v1.Scanning, v1.Failed) {

		// Only proceed if there are VM workloads to scan
		if len(scanInstance.Status.ScanLocations) == 0 {
			log.Info("No VM workloads to scan, marking as completed")
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanCompleted); uErr != nil {
				return ctrl.Result{}, uErr
			}
			return ctrl.Result{}, nil
		}

		// Check if Redis deployment phase is completed (idempotency)
		if !scanInstance.HasCondition(v1.RedisDeployment, v1.Ready) {
			return r.reconcileRedisDeployment(ctx, scanInstance, originalScanInstance)
		}

		// Check concurrency limit before creating scan resources
		canStart, activeCount, err := r.canStartNewScan(ctx)
		if err != nil {
			r.Log.WithError(err).Error("error checking scan concurrency limit")
			return ctrl.Result{}, err
		}

		if !canStart {
			maxConcurrent := internal.GetMaxConcurrentScans()
			log.Infof("Concurrent scan limit reached (%d/%d active). Requeuing after 1 minute...",
				activeCount, maxConcurrent)

			r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "ScanQueued",
				"Waiting for scan slot (concurrent limit: %d, active: %d)",
				maxConcurrent, activeCount)

			// Requeue after 1 minute to check again
			return ctrl.Result{RequeueAfter: time.Minute}, nil
		}

		log.Infof("Starting scan job (active scans: %d, max: %d)",
			activeCount, internal.GetMaxConcurrentScans())

		// Redis is ready, proceed to create configmap and scan job
		// Create scan configmap
		scanConfigMap, err := helpers.GetScanConfigMap(scanInstance)
		if err != nil {
			r.Log.WithError(err).Error("error occurred while creating scan configmap spec")
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
				fmt.Sprintf("Failed to create scan configmap: %v", err)); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
			return ctrl.Result{}, err
		}

		// Set owner reference
		if err := ctrl.SetControllerReference(scanInstance, scanConfigMap, r.Scheme); err != nil {
			r.Log.WithError(err).Error("error occurred while setting owner reference for scan configmap")
			return ctrl.Result{}, err
		}

		// Create the configmap
		if err := r.Client.Create(ctx, scanConfigMap); err != nil {
			if !apierrors.IsAlreadyExists(err) {
				r.Log.WithError(err).Error("error occurred while creating scan configmap")
				if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
					fmt.Sprintf("Failed to create scan configmap: %v", err)); uErr != nil {
					return ctrl.Result{}, uErr
				}
				if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
					return ctrl.Result{}, uErr
				}
				return ctrl.Result{}, err
			}
		}

		r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "ScanConfigMapCreated",
			"Scan configmap %s created for ScanInstance: %s", scanConfigMap.Name, scanInstance.Name)
		log.Infof("Created scan configmap: %s", scanConfigMap.Name)

		// Create scan secret with PostgreSQL credentials
		scanSecret, err := helpers.GetScanSecret(scanInstance)
		if err != nil {
			r.Log.WithError(err).Error("error occurred while creating scan secret spec")
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
				fmt.Sprintf("Failed to create scan secret: %v", err)); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
			return ctrl.Result{}, err
		}

		// Set owner reference for secret
		if err := ctrl.SetControllerReference(scanInstance, scanSecret, r.Scheme); err != nil {
			r.Log.WithError(err).Error("error occurred while setting owner reference for scan secret")
			return ctrl.Result{}, err
		}

		// Create the secret
		if err := r.Client.Create(ctx, scanSecret); err != nil {
			if !apierrors.IsAlreadyExists(err) {
				r.Log.WithError(err).Error("error occurred while creating scan secret")
				if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
					fmt.Sprintf("Failed to create scan secret: %v", err)); uErr != nil {
					return ctrl.Result{}, uErr
				}
				if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
					return ctrl.Result{}, uErr
				}
				return ctrl.Result{}, err
			}
		}

		r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "ScanSecretCreated",
			"Scan secret %s created for ScanInstance: %s", scanSecret.Name, scanInstance.Name)
		log.Infof("Created scan secret: %s", scanSecret.Name)

		// Create scan job (secret name is passed for envFrom)
		newScanJob, err := r.createScanJob(ctx, scanInstance, scanSecret.Name)
		if err != nil {
			r.Log.WithError(err).Error("error occurred while creating scan job")
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
				fmt.Sprintf("Failed to create scan job: %v", err)); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
			return ctrl.Result{}, err
		}

		// Update condition to Scanning InProgress
		if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.InProgress,
			"Starting scan job"); uErr != nil {
			return ctrl.Result{}, uErr
		}

		r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "ScanJobCreated",
			"Scan job %s created for ScanInstance: %s", newScanJob.Name, scanInstance.Name)
		log.Infof("Created scan job: %s", newScanJob.Name)

		return ctrl.Result{}, nil
	}

	// Check if Scanning phase is already completed (idempotency check)
	// CRITICAL: Check this BEFORE checking if job exists, since completed jobs are cleaned up
	if scanInstance.HasCondition(v1.Scanning, v1.Completed) {
		log.Debug("Scanning phase already completed, no further action needed")
		return ctrl.Result{}, nil
	}

	// Check if Scanning phase has failed (terminal state)
	if scanInstance.HasCondition(v1.Scanning, v1.Failed) {
		log.Info("Scanning phase has failed, ScanInstance is in terminal state")
		return ctrl.Result{}, nil
	}

	// If already in Scanning phase, check scan job status
	scanJob, err := r.getScanJob(ctx, scanInstance)
	if err != nil {
		r.Log.WithError(err).Error("error while getting scan job")
		return ctrl.Result{}, err
	}

	if scanJob == nil {
		// Scan job doesn't exist but should - this is an error state
		// Could happen if job was manually deleted
		// This should only happen if we're in Scanning/InProgress but job is missing
		log.Info("Scan job not found, marking as failed")
		if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
			"Scan job not found"); uErr != nil {
			return ctrl.Result{}, uErr
		}
		if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
			return ctrl.Result{}, uErr
		}
		return ctrl.Result{}, nil
	}

	// Process scan job status
	return r.processScanJobStatus(ctx, scanInstance, originalScanInstance, scanJob)
}

// createJanitorJob creates a janitor job to cleanup ScanInstance resources after scan completes
func (r *Reconciler) createJanitorJob(ctx context.Context, scanInstance *v1.ScanInstance) error {
	log := r.Log.WithField("scanInstance", scanInstance.Name)

	// Check if janitor job already exists (idempotency)
	janitorJobName := helpers.GetScanInstanceResourceName(internal.ScanInstanceJanitorJobPrefix, scanInstance.Name)
	existingJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      janitorJobName,
	}, existingJob); err == nil {
		log.Debug("Janitor job already exists")
		return nil
	} else if !apierrors.IsNotFound(err) {
		return fmt.Errorf("error checking for existing janitor job: %w", err)
	}

	// Create janitor job spec
	janitorJob, err := helpers.GetJanitorJob(scanInstance)
	if err != nil {
		return fmt.Errorf("error creating janitor job spec: %w", err)
	}

	// Set owner reference - janitor job is owned by ScanInstance
	// This ensures janitor job is cleaned up when ScanInstance is deleted
	if err := ctrl.SetControllerReference(scanInstance, janitorJob, r.Scheme); err != nil {
		return fmt.Errorf("error setting owner reference on janitor job: %w", err)
	}

	// Create the janitor job
	if err := r.Client.Create(ctx, janitorJob); err != nil {
		if apierrors.IsAlreadyExists(err) {
			log.Debug("Janitor job already exists (race condition)")
			return nil
		}
		return fmt.Errorf("error creating janitor job: %w", err)
	}

	r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "JanitorJobCreated",
		"Janitor job %s created for cleanup of ScanInstance: %s", janitorJob.Name, scanInstance.Name)

	log.Infof("Created janitor job: %s", janitorJob.Name)
	return nil
}

// countActiveScanJobs counts the number of active (running) scan jobs across all ScanInstances
// Active means scan jobs that are currently in InProgress state
func (r *Reconciler) countActiveScanJobs(ctx context.Context) (int, error) {
	// List all scan jobs managed by this controller
	jobList := &batchv1.JobList{}
	if err := r.Client.List(ctx, jobList,
		client.MatchingLabels{
			"app.kubernetes.io/managed-by": internal.ManagedBy,
			"app.kubernetes.io/component":  "scan",
		},
		client.InNamespace(internal.GetInstallNamespace()),
	); err != nil {
		return 0, fmt.Errorf("failed to list scan jobs: %w", err)
	}

	// Count jobs that are actively running (not completed or failed)
	activeCount := 0
	for i := range jobList.Items {
		job := &jobList.Items[i]
		jobStatus := helpers.GetJobStatus(job)
		if jobStatus == v1.InProgress {
			activeCount++
		}
	}

	return activeCount, nil
}

// canStartNewScan checks if we can start a new scan job based on concurrency limits
// Returns: (canStart bool, activeCount int, error)
// - canStart: true if we can start a new scan, false if limit reached
// - activeCount: current number of active scan jobs
// - error: any error encountered while checking
func (r *Reconciler) canStartNewScan(ctx context.Context) (bool, int, error) {
	maxConcurrent := internal.GetMaxConcurrentScans()

	// 0 means unlimited
	if maxConcurrent == 0 {
		return true, 0, nil
	}

	activeCount, err := r.countActiveScanJobs(ctx)
	if err != nil {
		return false, 0, err
	}

	return activeCount < maxConcurrent, activeCount, nil
}
