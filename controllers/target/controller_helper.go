package target

import (
	"context"
	"encoding/json"
	"fmt"

	"gomodules.xyz/jsonpatch/v2"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	ref "k8s.io/client-go/tools/reference"
	"k8s.io/client-go/util/retry"
	"sigs.k8s.io/controller-runtime/pkg/client"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	"github.com/trilioData/threat-scanning-architecture/internal"
	"github.com/trilioData/threat-scanning-architecture/pkg/helpers"
)

func (r *Reconciler) reconcileTargetDeleteFinalizer(ctx context.Context, targetInstance,
	originalTarget *v1.Target) (continueReconcile bool, err error) {

	if targetInstance.ObjectMeta.DeletionTimestamp.IsZero() &&
		!internal.ContainsString(targetInstance.Finalizers, internal.TargetDeleteFinalizer) {
		finalizers := targetInstance.ObjectMeta.Finalizers
		finalizers = append(finalizers, internal.TargetDeleteFinalizer)
		retErr := retry.RetryOnConflict(retry.DefaultRetry, func() error {
			err = r.Get(ctx, types.NamespacedName{Name: targetInstance.Name}, targetInstance)
			if err != nil {
				return err
			}
			targetInstance.ObjectMeta.Finalizers = finalizers
			return r.Update(ctx, targetInstance)
		})
		if retErr != nil {
			return continueReconcile, fmt.Errorf("error while updating finalizer: %w", retErr)
		}
		targetInstance.DeepCopyInto(originalTarget)
	} else if !targetInstance.ObjectMeta.DeletionTimestamp.IsZero() &&
		internal.ContainsString(targetInstance.ObjectMeta.Finalizers, internal.TargetDeleteFinalizer) {
		r.Log.Infof("cleaning up target resources for target:%s", targetInstance.Name)

		// Cleanup validation resources
		if err := r.cleanupTargetResources(ctx, targetInstance); err != nil {
			return continueReconcile, fmt.Errorf("error while cleaning target resources: %w", err)
		}

		// Remove finalizer with retry to handle ResourceVersion conflicts
		retErr := retry.RetryOnConflict(retry.DefaultRetry, func() error {
			// Refetch the target to get the latest ResourceVersion
			err = r.Get(ctx, types.NamespacedName{Name: targetInstance.Name}, targetInstance)
			if err != nil {
				// If target is already deleted, no need to remove finalizer
				if apierrors.IsNotFound(err) {
					return nil
				}
				return err
			}
			targetInstance.ObjectMeta.Finalizers = internal.RemoveString(targetInstance.ObjectMeta.Finalizers, internal.TargetDeleteFinalizer)
			return r.Update(ctx, targetInstance)
		})
		if retErr != nil {
			return continueReconcile, fmt.Errorf("error while updating finalizer: %w", retErr)
		}
		return continueReconcile, nil
	}

	return true, nil
}

func (r *Reconciler) cleanupTargetResources(ctx context.Context, target *v1.Target) error {
	// Get credential hash
	credHash, exists := target.Annotations[internal.TargetCredentialsHashAnnotationKey]
	if !exists {
		return nil
	}

	// Check if any other target (not being deleted) is using the same credential hash
	isHashInUse := false
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		return fmt.Errorf("error listing targets for cleanup: %w", err)
	}

	currentTargetName := target.Name
	for i := range targets.Items {
		t := &targets.Items[i]
		// Skip the current target being deleted
		if t.Name == currentTargetName {
			continue
		}
		// Skip targets that are also being deleted
		if !t.DeletionTimestamp.IsZero() {
			continue
		}
		// Check if this target uses the same credential hash
		targetHash, hashExists := t.Annotations[internal.TargetCredentialsHashAnnotationKey]
		if hashExists && targetHash == credHash {
			isHashInUse = true
			r.Log.Infof("Credential hash %s is still in use by target %s, skipping resource cleanup", credHash, t.Name)
			break
		}
	}

	// If credential hash is still in use by other targets, don't delete shared resources
	if isHashInUse {
		r.Log.Infof("Skipping cleanup of shared resources for credential hash %s (still in use)", credHash)
		// Still sync ConfigMap to clean up this target's stale entry
		if err := r.syncValidationConfigMap(ctx); err != nil {
			r.Log.WithError(err).Error("error syncing validation configmap during cleanup")
		}
		return nil
	}

	r.Log.Infof("Credential hash %s is no longer in use, cleaning up shared resources", credHash)

	// Delete validation job (safe to delete - no other target needs it)
	jobName := helpers.GetTargetResourceName(internal.TargetValidationPrefix, credHash)
	job := &batchv1.Job{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      jobName,
	}, job); err == nil {
		// Use Background propagation to delete pods along with the job
		backgroundPolicy := metav1.DeletePropagationBackground
		if err := r.Client.Delete(ctx, job, &client.DeleteOptions{PropagationPolicy: &backgroundPolicy}); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting validation job: %w", err)
		}
		r.Log.Infof("Deleted validation job: %s", jobName)
	}

	// Delete poller cronjob (safe to delete - no other target needs it)
	cronJobName := helpers.GetTargetResourceName(internal.TargetPollerPrefix, credHash)
	cronJob := &batchv1.CronJob{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      cronJobName,
	}, cronJob); err == nil {
		if err := r.Client.Delete(ctx, cronJob); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error deleting poller cronjob: %w", err)
		}
		r.Log.Infof("Deleted poller cronjob: %s", cronJobName)
	}

	// Delete NFS volumes if NFS target (safe to delete - no other target needs them)
	if target.IsNFSTarget() {
		volumeName := helpers.GetTargetResourceName(internal.TargetNFSVolumePrefix, credHash)

		pvc := &corev1.PersistentVolumeClaim{}
		if err := r.Client.Get(ctx, types.NamespacedName{
			Namespace: internal.GetInstallNamespace(),
			Name:      volumeName,
		}, pvc); err == nil {
			if err := r.Client.Delete(ctx, pvc); err != nil && !apierrors.IsNotFound(err) {
				return fmt.Errorf("error deleting PVC: %w", err)
			}
			r.Log.Infof("Deleted NFS PVC: %s", volumeName)
		}

		pv := &corev1.PersistentVolume{}
		if err := r.Client.Get(ctx, types.NamespacedName{Name: volumeName}, pv); err == nil {
			if err := r.Client.Delete(ctx, pv); err != nil && !apierrors.IsNotFound(err) {
				return fmt.Errorf("error deleting PV: %w", err)
			}
			r.Log.Infof("Deleted NFS PV: %s", volumeName)
		}
	}

	// Sync validation ConfigMap to remove stale credential hashes
	// This follows k8s-triliovault approach: cleanup all stale hashes during any target deletion
	if err := r.syncValidationConfigMap(ctx); err != nil {
		r.Log.WithError(err).Error("error syncing validation configmap during cleanup")
		// Don't fail cleanup, just log the error
	}

	return nil
}

func (r *Reconciler) syncNFSVolumes(ctx context.Context, newTarget, originalTarget *v1.Target, newCredHash string) (
	*corev1.PersistentVolume, *corev1.PersistentVolumeClaim, error) {
	var shouldPatch bool

	pv := &corev1.PersistentVolume{}
	pvc := &corev1.PersistentVolumeClaim{}

	pvName := types.NamespacedName{
		Name: helpers.GetTargetResourceName(internal.TargetNFSVolumePrefix, newCredHash),
	}
	if err := r.Client.Get(ctx, pvName, pv); err != nil {
		if !apierrors.IsNotFound(err) {
			return nil, nil, fmt.Errorf("error occurred while getting PV: %w", err)
		}
		pv = nil
	}

	pvcName := types.NamespacedName{
		Name:      helpers.GetTargetResourceName(internal.TargetNFSVolumePrefix, newCredHash),
		Namespace: internal.GetInstallNamespace(),
	}
	if err := r.Client.Get(ctx, pvcName, pvc); err != nil {
		if !apierrors.IsNotFound(err) {
			return nil, nil, fmt.Errorf("error occurred while getting PVC: %w", err)
		}
		pvc = nil
	}

	if pv != nil && pv.DeletionTimestamp != nil {
		pv = nil
		newTarget.Status.NFSPersistentVolume = nil
		shouldPatch = true
	}

	if pvc != nil && pvc.DeletionTimestamp != nil {
		pvc = nil
		newTarget.Status.NFSPersistentVolumeClaim = nil
		shouldPatch = true
	}

	// If the target type changes, then clear the PV & PVC object references from the target status
	if newTarget.Spec.Type != v1.NFS {
		newTarget.Status.NFSPersistentVolume = nil
		newTarget.Status.NFSPersistentVolumeClaim = nil
		shouldPatch = true
	}

	if shouldPatch {
		if err := r.Client.Status().Patch(ctx, newTarget, client.MergeFrom(originalTarget)); err != nil {
			return nil, nil, err
		}
		newTarget.DeepCopyInto(originalTarget)
	}

	return pv, pvc, nil
}

func (r *Reconciler) cleanupResourcesForTargetHash(ctx context.Context, tgt *v1.Target,
	oldTargetHash, currentTargetHash string) error {
	if oldTargetHash == "" {
		return nil
	}

	isHashInUse := false
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		return err
	}

	currentTargetName := tgt.Name
	for i := range targets.Items {
		if targets.Items[i].Name != currentTargetName {
			targetHash, exists := targets.Items[i].Annotations[internal.TargetCredentialsHashAnnotationKey]
			if exists && targetHash == oldTargetHash {
				isHashInUse = true
				break
			}
		}
	}

	if isHashInUse {
		return nil
	}

	// Delete NFS resources
	nfsVolumeName := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      helpers.GetTargetResourceName(internal.TargetNFSVolumePrefix, oldTargetHash),
	}

	for _, object := range []client.Object{&corev1.PersistentVolumeClaim{}, &corev1.PersistentVolume{}} {
		if err := r.Client.Get(ctx, nfsVolumeName, object); err != nil {
			if !apierrors.IsNotFound(err) {
				return fmt.Errorf("error occurred while getting object: %w", err)
			}
			continue
		}
		if objectHash := object.GetAnnotations()[internal.TargetCredentialsHashAnnotationKey]; objectHash == currentTargetHash {
			continue
		}
		if err := r.Client.Delete(ctx, object); err != nil && !apierrors.IsNotFound(err) {
			return fmt.Errorf("error occurred while deleting object: %w", err)
		}
	}

	// Delete failed validation job
	validationJobName := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      helpers.GetTargetResourceName(internal.TargetValidationPrefix, oldTargetHash),
	}

	validationJob := &batchv1.Job{}
	if err := r.Client.Get(ctx, validationJobName, validationJob); err != nil {
		if !apierrors.IsNotFound(err) {
			return fmt.Errorf("error occurred while getting job: %w", err)
		}
		return nil
	}
	if jobHash := validationJob.GetAnnotations()[internal.TargetCredentialsHashAnnotationKey]; jobHash == currentTargetHash {
		return nil
	}

	if err := r.Client.Delete(ctx, validationJob); err != nil && !apierrors.IsNotFound(err) {
		return fmt.Errorf("error occurred while deleting validation job: %w", err)
	}

	return nil
}

func (r *Reconciler) reconcileNFSVolumes(ctx context.Context, newTarget, originalTarget *v1.Target,
	newCredHash string, pv *corev1.PersistentVolume, pvc *corev1.PersistentVolumeClaim) error {
	log := r.Log.WithField("function", "reconcileNFSVolumes")

	var (
		pvObjectRef, pvcObjectRef *corev1.ObjectReference
		err                       error
	)

	log.Debug("Reconciling NFS volumes")
	name := helpers.GetTargetResourceName(internal.TargetNFSVolumePrefix, newCredHash)
	if pv == nil {
		newPv := helpers.GetNFSPersistentVolume(newTarget, newCredHash)
		log.Infof("Creating NFS volume: %s", name)
		if err = r.Client.Create(ctx, newPv); err != nil {
			return fmt.Errorf("error while creating the NFS volume: %w", err)
		}
		if pvObjectRef, err = ref.GetReference(r.Scheme, newPv); err != nil {
			return fmt.Errorf("error while getting object reference: %w", err)
		}
		pv = newPv
	} else if pvObjectRef, err = ref.GetReference(r.Scheme, pv); err != nil {
		return fmt.Errorf("error while getting object reference: %w", err)
	}

	if pvc == nil {
		// If PVC deleted bound to old PV
		if pv.Spec.ClaimRef != nil {
			log.Infof("Removing claim from already existing pv: %s", pv.Name)
			if err = removePVCRefFromPV(ctx, r.Client, pv); err != nil {
				return fmt.Errorf("error while setting claim ref to nil: %w", err)
			}
		}

		log.Infof("Creating NFS PVC: %s", name)
		newPvc := helpers.GetNFSPersistentVolumeClaim(newCredHash, pv)

		if err = r.Client.Create(ctx, newPvc); err != nil {
			return fmt.Errorf("error while creating the NFS PVC: %w", err)
		}
		if pvcObjectRef, err = ref.GetReference(r.Scheme, newPvc); err != nil {
			return fmt.Errorf("error while getting object reference: %w", err)
		}
	} else if pvcObjectRef, err = ref.GetReference(r.Scheme, pvc); err != nil {
		return fmt.Errorf("error while getting object reference: %w", err)
	}

	newTarget.Status.NFSPersistentVolume = pvObjectRef
	newTarget.Status.NFSPersistentVolumeClaim = pvcObjectRef
	if err = r.updateTargetStatus(ctx, newTarget, originalTarget, newTarget.Status.Status); err != nil {
		return fmt.Errorf("error while updating target status: %w", err)
	}

	log.Info("Successfully reconciled NFS Volumes")
	return nil
}

func removePVCRefFromPV(ctx context.Context, cl client.Client, pv *corev1.PersistentVolume) error {
	payload := []jsonpatch.Operation{
		{
			Operation: "remove",
			Path:      "/spec/claimRef",
		},
	}
	payloadBytes, _ := json.Marshal(payload)
	return cl.Patch(ctx, pv, client.RawPatch(types.JSONPatchType, payloadBytes))
}

func (r *Reconciler) getValidationJob(ctx context.Context, credentialHash string) (*batchv1.Job, error) {
	validationJob := &batchv1.Job{}

	validationJobKey := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      helpers.GetTargetResourceName(internal.TargetValidationPrefix, credentialHash),
	}

	if err := r.Client.Get(ctx, validationJobKey, validationJob); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, nil
		}
		return nil, err
	}

	return validationJob, nil
}

func (r *Reconciler) reconcileValidationJob(ctx context.Context, newTarget, originalTarget *v1.Target, newCredHash string,
	validationJob *batchv1.Job, validationStatus v1.ValidationState) (bool, error) {
	log := r.Log.WithField("function", "reconcileValidationJob")
	propagationPolicy := metav1.DeletePropagationForeground

	if validationJob == nil || validationStatus == v1.InvalidTargetCredential {
		// Only add InProgress condition if it doesn't already exist
		if !newTarget.HasValidationCondition(v1.InProgress) {
			if err := r.updateTargetCondition(ctx, newTarget, originalTarget, v1.ValidationOperation, v1.InProgress, ""); err != nil {
				return false, err
			}
		}

		// To trigger a new job, delete the old job which is in a failed state
		if validationJob != nil {
			if dErr := r.Client.Delete(ctx, validationJob, &client.DeleteOptions{PropagationPolicy: &propagationPolicy}); dErr != nil {
				if !apierrors.IsNotFound(dErr) {
					return false, dErr
				}
			}
		}

		newValidationJob, err := helpers.GetTargetValidatorJob(ctx, r.Client, newTarget, newCredHash)
		if err != nil {
			return false, fmt.Errorf("error occurred while getting target validator job: %w", err)
		}

		// Remove credential hash from validation config map
		if rErr := r.removeCredHashFromValidationConfig(ctx, newCredHash); rErr != nil {
			log.Errorf("error while removing the credential hash %s from target validation config map: %v",
				newCredHash, rErr)
		}

		log.Infof("Creating a new validation job: %s", newValidationJob.Name)
		if crErr := r.Client.Create(ctx, newValidationJob); crErr != nil {
			r.Recorder.Eventf(newTarget, corev1.EventTypeWarning, "JobCreateFailed",
				"Target validation job creation Failed for target: %s", newTarget.Name)
			return false, fmt.Errorf("error while creating the validation job: %w", crErr)
		}

		r.Recorder.Eventf(newTarget, corev1.EventTypeNormal, "JobCreateSuccess",
			"Target validation job %s created for target: %s", newValidationJob.Name, newTarget.Name)

		return false, nil
	}

	// Use pod-aware status check to detect errors like CrashLoopBackOff, ImagePullBackOff, etc.
	jobStatus := helpers.GetJobStatusWithPodCheck(ctx, r.Client, validationJob)
	log.Debugf("Found target validation job with name: %s and status: %v", validationJob.Name, jobStatus)

	status, operationStatus, eventReason := getTargetEquivalentJobStatus(jobStatus)
	if uErr := r.updateValidationConfigMap(ctx, newCredHash, operationStatus); uErr != nil {
		return false, fmt.Errorf("error while updating validation config map: %w", uErr)
	}

	if newTarget.Status.Status != v1.Available {
		specificReason := ""
		if helpers.IsJobPendingDeadlineExceeded(validationJob) {
			status = v1.Unavailable
			operationStatus = v1.Failed
			eventReason = "ValidationFailed"
			// Do NOT delete timeout job - keep for debugging (TVK pattern)
			// deleteJob = true  // Removed: failed/timeout jobs kept for debugging
			specificReason = "Job pending deadline exceeded"
		}

		// Only add condition if it doesn't already exist to avoid duplicates
		if !newTarget.HasValidationCondition(operationStatus) {
			if uErr := r.updateTargetCondition(ctx, newTarget, originalTarget,
				v1.ValidationOperation, operationStatus, specificReason); uErr != nil {
				return false, uErr
			}
		}
	}

	r.Recorder.Eventf(newTarget, corev1.EventTypeNormal, eventReason,
		"Target %s validation state: %s", newTarget.Name, operationStatus)
	if err := r.updateTargetStatus(ctx, newTarget, originalTarget, status); err != nil {
		return false, err
	}

	// Delete validation job ONLY when target becomes Available (validation succeeded)
	// Following TVK pattern: failed/timeout jobs are kept for debugging
	if status == v1.Available {
		if dErr := r.Client.Delete(ctx, validationJob, &client.DeleteOptions{PropagationPolicy: &propagationPolicy}); dErr != nil {
			if !apierrors.IsNotFound(dErr) {
				return false, dErr
			}
			// Job already deleted, ignore the error
			log.Debugf("Validation job %s already deleted", validationJob.Name)
		}
		log.Infof("Deleted successful validation job: %s", validationJob.Name)
	} else if operationStatus == v1.Failed {
		// Keep failed validation job for debugging
		log.Infof("Keeping failed validation job for debugging: %s", validationJob.Name)
	}

	return true, nil
}

func getTargetEquivalentJobStatus(jobStatus v1.Status) (v1.Status, v1.Status, string) {
	switch jobStatus {
	case v1.Completed:
		return v1.Available, v1.Completed, "ValidationSucceeded"
	case v1.Failed:
		return v1.Unavailable, v1.Failed, "ValidationFailed"
	default:
		return v1.InProgress, v1.InProgress, "ValidationInProgress"
	}
}

func (r *Reconciler) updateTargetCredentialsChangeHash(ctx context.Context, targetInstance, originalTarget *v1.Target,
	specCredentialsHash string) error {
	annotations := map[string]string{internal.TargetCredentialsHashAnnotationKey: specCredentialsHash}
	targetInstance.Annotations = internal.MergeMaps(targetInstance.Annotations, annotations)
	if err := r.Client.Patch(ctx, targetInstance, client.MergeFrom(originalTarget)); err != nil {
		return err
	}
	targetInstance.DeepCopyInto(originalTarget)
	return nil
}

func (r *Reconciler) updateTargetStatus(ctx context.Context, targetInstance, originalTarget *v1.Target, status v1.Status) error {
	if status == "" {
		return nil
	}
	targetInstance.Status.Status = status

	r.Recorder.Eventf(targetInstance, corev1.EventTypeNormal, "StatusUpdate",
		"Target status updated to: %s", status)

	if err := r.Client.Status().Patch(ctx, targetInstance, client.MergeFrom(originalTarget)); err != nil {
		return err
	}
	targetInstance.DeepCopyInto(originalTarget)
	return nil
}

func (r *Reconciler) updateTargetCondition(ctx context.Context, targetInstance, originalTarget *v1.Target,
	phase v1.OperationType, status v1.Status, reason string) error {

	condition := v1.TargetCondition{
		Phase:     phase,
		Status:    status,
		Timestamp: &metav1.Time{Time: metav1.Now().Time},
		Reason:    reason,
	}

	targetInstance.Status.Condition = append(targetInstance.Status.Condition, condition)

	if err := r.Client.Status().Patch(ctx, targetInstance, client.MergeFrom(originalTarget)); err != nil {
		return err
	}
	targetInstance.DeepCopyInto(originalTarget)
	return nil
}

func (r *Reconciler) reconcileValidationConfigMap(ctx context.Context) (*corev1.ConfigMap, error) {
	validationConfigMap := &corev1.ConfigMap{}
	validationConfigMapNsNm := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      internal.TargetValidationConfig,
	}
	if gErr := r.Get(ctx, validationConfigMapNsNm, validationConfigMap); gErr != nil {
		if apierrors.IsNotFound(gErr) {
			newConfigMap := newTargetValidatorConfigMap()
			if cErr := r.Client.Create(ctx, newConfigMap); cErr != nil {
				return nil, cErr
			}
			return newConfigMap, nil
		}
		return nil, gErr
	}
	return validationConfigMap, nil
}

func newTargetValidatorConfigMap() *corev1.ConfigMap {
	return &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      internal.TargetValidationConfig,
			Namespace: internal.GetInstallNamespace(),
			Labels:    internal.GetRecommendedLabels("validation-config", internal.ManagedBy),
		},
		Data: make(map[string]string),
	}
}

func (r *Reconciler) processValidationConfigMap(ctx context.Context, targetInstance, originalTarget *v1.Target,
	credentialHash string, validationConfigMap *corev1.ConfigMap) (runValidation bool, status v1.ValidationState, err error) {

	value, present := validationConfigMap.Data[credentialHash]
	validationState := v1.ValidationState(value)
	if !present || validationState != v1.ValidTargetCredential {
		return true, validationState, nil
	}

	// The current target is in available state, skip running the validation
	if targetInstance.Status.Status == v1.Available {
		return false, v1.ValidTargetCredential, nil
	}

	// If validation has already completed, don't add duplicate conditions
	// This handles controller restart scenarios where validation was already done
	if targetInstance.IsValidationCompleted() {
		// Just update status to Available if needed
		targetInstance.Status.Status = v1.Available
		if uErr := r.updateTargetStatus(ctx, targetInstance, originalTarget, targetInstance.Status.Status); uErr != nil {
			return false, validationState, uErr
		}
		return false, validationState, nil
	}

	// For targets with valid credentials, update status to available
	// Add validation conditions only if they don't already exist
	if !targetInstance.HasValidationCondition(v1.InProgress) {
		if uErr := r.updateTargetCondition(ctx, targetInstance, originalTarget, v1.ValidationOperation,
			v1.InProgress, ""); uErr != nil {
			return false, validationState, uErr
		}
	}
	if !targetInstance.HasValidationCondition(v1.Completed) {
		if uErr := r.updateTargetCondition(ctx, targetInstance, originalTarget, v1.ValidationOperation,
			v1.Completed, ""); uErr != nil {
			return false, validationState, uErr
		}
	}
	targetInstance.Status.Status = v1.Available
	if uErr := r.updateTargetStatus(ctx, targetInstance, originalTarget, targetInstance.Status.Status); uErr != nil {
		return false, validationState, uErr
	}
	return false, validationState, nil
}

func (r *Reconciler) updateValidationConfigMap(ctx context.Context, credHash string, status v1.Status) error {
	configMap := &corev1.ConfigMap{}
	nsNm := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      internal.TargetValidationConfig,
	}

	if err := r.Client.Get(ctx, nsNm, configMap); err != nil {
		return err
	}

	if configMap.Data == nil {
		configMap.Data = make(map[string]string)
	}

	var validationState string
	if status == v1.Completed {
		validationState = string(v1.ValidTargetCredential)
	} else if status == v1.Failed {
		validationState = string(v1.InvalidTargetCredential)
	} else {
		return nil // Don't update for in-progress state
	}

	configMap.Data[credHash] = validationState
	return r.Client.Update(ctx, configMap)
}

func (r *Reconciler) removeCredHashFromValidationConfig(ctx context.Context, credHash string) error {
	configMap := &corev1.ConfigMap{}
	nsNm := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      internal.TargetValidationConfig,
	}

	if err := r.Client.Get(ctx, nsNm, configMap); err != nil {
		return err
	}

	if configMap.Data == nil {
		return nil
	}

	delete(configMap.Data, credHash)
	return r.Client.Update(ctx, configMap)
}

// syncValidationConfigMap removes stale credential hashes from validation ConfigMap.
// It scans all existing targets and removes hashes that don't correspond to any target.
// This is called during target deletion cleanup, following k8s-triliovault janitor approach.
func (r *Reconciler) syncValidationConfigMap(ctx context.Context) error {
	log := r.Log.WithField("function", "syncValidationConfigMap")

	// Get the validation configmap
	configMap := &corev1.ConfigMap{}
	nsNm := types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      internal.TargetValidationConfig,
	}

	if err := r.Client.Get(ctx, nsNm, configMap); err != nil {
		if apierrors.IsNotFound(err) {
			// ConfigMap doesn't exist yet, nothing to clean up
			log.Debug("Validation ConfigMap does not exist, skipping sync")
			return nil
		}
		return fmt.Errorf("error getting validation configmap: %w", err)
	}

	if len(configMap.Data) == 0 {
		log.Debug("Validation ConfigMap is empty, nothing to sync")
		return nil
	}

	// Get all existing targets
	targets := &v1.TargetList{}
	if err := r.Client.List(ctx, targets); err != nil {
		return fmt.Errorf("error listing targets: %w", err)
	}

	// Build a map of active credential hashes from existing targets
	// Exclude targets that are being deleted (have deletionTimestamp set)
	activeHashes := make(map[string]struct{})
	for i := range targets.Items {
		target := &targets.Items[i]
		// If target is getting deleted, don't include its credential hash
		if !target.ObjectMeta.DeletionTimestamp.IsZero() {
			continue
		}
		if credHash, exists := target.Annotations[internal.TargetCredentialsHashAnnotationKey]; exists {
			activeHashes[credHash] = struct{}{}
		}
	}

	// Build new ConfigMap data with only active hashes
	newData := make(map[string]string)
	staleCount := 0
	for credHash, validationStatus := range configMap.Data {
		if _, exists := activeHashes[credHash]; exists {
			// Hash is still in use by an existing target, retain it
			newData[credHash] = validationStatus
		} else {
			// Hash is stale, will be removed
			staleCount++
			log.Debugf("Removing stale credential hash: %s", credHash)
		}
	}

	if staleCount == 0 {
		log.Debug("No stale credential hashes found in validation ConfigMap")
		return nil
	}

	// Update the ConfigMap with cleaned data
	configMap.Data = newData
	if err := r.Client.Update(ctx, configMap); err != nil {
		return fmt.Errorf("error updating validation configmap after sync: %w", err)
	}

	log.Infof("Successfully removed %d stale credential hashes from validation ConfigMap", staleCount)
	return nil
}

func (r *Reconciler) reconcilePollerCronJob(ctx context.Context, target *v1.Target, credentialHash string) error {
	log := r.Log.WithField("function", "reconcilePollerCronJob")

	// Get desired CronJob spec
	cronJobName := helpers.GetTargetResourceName(internal.TargetPollerPrefix, credentialHash)
	desiredCronJob, err := helpers.GetTargetPollerCronJob(ctx, r.Client, target, credentialHash)
	if err != nil {
		return fmt.Errorf("error creating poller cronjob spec: %w", err)
	}

	// Check if CronJob already exists
	existingCronJob := &batchv1.CronJob{}
	err = r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      cronJobName,
	}, existingCronJob)

	if err != nil {
		if !apierrors.IsNotFound(err) {
			return fmt.Errorf("error checking for existing cronjob: %w", err)
		}

		// CronJob doesn't exist, create it
		log.Infof("Creating poller cronjob: %s for credential hash: %s", desiredCronJob.Name, credentialHash)
		if err := r.Client.Create(ctx, desiredCronJob); err != nil {
			r.Recorder.Eventf(target, corev1.EventTypeWarning, "CronJobCreateFailed",
				"Poller cronjob creation failed for target: %s", target.Name)
			return fmt.Errorf("error creating poller cronjob: %w", err)
		}

		r.Recorder.Eventf(target, corev1.EventTypeNormal, "CronJobCreateSuccess",
			"Poller cronjob %s created for credential hash: %s", desiredCronJob.Name, credentialHash)

		log.Infof("Successfully created poller cronjob: %s", desiredCronJob.Name)
		return nil
	}

	// CronJob exists, check if update is needed
	needsUpdate := false
	updateReason := ""

	// Compare schedule
	if existingCronJob.Spec.Schedule != desiredCronJob.Spec.Schedule {
		needsUpdate = true
		updateReason = fmt.Sprintf("schedule changed from %s to %s", existingCronJob.Spec.Schedule, desiredCronJob.Spec.Schedule)
	}

	// Compare image
	if len(existingCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers) > 0 &&
		len(desiredCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers) > 0 {
		existingImage := existingCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers[0].Image
		desiredImage := desiredCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers[0].Image
		if existingImage != desiredImage {
			needsUpdate = true
			updateReason = fmt.Sprintf("image changed from %s to %s", existingImage, desiredImage)
		}
	}

	// Compare command and args
	if len(existingCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers) > 0 &&
		len(desiredCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers) > 0 {
		existingArgs := existingCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers[0].Args
		desiredArgs := desiredCronJob.Spec.JobTemplate.Spec.Template.Spec.Containers[0].Args
		if len(existingArgs) != len(desiredArgs) {
			needsUpdate = true
			if updateReason != "" {
				updateReason += "; "
			}
			updateReason += "command args changed"
		} else {
			for i := range existingArgs {
				if existingArgs[i] != desiredArgs[i] {
					needsUpdate = true
					if updateReason != "" {
						updateReason += "; "
					}
					updateReason += "command args changed"
					break
				}
			}
		}
	}

	if !needsUpdate {
		log.Debugf("Poller cronjob %s is up to date", cronJobName)
		return nil
	}

	// Update CronJob
	log.Infof("Updating poller cronjob %s: %s", cronJobName, updateReason)

	// Preserve metadata (resourceVersion, etc.)
	desiredCronJob.ResourceVersion = existingCronJob.ResourceVersion
	desiredCronJob.UID = existingCronJob.UID
	desiredCronJob.Generation = existingCronJob.Generation

	if err := r.Client.Update(ctx, desiredCronJob); err != nil {
		r.Recorder.Eventf(target, corev1.EventTypeWarning, "CronJobUpdateFailed",
			"Poller cronjob update failed for target: %s", target.Name)
		return fmt.Errorf("error updating poller cronjob: %w", err)
	}

	r.Recorder.Eventf(target, corev1.EventTypeNormal, "CronJobUpdateSuccess",
		"Poller cronjob %s updated: %s", cronJobName, updateReason)

	log.Infof("Successfully updated poller cronjob: %s", cronJobName)
	return nil
}
