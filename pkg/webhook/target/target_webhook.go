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

// Handle implements the validation webhook handler
func (v *TargetValidator) Handle(ctx context.Context, req admission.Request) admission.Response {
	target := &v1.Target{}

	// Decode the request
	if err := v.decoder.Decode(req, target); err != nil {
		return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding request: %w", err))
	}

	// Handle different operations
	switch req.Operation {
	case admissionv1.Create:
		if err := ValidateTargetCreate(ctx, v.Client, target); err != nil {
			return admission.Denied(err.Error())
		}

	case admissionv1.Update:
		// Get the old target from the request
		oldTarget := &v1.Target{}
		if err := v.decoder.DecodeRaw(req.OldObject, oldTarget); err != nil {
			return admission.Errored(http.StatusBadRequest, fmt.Errorf("error decoding old object: %w", err))
		}

		if err := ValidateTargetUpdate(ctx, v.Client, oldTarget, target); err != nil {
			return admission.Denied(err.Error())
		}

	default:
		// Allow Delete and other operations without validation
		return admission.Allowed("")
	}

	return admission.Allowed("")
}

// InjectDecoder injects the decoder into the validator
func (v *TargetValidator) InjectDecoder(d *admission.Decoder) error {
	v.decoder = d
	return nil
}

// NewTargetValidator creates a new TargetValidator
func NewTargetValidator(client client.Client) *TargetValidator {
	return &TargetValidator{
		Client: client,
	}
}
