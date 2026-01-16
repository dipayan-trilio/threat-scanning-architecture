package scaninstance

import (
	"context"
	"fmt"

	"github.com/sirupsen/logrus"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
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
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch

// Reconcile will be executed on every change for ScanInstance API resource
func (r *Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := r.Log.WithField("scanInstance", req.NamespacedName)

	log.Infof("Fetching the ScanInstance resource: %s", req.String())
	scanInstance := &v1.ScanInstance{}
	if err := r.Client.Get(ctx, req.NamespacedName, scanInstance); err != nil {
		// Don't log error for NotFound - this is expected when scanInstance is deleted
		if !apierrors.IsNotFound(err) {
			r.Log.WithError(err).Errorf("error occurred while fetching the instance of ScanInstance: %s", req.String())
		}
		return ctrl.Result{}, client.IgnoreNotFound(err)
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

	// Get or create preScan job
	preScanJob, err := r.getPreScanJob(ctx, scanInstance)
	if err != nil {
		r.Log.WithError(err).Error("error while getting PreScanJob")
		return ctrl.Result{}, err
	}

	// If preScan job doesn't exist, create it
	if preScanJob == nil {
		// Update condition to PreScan InProgress
		if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.InProgress,
			"Starting pre-scan validation"); uErr != nil {
			return ctrl.Result{}, uErr
		}
		if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanInProgress); uErr != nil {
			return ctrl.Result{}, uErr
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
		// Only update if not already in completed state
		if scanInstance.Status.Status != v1.ScanCompleted {
			// Check if we already have a PreScan/Completed condition to avoid duplicates
			hasCompletedCondition := false
			for _, cond := range scanInstance.Status.Condition {
				if cond.Phase == v1.PreScan && cond.Status == v1.Completed {
					hasCompletedCondition = true
					break
				}
			}

			if !hasCompletedCondition {
				if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Completed,
					"Pre-scan validation completed successfully"); uErr != nil {
					return ctrl.Result{}, uErr
				}

				r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "PreScanCompleted",
					"Pre-scan completed successfully for ScanInstance: %s", scanInstance.Name)
			}

			// TODO: Proceed to create scan job
			// For now, mark as completed since we're using placeholders
			// if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanCompleted); uErr != nil {
			// 	return ctrl.Result{}, uErr
			// }
		}

	case v1.Failed:
		// PreScan failed
		// Only update if not already in failed state
		if scanInstance.Status.Status != v1.ScanFailed {
			// Check if we already have a PreScan/Failed condition to avoid duplicates
			hasFailedCondition := false
			for _, cond := range scanInstance.Status.Condition {
				if cond.Phase == v1.PreScan && cond.Status == v1.Failed {
					hasFailedCondition = true
					break
				}
			}

			if !hasFailedCondition {
				if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Failed,
					"Pre-scan validation failed"); uErr != nil {
					return ctrl.Result{}, uErr
				}

				r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanFailed",
					"Pre-scan failed for ScanInstance: %s", scanInstance.Name)
			}

			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}

		// Delete the failed job (idempotent - safe to call multiple times)
		propagationPolicy := metav1.DeletePropagationBackground
		if dErr := r.Client.Delete(ctx, preScanJob, &client.DeleteOptions{PropagationPolicy: &propagationPolicy}); dErr != nil {
			if !apierrors.IsNotFound(dErr) {
				return ctrl.Result{}, dErr
			}
		}

	case v1.InProgress:
		// PreScan still in progress
		if scanInstance.Status.Status != v1.ScanInProgress {
			if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanInProgress); uErr != nil {
				return ctrl.Result{}, uErr
			}
		}

		// Check if job is stuck
		if helpers.IsJobPendingDeadlineExceeded(preScanJob) {
			// Only update if not already failed
			if scanInstance.Status.Status != v1.ScanFailed {
				// Check if we already have a timeout condition to avoid duplicates
				hasTimeoutCondition := false
				for _, cond := range scanInstance.Status.Condition {
					if cond.Phase == v1.PreScan && cond.Status == v1.Failed &&
						cond.Reason == "Pre-scan job pending deadline exceeded" {
						hasTimeoutCondition = true
						break
					}
				}

				if !hasTimeoutCondition {
					if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Failed,
						"Pre-scan job pending deadline exceeded"); uErr != nil {
						return ctrl.Result{}, uErr
					}

					r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanTimeout",
						"Pre-scan job timed out for ScanInstance: %s", scanInstance.Name)
				}

				if uErr := r.updateScanInstanceStatus(ctx, scanInstance, originalScanInstance, v1.ScanFailed); uErr != nil {
					return ctrl.Result{}, uErr
				}
			}

			// Delete the stuck job (idempotent - safe to call multiple times)
			propagationPolicy := metav1.DeletePropagationBackground
			if dErr := r.Client.Delete(ctx, preScanJob, &client.DeleteOptions{PropagationPolicy: &propagationPolicy}); dErr != nil {
				if !apierrors.IsNotFound(dErr) {
					return ctrl.Result{}, dErr
				}
			}
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
