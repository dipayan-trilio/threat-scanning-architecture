package target

import (
	"context"
	"fmt"
	"net/url"
	"reflect"
	"strings"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
)

// ValidateTargetCreate validates target creation
func ValidateTargetCreate(ctx context.Context, cl client.Client, target *v1.Target) error {
	// Run common validations for Create
	if err := validateTargetSpec(target); err != nil {
		return err
	}

	// Validate referenced resources exist (secrets, configmaps)
	if err := validateReferencedResources(ctx, cl, target); err != nil {
		return err
	}

	// Check for reporting target uniqueness
	if target.IsReportingTarget() {
		if err := validateReportingTargetUniqueness(ctx, cl, target, true); err != nil {
			return err
		}
	}

	return nil
}

// ValidateTargetUpdate validates target updates
func ValidateTargetUpdate(ctx context.Context, cl client.Client, oldTarget, newTarget *v1.Target) error {
	// Run common validations for Update
	if err := validateTargetSpec(newTarget); err != nil {
		return err
	}

	// Validate referenced resources exist (secrets, configmaps)
	if err := validateReferencedResources(ctx, cl, newTarget); err != nil {
		return err
	}

	// Check if spec is being updated
	if !reflect.DeepEqual(oldTarget.Spec, newTarget.Spec) {
		// Prevent spec update if target is referenced by active scan instances
		if err := validateNoActiveScanInstances(ctx, cl, newTarget); err != nil {
			return fmt.Errorf("cannot update target spec: %w", err)
		}
	}

	// Prevent conversion from backup to reporting
	if !oldTarget.IsReportingTarget() && newTarget.IsReportingTarget() {
		return fmt.Errorf("[spec.targetType] conversion from backup target to reporting target is not allowed")
	}

	// Check for reporting target uniqueness if converting to reporting
	if newTarget.IsReportingTarget() && !oldTarget.IsReportingTarget() {
		if err := validateReportingTargetUniqueness(ctx, cl, newTarget, false); err != nil {
			return err
		}
	}

	return nil
}

// validateTargetSpec performs common validation for target spec
func validateTargetSpec(target *v1.Target) error {
	// Target Type validation
	switch {
	case target.Spec.Type == v1.NFS:
		return validateNFSTarget(target)
	case target.Spec.Type == v1.ObjectStore:
		return validateObjectStoreTarget(target)
	default:
		return fmt.Errorf("[spec.type] unsupported target type: %s", target.Spec.Type)
	}
}

// validateNFSTarget validates NFS target specifications
func validateNFSTarget(target *v1.Target) error {
	// NFS credentials must be present
	if reflect.DeepEqual(target.Spec.NFSCredentials, v1.NFSCredentials{}) {
		return fmt.Errorf("[spec.nfsCredentials] target credentials for NFS missing")
	}

	// Object store credentials must NOT be present
	if !reflect.DeepEqual(target.Spec.ObjectStoreCredentials, v1.ObjectStoreCredentials{}) {
		return fmt.Errorf("[spec.objectStoreCredentials] object store credentials not allowed for NFS type target")
	}

	// nfsExport must be specified
	if target.Spec.NFSCredentials.NfsExport == "" {
		return fmt.Errorf("[spec.nfsCredentials.nfsExport] nfsExport for NFS target missing")
	}

	// ThresholdCapacity validation for NFS
	if target.Spec.ThresholdCapacity != nil {
		if err := ValidateResourceQuantity(target.Spec.ThresholdCapacity); err != nil {
			return fmt.Errorf("[spec.thresholdCapacity] %w", err)
		}
	}

	return nil
}

// validateObjectStoreTarget validates ObjectStore target specifications
func validateObjectStoreTarget(target *v1.Target) error {
	// Object store credentials must be present
	if reflect.DeepEqual(target.Spec.ObjectStoreCredentials, v1.ObjectStoreCredentials{}) {
		return fmt.Errorf("[spec.objectStoreCredentials] target credentials for ObjectStore missing")
	}

	// NFS credentials must NOT be present
	if !reflect.DeepEqual(target.Spec.NFSCredentials, v1.NFSCredentials{}) {
		return fmt.Errorf("[spec.nfsCredentials] nfs credentials not allowed for ObjectStore type target")
	}

	// CredentialSecret is required
	if target.Spec.ObjectStoreCredentials.CredentialSecret == nil {
		return fmt.Errorf("[spec.objectStoreCredentials.credentialSecret] missing required field: credentialSecret for target not specified")
	}

	// CRITICAL: Validate that credential secret has namespace specified
	// Since Target is cluster-scoped, we require explicit namespace
	if target.Spec.ObjectStoreCredentials.CredentialSecret.Namespace == "" {
		return fmt.Errorf("[spec.objectStoreCredentials.credentialSecret.namespace] namespace must be specified for credential secret (target is cluster-scoped)")
	}

	// BucketName is required
	if target.Spec.ObjectStoreCredentials.BucketName == "" {
		return fmt.Errorf("[spec.objectStoreCredentials.bucketName] bucketName for object store missing")
	}

	// SSL cert config validation
	if target.Spec.ObjectStoreCredentials.SSLCertConfig != nil {
		if strings.TrimSpace(target.Spec.ObjectStoreCredentials.SSLCertConfig.CertKey) == "" {
			return fmt.Errorf("[spec.objectStoreCredentials.sslCertConfig.certKey] certKey for object store sslCertConfig is missing")
		}
		if target.Spec.ObjectStoreCredentials.SSLCertConfig.CertConfigMap == nil {
			return fmt.Errorf("[spec.objectStoreCredentials.sslCertConfig.certConfigMap] certConfigMap reference is missing")
		}
		// Validate namespace is specified for SSL cert configmap
		if target.Spec.ObjectStoreCredentials.SSLCertConfig.CertConfigMap.Namespace == "" {
			return fmt.Errorf("[spec.objectStoreCredentials.sslCertConfig.certConfigMap.namespace] namespace must be specified for SSL cert configmap")
		}
	}

	// Vendor-specific validations
	switch target.Spec.Vendor {
	case v1.AWS, v1.Azure:
		// AWS and Azure use default endpoints, no URL validation needed
		// Future: Add specific AWS/Azure credential validations if needed
	default:
		// For other vendors (MinIO, S3-compatible), URL is required
		objectStoreURL := target.Spec.ObjectStoreCredentials.URL
		if objectStoreURL == "" {
			return fmt.Errorf("[spec.objectStoreCredentials.url] URL for object store missing")
		}

		// Validate URL format
		objectStoreURLParsed, err := url.ParseRequestURI(objectStoreURL)
		if err != nil {
			return fmt.Errorf("[spec.objectStoreCredentials.url] invalid value %s: %s", objectStoreURL, err.Error())
		}

		// Validate URL has scheme
		if objectStoreURLParsed.Scheme == "" {
			return fmt.Errorf("[spec.objectStoreCredentials.url] http scheme is not provided")
		}

		// Validate URL has host
		if objectStoreURLParsed.Host == "" {
			return fmt.Errorf("[spec.objectStoreCredentials.url] host is not provided")
		}
	}

	// Reporting target specific validations
	if target.IsReportingTarget() {
		return validateReportingTarget(target)
	}

	// Validate targetType is specified for non-reporting targets
	if !target.IsReportingTarget() && target.Spec.TargetType == "" {
		return fmt.Errorf("[spec.targetType] targetType (TVK/TVO) must be specified for backup targets")
	}

	return nil
}

// validateReportingTarget validates reporting target specific requirements
func validateReportingTarget(target *v1.Target) error {
	// Reporting targets must be ObjectStore type
	if target.Spec.Type != v1.ObjectStore {
		return fmt.Errorf("[spec.type] reporting targets must be of ObjectStore type, got: %s", target.Spec.Type)
	}

	// Additional reporting-specific validations can be added here
	// For example: ensure certain permissions, validate bucket access, etc.

	return nil
}

// validateReportingTargetUniqueness ensures only one reporting target exists in the cluster
func validateReportingTargetUniqueness(ctx context.Context, cl client.Client, target *v1.Target, isCreate bool) error {
	// List all targets in the cluster
	targetList := &v1.TargetList{}
	if err := cl.List(ctx, targetList); err != nil {
		return fmt.Errorf("error listing targets to check reporting target uniqueness: %w", err)
	}

	// Check if any other target is already a reporting target with Available status
	for i := range targetList.Items {
		existingTarget := &targetList.Items[i]

		// Skip the current target being created/updated
		if !isCreate && existingTarget.Name == target.Name {
			continue
		}

		// Check if this target is a reporting target with Available status
		if existingTarget.IsReportingTarget() && existingTarget.Status.Status == v1.Available {
			return fmt.Errorf("only one available reporting target is allowed, existing reporting target: %s", existingTarget.Name)
		}
	}

	return nil
}

// ValidateTargetDelete validates a Target on deletion
func ValidateTargetDelete(ctx context.Context, cl client.Client, target *v1.Target) error {
	// Prevent deletion if target is referenced by any active or queued scan instances
	if err := validateNoActiveScanInstances(ctx, cl, target); err != nil {
		return fmt.Errorf("cannot delete target: %w", err)
	}
	return nil
}

// validateReferencedResources validates that credential secret and SSL configmap exist
func validateReferencedResources(ctx context.Context, cl client.Client, target *v1.Target) error {
	if target.IsObjectStoreTarget() {
		// Validate credential secret exists
		if target.Spec.ObjectStoreCredentials.CredentialSecret != nil {
			secretRef := target.Spec.ObjectStoreCredentials.CredentialSecret
			secret := &corev1.Secret{}
			secretKey := types.NamespacedName{
				Name:      secretRef.Name,
				Namespace: secretRef.Namespace,
			}
			if err := cl.Get(ctx, secretKey, secret); err != nil {
				if apierrors.IsNotFound(err) {
					return fmt.Errorf("[spec.objectStoreCredentials.credentialSecret] secret '%s' not found in namespace '%s'",
						secretRef.Name, secretRef.Namespace)
				}
				return fmt.Errorf("[spec.objectStoreCredentials.credentialSecret] error checking secret existence: %w", err)
			}

			// Validate secret has required keys
			if _, ok := secret.Data["accessKey"]; !ok {
				return fmt.Errorf("[spec.objectStoreCredentials.credentialSecret] secret '%s' missing required key 'accessKey'",
					secretRef.Name)
			}
			if _, ok := secret.Data["secretKey"]; !ok {
				return fmt.Errorf("[spec.objectStoreCredentials.credentialSecret] secret '%s' missing required key 'secretKey'",
					secretRef.Name)
			}
		}

		// Validate SSL cert configmap exists if configured
		if target.HasSSLCertConfig() {
			cmRef := target.Spec.ObjectStoreCredentials.SSLCertConfig.CertConfigMap
			cm := &corev1.ConfigMap{}
			cmKey := types.NamespacedName{
				Name:      cmRef.Name,
				Namespace: cmRef.Namespace,
			}
			if err := cl.Get(ctx, cmKey, cm); err != nil {
				if apierrors.IsNotFound(err) {
					return fmt.Errorf("[spec.objectStoreCredentials.sslCertConfig.certConfigMap] configmap '%s' not found in namespace '%s'",
						cmRef.Name, cmRef.Namespace)
				}
				return fmt.Errorf("[spec.objectStoreCredentials.sslCertConfig.certConfigMap] error checking configmap existence: %w", err)
			}

			// Validate configmap has the specified cert key
			certKey := target.Spec.ObjectStoreCredentials.SSLCertConfig.CertKey
			if _, ok := cm.Data[certKey]; !ok {
				return fmt.Errorf("[spec.objectStoreCredentials.sslCertConfig.certKey] configmap '%s' missing required key '%s'",
					cmRef.Name, certKey)
			}
		}
	}

	return nil
}

// validateNoActiveScanInstances checks if target is referenced by active scan instances
func validateNoActiveScanInstances(ctx context.Context, cl client.Client, target *v1.Target) error {
	scanInstanceList := &v1.ScanInstanceList{}
	if err := cl.List(ctx, scanInstanceList); err != nil {
		return fmt.Errorf("error listing scan instances: %w", err)
	}

	for _, si := range scanInstanceList.Items {
		// Check if scan instance references this target
		if si.Spec.BackupTarget.Name == target.Name {
			// Check if scan instance is active (InProgress or Queued)
			if si.Status.Status == v1.ScanInProgress || si.Status.Status == v1.ScanQueued {
				return fmt.Errorf("target is referenced by active scan instance '%s' with status '%s'",
					si.Name, si.Status.Status)
			}
		}
	}

	return nil
}

// ValidateResourceQuantity validates a resource quantity
func ValidateResourceQuantity(quantity *resource.Quantity) error {
	if quantity == nil {
		return nil
	}

	// Basic validation - ensure it's not negative
	if quantity.Sign() < 0 {
		return fmt.Errorf("quantity cannot be negative")
	}

	// Validate it can be parsed
	if _, err := resource.ParseQuantity(quantity.String()); err != nil {
		return fmt.Errorf("invalid resource quantity format: %w", err)
	}

	return nil
}
