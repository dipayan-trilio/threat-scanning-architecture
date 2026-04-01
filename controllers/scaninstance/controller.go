package scaninstance

import (
	"context"
	"fmt"

	"github.com/sirupsen/logrus"
	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	"github.com/trilioData/threat-scanning-architecture/internal"
	"github.com/trilioData/threat-scanning-architecture/pkg/helpers"
)

// Reconciler reconciles a ScanInstance object
type Reconciler struct {
	client.Client
	Log       *logrus.Entry
	Scheme    *runtime.Scheme
	Recorder  record.EventRecorder
	APIReader client.Reader
}

// +kubebuilder:rbac:groups=threatscanning.trilio.io,resources=scaninstances,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=threatscanning.trilio.io,resources=scaninstances/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=batch,resources=jobs,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch;create;delete;update
// +kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=pods,verbs=get;list
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch
// +kubebuilder:rbac:groups="admissionregistration.k8s.io",resources=validatingwebhookconfigurations,verbs=get;list;update
// +kubebuilder:rbac:groups="admissionregistration.k8s.io",resources=mutatingwebhookconfigurations,verbs=get;list;update

// Reconcile will be executed on every change for ScanInstance API resource
func (r *Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := r.Log.WithField("scanInstance", req.NamespacedName)

	scanInstance := &v1.ScanInstance{}
	if err := r.Client.Get(ctx, req.NamespacedName, scanInstance); err != nil {
		// Don't log error for NotFound - this is expected when scanInstance is deleted
		if !apierrors.IsNotFound(err) {
			r.Log.WithError(err).Errorf("error occurred while fetching the instance of ScanInstance: %s", req.String())
		}
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Early exit for terminal states to avoid unnecessary reconciliations
	// BUT: Allow deletion to proceed even in terminal states (finalizer must run)
	if !scanInstance.ObjectMeta.DeletionTimestamp.IsZero() {
		// ScanInstance is being deleted, let finalizer logic handle it
		log.Infof("ScanInstance is being deleted: %s", req.String())
	} else if scanInstance.Status.Status == v1.ScanCompleted || scanInstance.Status.Status == v1.ScanFailed {
		// ScanInstance is in terminal state and NOT being deleted, skip reconciliation
		log.Debug("ScanInstance is in terminal state, skipping reconciliation")
		return ctrl.Result{}, nil
	} else {
		// Normal reconciliation for active ScanInstance
		log.Infof("Fetching the ScanInstance resource: %s", req.String())
	}

	originalScanInstance := scanInstance.DeepCopy()

	// Handle finalizer for deletion
	reconcileDelete, delErr := r.reconcileScanInstanceDeleteFinalizer(ctx, scanInstance, originalScanInstance)
	if delErr != nil {
		r.Log.WithError(delErr).Error("error while reconciling ScanInstanceDeleteFinalizer")
		return ctrl.Result{}, delErr
	}
	if !reconcileDelete {
		return ctrl.Result{}, nil
	}

	// Initialize status if not set
	if scanInstance.Status.Status == "" {
		if err := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanQueued); err != nil {
			r.Log.WithError(err).Error("error while initializing ScanInstance status")
			return ctrl.Result{}, err
		}
	}

	// Check if PreScan phase is already completed (idempotency check)
	// If controller restarts, we should not recreate the job or reprocess
	if scanInstance.HasCondition(v1.PreScan, v1.Completed) {
		log.Info("PreScan phase already completed, proceeding to scan phase")
		// Proceed to scan phase
		return r.reconcileScanPhase(ctx, scanInstance, originalScanInstance)
	}

	// Check if PreScan phase has failed (terminal state)
	// Keep failed jobs for debugging - they will be cleaned up when ScanInstance is deleted
	if scanInstance.HasCondition(v1.PreScan, v1.Failed) {
		log.Info("PreScan phase has failed, ScanInstance is in terminal state")
		return ctrl.Result{}, nil
	}

	// Get or create preScan job
	preScanJob, err := r.getPreScanJob(ctx, scanInstance)
	if err != nil {
		r.Log.WithError(err).Error("error while getting PreScanJob")
		return ctrl.Result{}, err
	}

	// If preScan job doesn't exist and PreScan hasn't started, create it
	if preScanJob == nil {
		// Check if we already have a PreScan/InProgress condition (idempotency)
		if !scanInstance.HasCondition(v1.PreScan, v1.InProgress) {
			// Update condition to PreScan InProgress
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.InProgress,
				"Starting pre-scan validation"); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanInProgress); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}

		// Create preScan job
		// Webhook ensures target exists and is available
		// PreScan job will validate target accessibility and backup details
		newPreScanJob, err := r.createPreScanJob(ctx, scanInstance)
		if err != nil {
			r.Log.WithError(err).Error("error occurred while creating pre-scan job")
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Failed,
				fmt.Sprintf("Failed to create pre-scan job: %v", err)); uErr != nil {
				return ctrl.Result{}, uErr
			}
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
			return ctrl.Result{}, err
		}

		r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "PreScanJobCreated",
			"Pre-scan job %s created for ScanInstance: %s", newPreScanJob.Name, scanInstance.Name)

		log.Infof("Created pre-scan job: %s", newPreScanJob.Name)
		// Don't requeue - job watcher will trigger reconciliation when job status changes
		return ctrl.Result{}, nil
	}

	// Process existing preScan job
	jobStatus := helpers.GetJobStatusWithPodCheck(ctx, r.Client, preScanJob)
	log.Debugf("Found pre-scan job with name: %s and status: %v", preScanJob.Name, jobStatus)

	switch jobStatus {
	case v1.Completed:
		// PreScan completed successfully
		// Check idempotency - only update if condition doesn't exist
		if !scanInstance.HasCondition(v1.PreScan, v1.Completed) {
			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Completed,
				"Pre-scan validation completed successfully"); uErr != nil {
				return ctrl.Result{}, uErr
			}

			r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "PreScanCompleted",
				"Pre-scan completed successfully for ScanInstance: %s", scanInstance.Name)
		}

		// Proceed to scan phase
		return r.reconcileScanPhase(ctx, scanInstance, originalScanInstance)

	case v1.Failed:
		// PreScan failed
		// Check idempotency - only update if condition doesn't exist
		if !scanInstance.HasCondition(v1.PreScan, v1.Failed) {
			// Refetch job to get latest annotations (prescan container updates them)
			// Following TVK datamover pattern: job updates its own annotations, controller reads them
			latestJob, err := r.getPreScanJob(ctx, scanInstance)
			if err != nil {
				log.WithError(err).Error("error refetching prescan job for error annotation")
				// Continue with existing job if refetch fails
				latestJob = preScanJob
			}
			if latestJob == nil {
				// Job was deleted, use the one we have
				latestJob = preScanJob
			}

			// Read error message from job annotation if available
			// Prescan sets concise error message (traceback is in job logs)
			errorReason := "Pre-scan validation failed"
			if latestJob.Annotations != nil {
				if errMsg, ok := latestJob.Annotations[internal.PrescanErrorAnnotation]; ok && errMsg != "" {
					errorReason = errMsg
				}
			}

			if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Failed,
				errorReason); uErr != nil {
				return ctrl.Result{}, uErr
			}

			// Generate event with the error message
			r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanFailed",
				"Pre-scan failed for ScanInstance %s: %s", scanInstance.Name, errorReason)

			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}

		// Keep failed job for debugging - it will be cleaned up when ScanInstance is deleted
		// Following TVK pattern: failed jobs are kept for log inspection
		log.Debug("PreScan job failed, keeping job for debugging")

	case v1.InProgress:
		// PreScan still in progress
		if scanInstance.Status.Status != v1.ScanInProgress {
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanInProgress); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}

		// Check if job is stuck
		if helpers.IsJobPendingDeadlineExceeded(preScanJob, 0) { // 0 = use default timeout
			// Check idempotency - only update if no failed condition exists
			if !scanInstance.HasCondition(v1.PreScan, v1.Failed) {
				if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Failed,
					"Pre-scan job pending deadline exceeded"); uErr != nil {
					return ctrl.Result{}, uErr
				}

				r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanTimeout",
					"Pre-scan job timed out for ScanInstance: %s", scanInstance.Name)

				if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
					return ctrl.Result{}, uErr
				}
			}

			// Keep stuck job for debugging - it will be cleaned up when ScanInstance is deleted
			// Following TVK pattern: failed/stuck jobs are kept for log inspection
			log.Debug("PreScan job exceeded pending deadline, keeping job for debugging")
			return ctrl.Result{}, nil
		}

		// Don't requeue - job watcher will trigger reconciliation when job status changes
		log.Debug("PreScan job still in progress, waiting for job watcher to trigger reconciliation")
	}

	return ctrl.Result{}, nil
}

// SetupWithManager will attach this controller to manager
func (r *Reconciler) SetupWithManager(mgr ctrl.Manager) error {
	log := r.Log.WithField("function", "SetupWithManager")

	createFunction := func(e event.CreateEvent) bool {
		if e.Object == nil {
			log.Error("Create event has no runtime object to create")
			return false
		}

		// For Job: only process if managed by threat-scanning-controller
		if job, ok := e.Object.(*batchv1.Job); ok {
			managedBy, exists := job.GetLabels()["app.kubernetes.io/managed-by"]
			if !exists || managedBy != internal.ManagedBy {
				return false
			}
		}

		// For Deployment: only process if managed by threat-scanning-controller
		if deploy, ok := e.Object.(*appsv1.Deployment); ok {
			managedBy, exists := deploy.GetLabels()["app.kubernetes.io/managed-by"]
			if !exists || managedBy != internal.ManagedBy {
				return false
			}
		}

		return true
	}

	deleteFunction := func(e event.DeleteEvent) bool {
		// For Job: only process if managed by threat-scanning-controller
		if job, ok := e.Object.(*batchv1.Job); ok {
			managedBy, exists := job.GetLabels()["app.kubernetes.io/managed-by"]
			if !exists || managedBy != internal.ManagedBy {
				return false
			}
		}

		// For Deployment: only process if managed by threat-scanning-controller
		if deploy, ok := e.Object.(*appsv1.Deployment); ok {
			managedBy, exists := deploy.GetLabels()["app.kubernetes.io/managed-by"]
			if !exists || managedBy != internal.ManagedBy {
				return false
			}
		}

		return true
	}

	updateFunction := func(e event.UpdateEvent) bool {
		if e.ObjectNew == nil || e.ObjectOld == nil {
			return false
		}

		// For ScanInstance: only reconcile if generation changed (spec changed)
		if _, ok := e.ObjectNew.DeepCopyObject().(*v1.ScanInstance); ok {
			return e.ObjectNew.GetGeneration() != e.ObjectOld.GetGeneration()
		}

		// For Job: only reconcile if status changed and it's managed by us
		if currentJobObj, ok := e.ObjectNew.DeepCopyObject().(*batchv1.Job); ok {
			// Filter: Only process jobs managed by threat-scanning-controller
			managedBy, exists := currentJobObj.GetLabels()["app.kubernetes.io/managed-by"]
			if !exists || managedBy != internal.ManagedBy {
				return false
			}

			previousJobObj := e.ObjectOld.DeepCopyObject().(*batchv1.Job)

			// Only reconcile if job status actually changed
			if previousJobObj.Status.Active != currentJobObj.Status.Active ||
				previousJobObj.Status.Succeeded != currentJobObj.Status.Succeeded ||
				previousJobObj.Status.Failed != currentJobObj.Status.Failed {
				return true
			}
			return false
		}

		// For Deployment: only reconcile if status changed and it's managed by us
		if currentDeployObj, ok := e.ObjectNew.DeepCopyObject().(*appsv1.Deployment); ok {
			// Filter: Only process deployments managed by threat-scanning-controller
			managedBy, exists := currentDeployObj.GetLabels()["app.kubernetes.io/managed-by"]
			if !exists || managedBy != internal.ManagedBy {
				return false
			}

			previousDeployObj := e.ObjectOld.DeepCopyObject().(*appsv1.Deployment)

			// Only reconcile if deployment status changed (ready replicas, availability)
			if previousDeployObj.Status.ReadyReplicas != currentDeployObj.Status.ReadyReplicas ||
				previousDeployObj.Status.AvailableReplicas != currentDeployObj.Status.AvailableReplicas ||
				len(previousDeployObj.Status.Conditions) != len(currentDeployObj.Status.Conditions) {
				return true
			}
			return false
		}

		return true
	}

	p := predicate.Funcs{
		CreateFunc: createFunction,
		UpdateFunc: updateFunction,
		DeleteFunc: deleteFunction,
	}

	return ctrl.NewControllerManagedBy(mgr).
		For(&v1.ScanInstance{}).
		Watches(&batchv1.Job{}, handler.EnqueueRequestsFromMapFunc(r.jobHandler)).
		Watches(&appsv1.Deployment{}, handler.EnqueueRequestsFromMapFunc(r.deploymentHandler)).
		WithEventFilter(p).
		Complete(r)
}

func (r *Reconciler) jobHandler(ctx context.Context, obj client.Object) []reconcile.Request {
	if obj == nil {
		return nil
	}

	// Filter: Only process jobs managed by threat-scanning-controller
	managedBy, exists := obj.GetLabels()["app.kubernetes.io/managed-by"]
	if !exists || managedBy != internal.ManagedBy {
		return nil
	}

	// Get scan instance name from job label
	scanInstanceName, exists := obj.GetLabels()[internal.ScanInstanceNameLabel]
	if !exists {
		return nil
	}

	return []reconcile.Request{
		{NamespacedName: types.NamespacedName{Name: scanInstanceName}},
	}
}

func (r *Reconciler) deploymentHandler(ctx context.Context, obj client.Object) []reconcile.Request {
	if obj == nil {
		return nil
	}

	// Filter: Only process deployments managed by threat-scanning-controller
	managedBy, exists := obj.GetLabels()["app.kubernetes.io/managed-by"]
	if !exists || managedBy != internal.ManagedBy {
		return nil
	}

	// Get scan instance name from deployment label
	scanInstanceName, exists := obj.GetLabels()[internal.ScanInstanceNameLabel]
	if !exists {
		return nil
	}

	return []reconcile.Request{
		{NamespacedName: types.NamespacedName{Name: scanInstanceName}},
	}
}
