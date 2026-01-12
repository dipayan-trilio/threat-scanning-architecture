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

	// TODO: Delete scan job when implemented
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
