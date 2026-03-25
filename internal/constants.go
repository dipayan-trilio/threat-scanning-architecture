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

	// ScanInstanceScanConfigPrefix is the prefix for scan config configmap
	ScanInstanceScanConfigPrefix = "scan-config"

	// ScanInstanceRedisDeployPrefix is the prefix for redis deployment
	ScanInstanceRedisDeployPrefix = "redis-deploy"

	// ScanInstanceRedisServicePrefix is the prefix for redis service
	ScanInstanceRedisServicePrefix = "redis-svc"

	// ScanInstanceJanitorJobPrefix is the prefix for janitor job resources
	ScanInstanceJanitorJobPrefix = "threat-scan-janitor"

	// ScanInstanceNameLabel is the label key for scan instance name
	ScanInstanceNameLabel = "trilio.io/scaninstance-name"

	// PrescanErrorAnnotation is the annotation key for prescan job error messages
	PrescanErrorAnnotation = "threatscanning.trilio.io/prescan-error"

	// ScanErrorAnnotation is the annotation key for scan job error messages
	ScanErrorAnnotation = "threatscanning.trilio.io/scan-error"

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
	JobPendingDeadlineSeconds = 900

	// SecretKeyName is the key name for secret key in credential secret
	SecretKeyName = "secretKey"

	// AccessKeyName is the key name for access key in credential secret
	AccessKeyName = "accessKey"

	// CABundle is the key name for CA bundle
	CABundle = "caBundle"

	// PendingDeadlineSeconds is the default pending deadline
	PendingDeadlineSeconds = int64(300)

	// JobBackoffLimit is the backoff limit for jobs (0 = no retries for validation/poller)
	JobBackoffLimit = int32(0)

	// ScanJobBackoffLimit is the backoff limit for scan jobs (3 retries before failure)
	ScanJobBackoffLimit = int32(3)

	// JobTTLSecondsAfterFinished is the TTL for jobs after finished
	JobTTLSecondsAfterFinished = int32(300)

	// RelatedImageValidator is the environment variable name for validator image
	RelatedImageValidator = "RELATED_IMAGE_VALIDATOR"

	// RelatedImagePoller is the environment variable name for poller image
	RelatedImagePoller = "RELATED_IMAGE_POLLER"

	// RelatedImageScanner is the environment variable name for scanner image
	RelatedImageScanner = "RELATED_IMAGE_SCANNER"

	// RelatedImageRedis is the environment variable name for redis image
	RelatedImageRedis = "RELATED_IMAGE_REDIS"

	// RelatedImageJanitor is the environment variable name for janitor image
	RelatedImageJanitor = "RELATED_IMAGE_JANITOR"

	// DatabaseURL is the environment variable name for database URL
	DatabaseURL = "DATABASE_URL"

	// TargetPollingCron is the environment variable name for target polling cron schedule
	TargetPollingCron = "TARGET_POLLING_CRON"

	// TargetPollingDisabled is the environment variable name to disable target polling
	TargetPollingDisabled = "TARGET_POLLING_DISABLED"

	// DefaultValidatorImage is the default validator image if env var not set
	DefaultValidatorImage = "gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:latest"

	// DefaultPollerImage is the default poller image if env var not set
	DefaultPollerImage = "threat-scan-poller:latest"

	// DefaultScannerImage is the default scanner image if env var not set
	DefaultScannerImage = "threat-scan-scanner:latest"

	// DefaultRedisImage is the default redis image if env var not set
	DefaultRedisImage = "redis:7-alpine"

	// DefaultJanitorImage is the default janitor image if env var not set
	DefaultJanitorImage = "threat-scan-janitor:latest"

	// DefaultDatabaseURL is the default database URL if env var not set (SQLite)
	DefaultDatabaseURL = "sqlite+aiosqlite:///./scan_analysis.db"

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

	// DefaultDatastoreBase is the default mount path for datastores (NFS, ObjectStore)
	// This path is used consistently across validation, polling, prescan, and scan jobs
	// Matches k8s-triliovault's DefaultDatastoreBase constant
	DefaultDatastoreBase = "/triliodata"
)

// GetInstallNamespace returns the installation namespace from environment variable or default
func GetInstallNamespace() string {
	if ns := os.Getenv(InstallNamespaceEnvVar); ns != "" {
		return ns
	}
	return DefaultInstallNamespace
}

// GetRedisImage returns the Redis image from environment variable or default
func GetRedisImage() string {
	if img := os.Getenv(RelatedImageRedis); img != "" {
		return img
	}
	return DefaultRedisImage
}

// GetJanitorImage returns the Janitor image from environment variable or default
func GetJanitorImage() string {
	if img := os.Getenv(RelatedImageJanitor); img != "" {
		return img
	}
	return DefaultJanitorImage
}

// GetDatabaseURL returns the database URL from environment variable or default
func GetDatabaseURL() string {
	if url := os.Getenv(DatabaseURL); url != "" {
		return url
	}
	return DefaultDatabaseURL
}

// GetTargetPollingCron returns the target polling cron schedule from environment variable or default
// Validates the cron expression and returns default if invalid
func GetTargetPollingCron(logger interface {
	Warnf(format string, args ...interface{})
}) string {
	cronExpr := os.Getenv(TargetPollingCron)
	if cronExpr == "" {
		return DefaultPollerSchedule
	}

	// Validate cron expression (basic validation for 5-field cron)
	if !isValidCronExpression(cronExpr) {
		if logger != nil {
			logger.Warnf("Invalid cron expression in %s: '%s'. Using default: %s",
				TargetPollingCron, cronExpr, DefaultPollerSchedule)
		}
		return DefaultPollerSchedule
	}

	return cronExpr
}

// isValidCronExpression performs basic validation of cron expression
// Validates 5-field cron format: minute hour day month weekday
func isValidCronExpression(expr string) bool {
	// Basic validation: check if it has 5 fields
	fields := splitCronFields(expr)
	if len(fields) != 5 {
		return false
	}

	// Additional validation can be added here
	// For now, we trust Kubernetes CronJob validation
	return true
}

// splitCronFields splits cron expression into fields, handling multiple spaces
func splitCronFields(expr string) []string {
	var fields []string
	currentField := ""
	for _, char := range expr {
		if char == ' ' || char == '\t' {
			if currentField != "" {
				fields = append(fields, currentField)
				currentField = ""
			}
		} else {
			currentField += string(char)
		}
	}
	if currentField != "" {
		fields = append(fields, currentField)
	}
	return fields
}

// IsTargetPollingDisabled returns true if target polling is disabled via environment variable
func IsTargetPollingDisabled() bool {
	disabled := os.Getenv(TargetPollingDisabled)
	return disabled == "true" || disabled == "True" || disabled == "TRUE" || disabled == "1"
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
