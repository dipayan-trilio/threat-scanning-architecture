package target

import (
	"context"
	"fmt"
	"time"

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

// Reconciler reconciles a Target object
type Reconciler struct {
	client.Client
	Log       *logrus.Entry
	Scheme    *runtime.Scheme
	Recorder  record.EventRecorder
	APIReader client.Reader
}

// +kubebuilder:rbac:groups=threatscanning.trilio.io,resources=targets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=threatscanning.trilio.io,resources=targets/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=batch,resources=jobs,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=persistentvolumes,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch

// Reconcile will be executed on every change for Target API resource
func (r *Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := r.Log.WithField("target", req.NamespacedName)

	var (
		currentSpecCredentialsHash string
		isTargetCredentialsUpdated bool
		validationJob              *batchv1.Job
		nfsPVC                     *corev1.PersistentVolumeClaim
		nfsPV                      *corev1.PersistentVolume
		err                        error
	)

	log.Infof("Fetching the Target resource: %s", req.String())
	target := &v1.Target{}
	if err = r.Client.Get(ctx, req.NamespacedName, target); err != nil {
		// Don't log error for NotFound - this is expected when target is deleted
		if !apierrors.IsNotFound(err) {
			r.Log.WithError(err).Errorf("error occurred while fetching the instance of Target: %s", req.String())
		}
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	originalTarget := target.DeepCopy()

	// Handle finalizer for deletion
	reconcileDelete, delErr := r.reconcileTargetDeleteFinalizer(ctx, target, originalTarget)
	if delErr != nil {
		r.Log.WithError(delErr).Error("error while reconciling TargetDeleteFinalizer")
		return ctrl.Result{}, delErr
	}
	if !reconcileDelete {
		return ctrl.Result{}, nil
	}

	// Calculate current credential hash
	if currentSpecCredentialsHash, err = helpers.GetTargetCredentialsHash(ctx, r.Client, target); err != nil {
		return ctrl.Result{}, err
	}

	// Check if target credentials have been updated
	isTargetCredentialsUpdated = target.Annotations[internal.TargetCredentialsHashAnnotationKey] != currentSpecCredentialsHash

	// Check if target type has changed (e.g., reporting to backup conversion)
	// This requires re-validation as validation logic differs between types
	isTargetTypeChanged := r.isTargetTypeChanged(target, originalTarget)
	if isTargetTypeChanged {
		r.Log.Infof("Target type changed for target %s, triggering re-validation", target.Name)
		// Treat type change as credential change to force re-validation
		isTargetCredentialsUpdated = true
	}

	if isTargetCredentialsUpdated || target.Status.Status == "" {
		// Mark Target in InProgress status
		var updateCondition bool
		credReason := fmt.Sprintf("Target credentials changed to hash %s", currentSpecCredentialsHash)
		condition := v1.TargetCondition{Timestamp: &metav1.Time{Time: time.Now()}, Reason: credReason}

		if len(target.Status.Condition) > 0 {
			lastCondition := target.LastMatchingTargetCondition(condition)
			// When the previous credential change reason is same as of the current reason, then don't update the target condition
			if lastCondition == nil || lastCondition.Reason != condition.Reason {
				updateCondition = true
				target.Status.Condition = append(target.Status.Condition, condition)
			}
		} else {
			updateCondition = true
			target.Status.Condition = append(target.Status.Condition, condition)
		}

		if updateCondition {
			if rErr := r.updateTargetStatus(ctx, target, originalTarget, v1.InProgress); rErr != nil {
				r.Log.WithError(rErr).Error("error while updating Target status")
				return ctrl.Result{}, rErr
			}
		}
	}

	// Sync NFS volumes if target is NFS type
	if nfsPV, nfsPVC, err = r.syncNFSVolumes(ctx, target, originalTarget, currentSpecCredentialsHash); err != nil {
		r.Log.WithError(err).Error("error while syncing NFS volumes")
		return ctrl.Result{}, err
	}

	// Cleanup old resources if credentials were updated
	if isTargetCredentialsUpdated {
		if oldCredHash, exists := target.Annotations[internal.TargetCredentialsHashAnnotationKey]; exists {
			if cErr := r.cleanupResourcesForTargetHash(ctx, target, oldCredHash, currentSpecCredentialsHash); cErr != nil {
				return ctrl.Result{}, cErr
			}
		}
	}

	// Reconcile NFS volumes for NFS targets
	if target.Spec.Type == v1.NFS {
		if rErr := r.reconcileNFSVolumes(ctx, target, originalTarget, currentSpecCredentialsHash, nfsPV, nfsPVC); rErr != nil {
			r.Log.WithError(rErr).Error("error occurred while reconciling NFS volumes")
			return ctrl.Result{}, rErr
		}
	}

	// Get or create validation configmap
	validatorConfigMap, err := r.reconcileValidationConfigMap(ctx)
	if err != nil {
		r.Log.WithError(err).Error("error while reconciling validation config map")
		return ctrl.Result{}, err
	}

	runValidation, validationStatus, err := r.processValidationConfigMap(ctx, target, originalTarget,
		currentSpecCredentialsHash, validatorConfigMap)
	if err != nil {
		r.Log.WithError(err).Error("error while processing validation config map")
		return ctrl.Result{}, err
	}

	// Exit condition for unavailable targets to avoid recreation of validation jobs for failed Targets
	if validationStatus == v1.InvalidTargetCredential && target.Status.Status == v1.Unavailable {
		r.Log.Debug("exiting the reconciliation for already failed target")
		return ctrl.Result{}, nil
	}

	if runValidation {
		validationJob, err = r.getValidationJob(ctx, currentSpecCredentialsHash)
		if err != nil {
			r.Log.WithError(err).Error("error while getting ValidationJob")
			return ctrl.Result{}, err
		}

		if isTargetCredentialsUpdated || validationJob != nil || target.Status.Status == v1.InProgress {
			continueReconcile, rErr := r.reconcileValidationJob(ctx, target, originalTarget, currentSpecCredentialsHash,
				validationJob, validationStatus)
			if rErr != nil {
				r.Log.WithError(rErr).Error("error occurred while reconciling target validation job")
				return ctrl.Result{}, rErr
			}

			if (!continueReconcile || validationJob != nil) && isTargetCredentialsUpdated {
				// Update credential hash annotation
				if err = r.updateTargetCredentialsChangeHash(ctx, target, originalTarget, currentSpecCredentialsHash); err != nil {
					r.Log.WithError(err).Error("error occurred while updating changed credentials hash")
					return ctrl.Result{}, err
				}
				return ctrl.Result{RequeueAfter: time.Duration(internal.PendingDeadlineSeconds) * time.Second}, nil
			}
		}
	}

	if isTargetCredentialsUpdated {
		if rErr := r.updateTargetCredentialsChangeHash(ctx, target, originalTarget, currentSpecCredentialsHash); rErr != nil {
			r.Log.WithError(rErr).Error("error occurred while updating changed credentials hash")
			return ctrl.Result{}, rErr
		}
	}

	// Create poller cronjob if target is available and not a reporting target
	if target.Status.Status == v1.Available && !target.IsReportingTarget() {
		if err := r.reconcilePollerCronJob(ctx, target, currentSpecCredentialsHash); err != nil {
			r.Log.WithError(err).Error("error occurred while reconciling poller cronjob")
			return ctrl.Result{}, err
		}
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
		return true
	}

	deleteFunction := func(e event.DeleteEvent) bool {
		return true
	}

	updateFunction := func(e event.UpdateEvent) bool {
		if e.ObjectNew == nil || e.ObjectOld == nil {
			return false
		}

		if _, ok := e.ObjectNew.DeepCopyObject().(*v1.Target); ok {
			if e.ObjectNew.GetGeneration() == e.ObjectOld.GetGeneration() {
				return false
			}
		}

		if currentJobObj, ok := e.ObjectNew.DeepCopyObject().(*batchv1.Job); ok {
			previousJobObj := e.ObjectOld.DeepCopyObject().(*batchv1.Job)

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
		For(&v1.Target{}).
		Watches(&batchv1.Job{}, handler.EnqueueRequestsFromMapFunc(r.jobHandler)).
		Watches(&batchv1.CronJob{}, handler.EnqueueRequestsFromMapFunc(r.cronjobHandler)).
		Watches(&corev1.Secret{}, handler.EnqueueRequestsFromMapFunc(r.secretHandler)).
		Watches(&corev1.ConfigMap{}, handler.EnqueueRequestsFromMapFunc(r.configmapHandler)).
		Watches(&corev1.PersistentVolumeClaim{}, handler.EnqueueRequestsFromMapFunc(r.pvcHandler)).
		WithEventFilter(p).
		Complete(r)
}

func (r *Reconciler) jobHandler(ctx context.Context, obj client.Object) []reconcile.Request {
	if obj == nil {
		return nil
	}

	// Get credential hash from job annotation
	credHash, exists := obj.GetAnnotations()[internal.TargetCredentialsHashAnnotationKey]
	if !exists {
		return nil
	}

	// Find all targets with this credential hash
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		r.Log.Error(err, "error listing targets")
		return nil
	}

	var requests []reconcile.Request
	for i := range targets.Items {
		targetHash, exists := targets.Items[i].Annotations[internal.TargetCredentialsHashAnnotationKey]
		if exists && targetHash == credHash {
			requests = append(requests, reconcile.Request{
				NamespacedName: types.NamespacedName{Name: targets.Items[i].Name},
			})
		}
	}

	return requests
}

func (r *Reconciler) secretHandler(ctx context.Context, obj client.Object) []reconcile.Request {
	if obj == nil {
		return nil
	}

	// Find all targets that reference this secret
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		r.Log.Error(err, "error listing targets")
		return nil
	}

	var requests []reconcile.Request
	for i := range targets.Items {
		target := &targets.Items[i]
		if target.HasObjectStoreCredentialSecret() &&
			target.Spec.ObjectStoreCredentials.CredentialSecret.Name == obj.GetName() {
			requests = append(requests, reconcile.Request{
				NamespacedName: types.NamespacedName{Name: target.Name},
			})
		}
	}

	return requests
}

func (r *Reconciler) configmapHandler(ctx context.Context, obj client.Object) []reconcile.Request {
	if obj == nil {
		return nil
	}

	// Handle validation configmap changes
	if obj.GetName() == internal.TargetValidationConfig && obj.GetNamespace() == internal.GetInstallNamespace() {
		targets := &v1.TargetList{}
		if err := r.Client.List(ctx, targets); err != nil {
			r.Log.Error(err, "error listing targets")
			return nil
		}

		var requests []reconcile.Request
		for i := range targets.Items {
			requests = append(requests, reconcile.Request{
				NamespacedName: types.NamespacedName{Name: targets.Items[i].Name},
			})
		}
		return requests
	}

	// Find all targets that reference this configmap for SSL cert
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		r.Log.Error(err, "error listing targets")
		return nil
	}

	var requests []reconcile.Request
	for i := range targets.Items {
		target := &targets.Items[i]
		if target.HasSSLCertConfig() &&
			target.Spec.ObjectStoreCredentials.SSLCertConfig.CertConfigMap.Name == obj.GetName() {
			requests = append(requests, reconcile.Request{
				NamespacedName: types.NamespacedName{Name: target.Name},
			})
		}
	}

	return requests
}

func (r *Reconciler) pvcHandler(ctx context.Context, obj client.Object) []reconcile.Request {
	if obj == nil {
		return nil
	}

	// Get credential hash from PVC annotation
	credHash, exists := obj.GetAnnotations()[internal.TargetCredentialsHashAnnotationKey]
	if !exists {
		return nil
	}

	// Find all targets with this credential hash
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		r.Log.Error(err, "error listing targets")
		return nil
	}

	var requests []reconcile.Request
	for i := range targets.Items {
		targetHash, exists := targets.Items[i].Annotations[internal.TargetCredentialsHashAnnotationKey]
		if exists && targetHash == credHash {
			requests = append(requests, reconcile.Request{
				NamespacedName: types.NamespacedName{Name: targets.Items[i].Name},
			})
		}
	}

	return requests
}

func (r *Reconciler) cronjobHandler(ctx context.Context, obj client.Object) []reconcile.Request {
	if obj == nil {
		return nil
	}

	// Get credential hash from cronjob annotation/label
	// CronJob uses credential hash in both labels and annotations
	credHash, exists := obj.GetAnnotations()[internal.TargetCredentialsHashAnnotationKey]
	if !exists {
		// Fall back to labels for backward compatibility
		credHash, exists = obj.GetLabels()[internal.TargetCredentialsHashAnnotationKey]
		if !exists {
			return nil
		}
	}

	// Find all targets with this credential hash
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		r.Log.Error(err, "error listing targets")
		return nil
	}

	var requests []reconcile.Request
	for i := range targets.Items {
		targetHash, exists := targets.Items[i].Annotations[internal.TargetCredentialsHashAnnotationKey]
		if exists && targetHash == credHash {
			requests = append(requests, reconcile.Request{
				NamespacedName: types.NamespacedName{Name: targets.Items[i].Name},
			})
		}
	}

	return requests
}

// isTargetTypeChanged checks if the target type has changed
// This is important for detecting reporting <-> backup conversions
func (r *Reconciler) isTargetTypeChanged(current, original *v1.Target) bool {
	// Check if target type annotation changed
	currentIsReporting := current.IsReportingTarget()
	originalIsReporting := original.IsReportingTarget()

	if currentIsReporting != originalIsReporting {
		return true
	}

	// Check if NFS vs ObjectStore type changed
	if current.Spec.Type != original.Spec.Type {
		return true
	}

	return false
}
