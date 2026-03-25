package scaninstance

import (
	"context"
	"fmt"
	"net/http"

	admissionv1 "k8s.io/api/admission/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
)

// ScanInstanceValidator handles validation for ScanInstance resources
type ScanInstanceValidator struct {
	Client  client.Client
	decoder *admission.Decoder
}

// ScanInstanceMutator handles mutation for ScanInstance resources
type ScanInstanceMutator struct {
	Client  client.Client
	decoder *admission.Decoder
}

// Handle implements the validation webhook handler
func (v *ScanInstanceValidator) Handle(ctx context.Context, req admission.Request) admission.Response {
	scanInstance := &v1.ScanInstance{}

	// Handle different operations
	switch req.Operation {
	case admissionv1.Create:
		// For create, decode from req.Object
		if err := v.decoder.Decode(req, scanInstance); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding request: %w", err))
		}

		if err := ValidateScanInstanceCreate(ctx, v.Client, scanInstance); err != nil {
			return admission.Denied(err.Error())
		}

	case admissionv1.Update:
		// For update, decode new object from req.Object
		if err := v.decoder.Decode(req, scanInstance); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding request: %w", err))
		}

		// Get the old scan instance from req.OldObject
		oldScanInstance := &v1.ScanInstance{}
		if err := v.decoder.DecodeRaw(req.OldObject, oldScanInstance); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding old object: %w", err))
		}

		if err := ValidateScanInstanceUpdate(ctx, v.Client, oldScanInstance, scanInstance); err != nil {
			return admission.Denied(err.Error())
		}

	case admissionv1.Delete:
		// For delete operations, object is in req.OldObject (req.Object is empty)
		if err := v.decoder.DecodeRaw(req.OldObject, scanInstance); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding old object: %w", err))
		}

		// Log warning but allow deletion
		if scanInstance.Status.Status == v1.ScanInProgress {
			// Return warning but still allow the deletion
			return admission.Allowed(fmt.Sprintf("Warning: Deleting scan instance '%s' which is in progress (status: %s)",
				scanInstance.Name, scanInstance.Status.Status))
		}

	default:
		// Allow other operations
		return admission.Allowed("")
	}

	return admission.Allowed("")
}

// Handle implements the mutation webhook handler
func (m *ScanInstanceMutator) Handle(ctx context.Context, req admission.Request) admission.Response {
	scanInstance := &v1.ScanInstance{}

	// Decode the request
	if err := m.decoder.Decode(req, scanInstance); err != nil {
		return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding request: %w", err))
	}

	// Only mutate on Create operations
	if req.Operation != admissionv1.Create {
		return admission.Allowed("")
	}

	// Apply mutations
	patchBytes, err := MutateScanInstance(scanInstance)
	if err != nil {
		return admission.Errored(http.StatusInternalServerError, fmt.Errorf("error mutating scan instance: %w", err))
	}

	// If no patches, just allow the request
	if patchBytes == nil || len(patchBytes) == 0 {
		return admission.Allowed("")
	}

	// Return patched response
	return admission.PatchResponseFromRaw(req.Object.Raw, patchBytes)
}

// InjectDecoder injects the decoder into the validator
func (v *ScanInstanceValidator) InjectDecoder(d *admission.Decoder) error {
	v.decoder = d
	return nil
}

// InjectDecoder injects the decoder into the mutator
func (m *ScanInstanceMutator) InjectDecoder(d *admission.Decoder) error {
	m.decoder = d
	return nil
}

// NewScanInstanceValidator creates a new ScanInstanceValidator
func NewScanInstanceValidator(client client.Client) *ScanInstanceValidator {
	return &ScanInstanceValidator{
		Client: client,
	}
}

// NewScanInstanceMutator creates a new ScanInstanceMutator
func NewScanInstanceMutator(client client.Client) *ScanInstanceMutator {
	return &ScanInstanceMutator{
		Client: client,
	}
}
