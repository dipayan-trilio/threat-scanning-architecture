package internal

import "os"

const (
	// TargetValidationPrefix is the prefix for target validation resources
	TargetValidationPrefix = "threat-scan-target-validation"

	// TargetPollerPrefix is the prefix for target poller resources
	TargetPollerPrefix = "threat-scan-target-poller"

	// TargetPollerCronJobPrefix is the prefix for target poller cronjobs (deprecated, use TargetPollerPrefix)
	TargetPollerCronJobPrefix = "poller"

	// TargetCredentialsHashAnnotationKey is the annotation key for target credentials hash
	TargetCredentialsHashAnnotationKey = "trilio.io/target-credentials-hash"

	// TargetNameAnnotationKey is the annotation key for target name
	TargetNameAnnotationKey = "trilio.io/target-name"

	// TargetDeleteFinalizer is the finalizer for target deletion
	TargetDeleteFinalizer = "threatscanning.trilio.io/target-finalizer"

	// TargetKind is the kind for Target resource
	TargetKind = "Target"

	// ScanInstanceDeleteFinalizer is the finalizer for scan instance deletion
	ScanInstanceDeleteFinalizer = "threatscanning.trilio.io/scaninstance-finalizer"

	// ScanInstanceKind is the kind for ScanInstance resource
	ScanInstanceKind = "ScanInstance"

	// ScanInstancePreScanPrefix is the prefix for pre-scan job resources
	ScanInstancePreScanPrefix = "threat-scan-prescan"

	// ScanInstanceScanJobPrefix is the prefix for scan job resources
	ScanInstanceScanJobPrefix = "threat-scan-scanjob"

	// ScanInstanceNameLabel is the label key for scan instance name
	ScanInstanceNameLabel = "trilio.io/scaninstance-name"

	// Operation annotation key
	Operation = "trilio.io/operation"

	// TargetValidationOperation is the operation type for target validation
	TargetValidationOperation = "target-validation"

	// TargetPollerOperation is the operation type for target polling
	TargetPollerOperation = "target-polling"

	// InstallNamespaceEnvVar is the environment variable name for installation namespace
	InstallNamespaceEnvVar = "INSTALL_NAMESPACE"

	// DefaultInstallNamespace is the default namespace if env var not set
	DefaultInstallNamespace = "threat-scanning-system"

	// TargetValidationConfig is the name of the validation configmap
	TargetValidationConfig = "threat-scan-target-validation-config"

	// TargetHashFieldSelector is the field selector for target hash
	TargetHashFieldSelector = "metadata.annotations[trilio.io/target-credentials-hash]"

	// SecretToTargetFieldSelector is the field selector for secret to target mapping
	SecretToTargetFieldSelector = "spec.objectStoreCredentials.credentialSecret.name"

	// TargetNFSVolumePrefix is the prefix for NFS volumes
	TargetNFSVolumePrefix = "threat-scan-nfs-volume"

	// K8sPartOfLabel is the label key for Kubernetes part-of
	K8sPartOfLabel = "app.kubernetes.io/part-of"

	// PartOfThreatScanning is the value for part-of label
	PartOfThreatScanning = "threat-scanning"

	// ManagedBy is the value for managed-by label
	ManagedBy = "threat-scanning-controller"

	// ResourceCreatorKindLabelKey is the label key for resource creator kind
	ResourceCreatorKindLabelKey = "trilio.io/creator-kind"

	// JobPendingDeadlineSeconds is the default deadline for pending jobs
	JobPendingDeadlineSeconds = 300

	// SecretKeyName is the key name for secret key in credential secret
	SecretKeyName = "secretKey"

	// AccessKeyName is the key name for access key in credential secret
	AccessKeyName = "accessKey"

	// CABundle is the key name for CA bundle
	CABundle = "caBundle"

	// PendingDeadlineSeconds is the default pending deadline
	PendingDeadlineSeconds = int64(300)

	// JobBackoffLimit is the backoff limit for jobs
	JobBackoffLimit = int32(0)

	// JobTTLSecondsAfterFinished is the TTL for jobs after finished
	JobTTLSecondsAfterFinished = int32(300)

	// RelatedImageValidator is the environment variable name for validator image
	RelatedImageValidator = "RELATED_IMAGE_VALIDATOR"

	// RelatedImagePoller is the environment variable name for poller image
	RelatedImagePoller = "RELATED_IMAGE_POLLER"

	// DefaultValidatorImage is the default validator image if env var not set
	DefaultValidatorImage = "gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:latest"

	// DefaultPollerImage is the default poller image if env var not set
	DefaultPollerImage = "threat-scan-poller:latest"

	// DefaultPollerSchedule is the default cron schedule for poller (every 6 hours)
	DefaultPollerSchedule = "0 */6 * * *"

	// ControllerServiceAccount is the service account name used by the controller and child resources
	ControllerServiceAccount = "trilio-threat-scanning"

	// Datastore-attacher paths (Python scripts for target validation and mounting)
	BasePath                         = "/opt/threat-scanning"
	Py3Path                          = "/usr/bin/python3"
	DatastoreValidatorUtil           = "datastore-attacher/scripts/target_validations.py"
	DatastoreMountUtil               = "datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py"
	DatastoreAttacherPathInContainer = "/opt/threat-scanning/datastore-attacher"
)

// GetInstallNamespace returns the installation namespace from environment variable or default
func GetInstallNamespace() string {
	if ns := os.Getenv(InstallNamespaceEnvVar); ns != "" {
		return ns
	}
	return DefaultInstallNamespace
}

// GetRecommendedLabels returns the recommended labels
func GetRecommendedLabels(component, managedBy string) map[string]string {
	labels := map[string]string{
		K8sPartOfLabel: PartOfThreatScanning,
	}
	if component != "" {
		labels["app.kubernetes.io/component"] = component
	}
	if managedBy != "" {
		labels["app.kubernetes.io/managed-by"] = managedBy
	}
	return labels
}

// ContainsString checks if a string is present in a slice
func ContainsString(slice []string, s string) bool {
	for _, item := range slice {
		if item == s {
			return true
		}
	}
	return false
}

// RemoveString removes a string from a slice
func RemoveString(slice []string, s string) []string {
	result := []string{}
	for _, item := range slice {
		if item != s {
			result = append(result, item)
		}
	}
	return result
}

// MergeMaps merges two maps
func MergeMaps(map1, map2 map[string]string) map[string]string {
	result := make(map[string]string)
	for k, v := range map1 {
		result[k] = v
	}
	for k, v := range map2 {
		result[k] = v
	}
	return result
}
