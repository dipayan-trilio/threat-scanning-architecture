package scaninstance

import (
	"context"
	"fmt"

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

	// TODO: Delete cleanup job for reports when implemented

	return nil
}

// cleanupScanInstanceJobs cleans up all jobs associated with a completed ScanInstance
// Following TVK pattern: jobs are deleted only when the main CR reaches terminal Completed state
// Failed jobs are not cleaned up here - they are kept for debugging and cleaned during CR deletion
func (r *Reconciler) cleanupScanInstanceJobs(ctx context.Context, scanInstance *v1.ScanInstance) error {
	log := r.Log.WithField("scanInstance", scanInstance.Name)

	jobsDeleted := 0
	var errors []string

	// Delete pre-scan job if exists and is completed successfully
	preScanJobName := helpers.GetScanInstanceResourceName(internal.ScanInstancePreScanPrefix, scanInstance.Name)
	preScanJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      preScanJobName,
	}, preScanJob); err == nil {
		// Use Foreground propagation to ensure pods are deleted before job
		// Following TVK pattern: CleanupJobs uses DeletePropagationForeground
		foregroundPolicy := metav1.DeletePropagationForeground
		if err := r.Client.Delete(ctx, preScanJob, &client.DeleteOptions{PropagationPolicy: &foregroundPolicy}); err != nil {
			if !apierrors.IsNotFound(err) {
				errors = append(errors, fmt.Sprintf("error deleting pre-scan job: %v", err))
			}
		} else {
			jobsDeleted++
			log.Infof("Deleted pre-scan job: %s", preScanJobName)
		}
	} else if !apierrors.IsNotFound(err) {
		errors = append(errors, fmt.Sprintf("error getting pre-scan job: %v", err))
	}

	// Delete scan job if exists
	scanJobName := helpers.GetScanInstanceResourceName(internal.ScanInstanceScanJobPrefix, scanInstance.Name)
	scanJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      scanJobName,
	}, scanJob); err == nil {
		foregroundPolicy := metav1.DeletePropagationForeground
		if err := r.Client.Delete(ctx, scanJob, &client.DeleteOptions{PropagationPolicy: &foregroundPolicy}); err != nil {
			if !apierrors.IsNotFound(err) {
				errors = append(errors, fmt.Sprintf("error deleting scan job: %v", err))
			}
		} else {
			jobsDeleted++
			log.Infof("Deleted scan job: %s", scanJobName)
		}
	} else if !apierrors.IsNotFound(err) {
		errors = append(errors, fmt.Sprintf("error getting scan job: %v", err))
	}

	// Delete scan configmap if exists
	configMapName := helpers.GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, scanInstance.Name)
	configMap := &corev1.ConfigMap{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      configMapName,
	}, configMap); err == nil {
		if err := r.Client.Delete(ctx, configMap); err != nil {
			if !apierrors.IsNotFound(err) {
				errors = append(errors, fmt.Sprintf("error deleting scan configmap: %v", err))
			}
		} else {
			jobsDeleted++
			log.Infof("Deleted scan configmap: %s", configMapName)
		}
	} else if !apierrors.IsNotFound(err) {
		errors = append(errors, fmt.Sprintf("error getting scan configmap: %v", err))
	}

	// TODO: Delete post-scan/cleanup jobs when implemented

	if len(errors) > 0 {
		return fmt.Errorf("cleanup errors: %v", errors)
	}

	log.Infof("Successfully cleaned up %d job(s) for completed ScanInstance", jobsDeleted)
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

	// Create pre-scan job spec with extracted parameters
	preScanJob, err := helpers.GetPreScanJob(ctx, r.Client, scanInstance, targetName, backupUID, backupPath)
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
func (r *Reconciler) createScanJob(ctx context.Context, scanInstance *v1.ScanInstance) (*batchv1.Job, error) {
	// Get scan job spec
	scanJob, err := helpers.GetScanJob(ctx, r.Client, scanInstance)
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
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Completed,
				"Scan completed successfully"); uErr != nil {
				return ctrl.Result{}, uErr
			}

			r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "ScanCompleted",
				"Scan completed successfully for ScanInstance: %s", scanInstance.Name)

			// Mark entire ScanInstance as completed
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanCompleted); uErr != nil {
				return ctrl.Result{}, uErr
			}

			log.Info("Scan completed successfully, ScanInstance marked as completed")
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
		if helpers.IsJobPendingDeadlineExceeded(scanJob) {
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

		// Create scan job
		newScanJob, err := r.createScanJob(ctx, scanInstance)
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

	// If already in Scanning phase, check scan job status
	scanJob, err := r.getScanJob(ctx, scanInstance)
	if err != nil {
		r.Log.WithError(err).Error("error while getting scan job")
		return ctrl.Result{}, err
	}

	if scanJob == nil {
		// Scan job doesn't exist but should - this is an error state
		// Could happen if job was manually deleted
		log.Info("Scan job not found, marking as failed")
		if !scanInstance.HasCondition(v1.Scanning, v1.Failed) {
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Failed,
				"Scan job not found"); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}
		return ctrl.Result{}, nil
	}

	// Process scan job status
	return r.processScanJobStatus(ctx, scanInstance, originalScanInstance, scanJob)
}
