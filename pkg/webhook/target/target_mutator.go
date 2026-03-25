package target

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

// MutateTarget applies default values and mutations to a Target
func MutateTarget(target *v1.Target) ([]byte, error) {
	var patches []PatchOperation

	// Set default vendor to "Other" for non-cloud ObjectStore if not specified
	if target.IsObjectStoreTarget() && target.Spec.Vendor == "" {
		patches = append(patches, PatchOperation{
			Op:    "add",
			Path:  "/spec/vendor",
			Value: v1.Other,
		})
	}

	// Set default skipCertVerification to false if not specified
	if target.IsObjectStoreTarget() {
		// Only add default if the field is not explicitly set
		// This checks if skipCertVerification is the zero value (false)
		// We need to be careful here as false is the zero value
		// The validation will handle this, but we can add a default here
		if !target.HasSkipCertVerification() && !target.HasSSLCertConfig() {
			patches = append(patches, PatchOperation{
				Op:    "add",
				Path:  "/spec/objectStoreCredentials/skipCertVerification",
				Value: false,
			})
		}
	}

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
