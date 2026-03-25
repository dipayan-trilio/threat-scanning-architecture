package target

import (
	"context"
	"fmt"
	"net/http"

	admissionv1 "k8s.io/api/admission/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
)

// TargetValidator handles validation for Target resources
type TargetValidator struct {
	Client  client.Client
	decoder *admission.Decoder
}

// TargetMutator handles mutation for Target resources
type TargetMutator struct {
	Client  client.Client
	decoder *admission.Decoder
}

// Handle implements the validation webhook handler
func (v *TargetValidator) Handle(ctx context.Context, req admission.Request) admission.Response {
	target := &v1.Target{}

	// Handle different operations
	switch req.Operation {
	case admissionv1.Create:
		// For create, decode from req.Object
		if err := v.decoder.Decode(req, target); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding request: %w", err))
		}

		if err := ValidateTargetCreate(ctx, v.Client, target); err != nil {
			return admission.Denied(err.Error())
		}

	case admissionv1.Update:
		// For update, decode new object from req.Object
		if err := v.decoder.Decode(req, target); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding request: %w", err))
		}

		// Get the old target from req.OldObject
		oldTarget := &v1.Target{}
		if err := v.decoder.DecodeRaw(req.OldObject, oldTarget); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding old object: %w", err))
		}

		if err := ValidateTargetUpdate(ctx, v.Client, oldTarget, target); err != nil {
			return admission.Denied(err.Error())
		}

	case admissionv1.Delete:
		// For delete operations, object is in req.OldObject (req.Object is empty)
		if err := v.decoder.DecodeRaw(req.OldObject, target); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding old object: %w", err))
		}

		if err := ValidateTargetDelete(ctx, v.Client, target); err != nil {
			return admission.Denied(err.Error())
		}

	default:
		// Allow other operations
		return admission.Allowed("")
	}

	return admission.Allowed("")
}

// Handle implements the mutation webhook handler
func (m *TargetMutator) Handle(ctx context.Context, req admission.Request) admission.Response {
	target := &v1.Target{}

	// Decode the request
	if err := m.decoder.Decode(req, target); err != nil {
		return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding request: %w", err))
	}

	// Only mutate on Create operations
	if req.Operation != admissionv1.Create {
		return admission.Allowed("")
	}

	// Apply mutations
	patchBytes, err := MutateTarget(target)
	if err != nil {
		return admission.Errored(http.StatusInternalServerError, fmt.Errorf("error mutating target: %w", err))
	}

	// If no patches, just allow the request
	if patchBytes == nil || len(patchBytes) == 0 {
		return admission.Allowed("")
	}

	// Return patched response
	return admission.PatchResponseFromRaw(req.Object.Raw, patchBytes)
}

// InjectDecoder injects the decoder into the validator
func (v *TargetValidator) InjectDecoder(d *admission.Decoder) error {
	v.decoder = d
	return nil
}

// InjectDecoder injects the decoder into the mutator
func (m *TargetMutator) InjectDecoder(d *admission.Decoder) error {
	m.decoder = d
	return nil
}

// NewTargetValidator creates a new TargetValidator
func NewTargetValidator(client client.Client) *TargetValidator {
	return &TargetValidator{
		Client: client,
	}
}

// NewTargetMutator creates a new TargetMutator
func NewTargetMutator(client client.Client) *TargetMutator {
	return &TargetMutator{
		Client: client,
	}
}
