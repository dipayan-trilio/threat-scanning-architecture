package scaninstance

import (
	"context"
	"fmt"
	"reflect"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
)

// ValidateScanInstanceCreate validates a ScanInstance on creation
func ValidateScanInstanceCreate(ctx context.Context, cl client.Client, si *v1.ScanInstance) error {
	// 1. Validate that backupRef.path is not empty
	if si.Spec.BackupRef.Path == "" {
		return fmt.Errorf("[spec.backupRef.path] backup path cannot be empty")
	}

	// 2. Validate that referenced target exists
	target := &v1.Target{}
	targetKey := types.NamespacedName{
		Name: si.Spec.BackupTarget.Name,
	}
	if err := cl.Get(ctx, targetKey, target); err != nil {
		if apierrors.IsNotFound(err) {
			return fmt.Errorf("[spec.backupTarget.name] target '%s' not found", si.Spec.BackupTarget.Name)
		}
		return fmt.Errorf("[spec.backupTarget.name] error checking target existence: %w", err)
	}

	// 3. Validate that target status is Available
	if target.Status.Status != v1.Available {
		return fmt.Errorf("[spec.backupTarget.name] target '%s' is not available (status: %s)",
			target.Name, target.Status.Status)
	}

	// 4. Validate that target has completed validation
	if !target.IsValidationCompleted() {
		return fmt.Errorf("[spec.backupTarget.name] target '%s' has not completed validation",
			target.Name)
	}

	// Note: We allow duplicate scan instances for the same backup path and target (rescans)

	return nil
}

// ValidateScanInstanceUpdate validates a ScanInstance on update
func ValidateScanInstanceUpdate(ctx context.Context, cl client.Client, oldSI, newSI *v1.ScanInstance) error {
	// 1. Validate that spec is immutable after creation
	if !reflect.DeepEqual(oldSI.Spec, newSI.Spec) {
		return fmt.Errorf("spec is immutable after creation, cannot update scan instance spec")
	}

	// 2. Validate logical phase transitions
	if err := validatePhaseTransition(oldSI, newSI); err != nil {
		return err
	}

	return nil
}

// validatePhaseTransition validates that phase transitions are logical
func validatePhaseTransition(oldSI, newSI *v1.ScanInstance) error {
	// If status hasn't changed, allow the update
	if oldSI.Status.Status == newSI.Status.Status {
		return nil
	}

	// Define valid transitions
	validTransitions := map[v1.ScanInstanceStatus][]v1.ScanInstanceStatus{
		v1.ScanQueued: {
			v1.ScanInProgress,
			v1.ScanFailed,
		},
		v1.ScanInProgress: {
			v1.ScanCompleted,
			v1.ScanFailed,
		},
		v1.ScanCompleted: {
			// Completed is terminal, but we can allow rescan by allowing transition to Queued
			// This would be done by creating a new ScanInstance, not updating
		},
		v1.ScanFailed: {
			// Failed is terminal
			// Retry would be done by creating a new ScanInstance
		},
	}

	// Check if transition is valid
	oldStatus := oldSI.Status.Status
	newStatus := newSI.Status.Status

	// Empty old status means this is the first status update, allow any status
	if oldStatus == "" {
		return nil
	}

	// Check if new status is in the list of valid transitions
	allowedTransitions, exists := validTransitions[oldStatus]
	if !exists {
		// No valid transitions defined for this status
		return fmt.Errorf("invalid status transition from '%s' to '%s': no valid transitions from '%s'",
			oldStatus, newStatus, oldStatus)
	}

	// Check if the new status is in the allowed list
	for _, allowed := range allowedTransitions {
		if newStatus == allowed {
			return nil
		}
	}

	// If we reach here, the transition is not valid
	return fmt.Errorf("invalid status transition from '%s' to '%s': allowed transitions are %v",
		oldStatus, newStatus, allowedTransitions)
}
