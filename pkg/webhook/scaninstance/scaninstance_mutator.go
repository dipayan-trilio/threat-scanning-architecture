package scaninstance

import (
	"encoding/json"
	"fmt"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
)

// PatchOperation represents a JSON patch operation
type PatchOperation struct {
	Op    string      `json:"op"`
	Path  string      `json:"path"`
	Value interface{} `json:"value,omitempty"`
}

// MutateScanInstance applies default values and mutations to a ScanInstance
func MutateScanInstance(si *v1.ScanInstance) ([]byte, error) {
	var patches []PatchOperation

	// Auto-populate backupTarget.apiVersion if not provided
	if si.Spec.BackupTarget.APIVersion == "" {
		patches = append(patches, PatchOperation{
			Op:    "add",
			Path:  "/spec/backupTarget/apiVersion",
			Value: "threatscanning.trilio.io/v1",
		})
	}

	// Auto-populate backupTarget.kind if not provided
	if si.Spec.BackupTarget.Kind == "" {
		patches = append(patches, PatchOperation{
			Op:    "add",
			Path:  "/spec/backupTarget/kind",
			Value: "Target",
		})
	}

	// Note: We do NOT initialize status here
	// Status initialization is handled by the controller for proper state management
	// The controller will set the initial Queued status and conditions

	// Note: We do NOT manage labels here
	// Label management is done by the prescan job after mounting the target
	// This allows proper backup detection and metadata extraction

	// Note: We do NOT populate resourceVersion and UID here
	// These fields are optional and can be set by the user if needed

	// Return nil if no mutations needed (webhook handler will return admission.Allowed)
	if len(patches) == 0 {
		return nil, nil
	}

	patchBytes, err := json.Marshal(patches)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal patches: %w", err)
	}

	return patchBytes, nil
}
