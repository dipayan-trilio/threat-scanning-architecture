package helpers

import (
	"context"
	"fmt"
	"os"
	"time"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	"github.com/trilioData/threat-scanning-architecture/internal"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// GetTargetValidatorJob creates a job spec to validate if the target can be mounted in a pod
func GetTargetValidatorJob(ctx context.Context, cl client.Client, target *v1.Target, credentialHash string) (*batchv1.Job, error) {
	var (
		validationCmd string
		volumes       []corev1.Volume
		volumeMounts  []corev1.VolumeMount
	)

	annotations := map[string]string{
		internal.Operation:                          internal.TargetValidationOperation,
		internal.TargetCredentialsHashAnnotationKey: credentialHash,
	}

	// Determine target type (backup or reporting)
	targetType := "backup"
	if target.IsReportingTarget() {
		targetType = "reporting"
	}

	// Build validation command with Python script
	// For NFS targets and reporting targets: directly run validation (no mount needed)
	// For backup ObjectStore targets: mount first (via s3fuse) then validate
	if target.IsNFSTarget() || target.IsReportingTarget() {
		// NFS: validates via direct NFS access
		// Reporting: validates via boto3 API (no mount needed)
		validationCmd = fmt.Sprintf("%s %s --target-name=%s --type=%s --group=threatscanning.trilio.io --version=v1",
			internal.Py3Path,
			fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreValidatorUtil),
			target.Name,
			targetType)
	} else {
		// For backup ObjectStore targets: mount via s3fuse, then validate via filesystem access
		mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
			internal.Py3Path,
			fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
			target.Name)
		validateCmd := fmt.Sprintf("%s %s --target-name=%s --type=%s --group=threatscanning.trilio.io --version=v1",
			internal.Py3Path,
			fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreValidatorUtil),
			target.Name,
			targetType)
		validationCmd = fmt.Sprintf("%s && %s", mountCmd, validateCmd)
	}

	// Build volumes based on target type
	if target.IsNFSTarget() {
		// Add NFS volume
		volumes, volumeMounts = getNFSVolumes(target, credentialHash)
	} else {
		// For object store targets, add secret volume for credentials if present
		if target.HasObjectStoreCredentialSecret() {
			secretVolume, secretMount := getSecretVolume(target)
			volumes = append(volumes, secretVolume)
			volumeMounts = append(volumeMounts, secretMount)
		}

		// Add SSL cert configmap volume if present
		if target.HasSSLCertConfig() {
			certVolume, certMount := getCertVolume(target)
			volumes = append(volumes, certVolume)
			volumeMounts = append(volumeMounts, certMount)
		}
	}

	// Create the validation container
	validationContainer := corev1.Container{
		Name:            "validator",
		Image:           getValidatorImage(),
		Command:         []string{"/bin/sh", "-c"},
		Args:            []string{validationCmd},
		ImagePullPolicy: corev1.PullIfNotPresent,
		VolumeMounts:    volumeMounts,
		Resources: corev1.ResourceRequirements{
			Requests: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("100m"),
				corev1.ResourceMemory: resource.MustParse("128Mi"),
			},
			Limits: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("500m"),
				corev1.ResourceMemory: resource.MustParse("512Mi"),
			},
		},
	}

	// For backup ObjectStore targets, we need privileged container for s3fuse mounting
	// Reporting targets use boto3 APIs directly, so no privileged access needed
	if target.IsObjectStoreTarget() && !target.IsReportingTarget() {
		privileged := true
		validationContainer.SecurityContext = &corev1.SecurityContext{
			Privileged: &privileged,
			Capabilities: &corev1.Capabilities{
				Add: []corev1.Capability{"SYS_ADMIN"},
			},
		}
	}

	// Add environment variables for object store targets
	if target.IsObjectStoreTarget() {
		validationContainer.Env = getObjectStoreEnvVars(target)
	}

	// Create the job
	jobName := GetTargetResourceName(internal.TargetValidationPrefix, credentialHash)
	backoffLimit := internal.JobBackoffLimit
	ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished

	// Get centralized labels and annotations
	labels := GetTargetResourceLabels(credentialHash, "target-validator")
	annotations = internal.MergeMaps(annotations, GetTargetResourceAnnotations(target, credentialHash))

	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:        jobName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		Spec: batchv1.JobSpec{
			BackoffLimit:            &backoffLimit,
			TTLSecondsAfterFinished: &ttlSecondsAfterFinished,
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: internal.ControllerServiceAccount,
					Containers:         []corev1.Container{validationContainer},
					Volumes:            volumes,
					RestartPolicy:      corev1.RestartPolicyNever,
				},
			},
		},
	}

	return job, nil
}

// getNFSVolumes creates volumes and volume mounts for NFS target
func getNFSVolumes(target *v1.Target, credentialHash string) ([]corev1.Volume, []corev1.VolumeMount) {
	volumeName := "nfs-target"

	volume := corev1.Volume{
		Name: volumeName,
		VolumeSource: corev1.VolumeSource{
			NFS: &corev1.NFSVolumeSource{
				Server: getNFSServer(target.Spec.NFSCredentials.NfsExport),
				Path:   getNFSPath(target.Spec.NFSCredentials.NfsExport),
			},
		},
	}

	volumeMount := corev1.VolumeMount{
		Name:      volumeName,
		MountPath: "/mnt/target",
	}

	return []corev1.Volume{volume}, []corev1.VolumeMount{volumeMount}
}

// getSecretVolume creates volume and volume mount for credential secret
func getSecretVolume(target *v1.Target) (corev1.Volume, corev1.VolumeMount) {
	volumeName := "credential-secret"

	volume := corev1.Volume{
		Name: volumeName,
		VolumeSource: corev1.VolumeSource{
			Secret: &corev1.SecretVolumeSource{
				SecretName: target.Spec.ObjectStoreCredentials.CredentialSecret.Name,
			},
		},
	}

	volumeMount := corev1.VolumeMount{
		Name:      volumeName,
		MountPath: "/etc/credentials",
		ReadOnly:  true,
	}

	return volume, volumeMount
}

// getCertVolume creates volume and volume mount for SSL certificate
func getCertVolume(target *v1.Target) (corev1.Volume, corev1.VolumeMount) {
	volumeName := "ssl-cert"

	volume := corev1.Volume{
		Name: volumeName,
		VolumeSource: corev1.VolumeSource{
			ConfigMap: &corev1.ConfigMapVolumeSource{
				LocalObjectReference: corev1.LocalObjectReference{
					Name: target.Spec.ObjectStoreCredentials.SSLCertConfig.CertConfigMap.Name,
				},
			},
		},
	}

	volumeMount := corev1.VolumeMount{
		Name:      volumeName,
		MountPath: "/etc/ssl/certs/custom",
		ReadOnly:  true,
	}

	return volume, volumeMount
}

// getObjectStoreEnvVars creates environment variables for object store target
func getObjectStoreEnvVars(target *v1.Target) []corev1.EnvVar {
	envVars := []corev1.EnvVar{
		{
			Name:  "TARGET_TYPE",
			Value: "ObjectStore",
		},
		{
			Name:  "TARGET_VENDOR",
			Value: string(target.Spec.Vendor),
		},
		{
			Name:  "TARGET_URL",
			Value: target.Spec.ObjectStoreCredentials.URL,
		},
		{
			Name:  "TARGET_BUCKET",
			Value: target.Spec.ObjectStoreCredentials.BucketName,
		},
		{
			Name:  "TARGET_REGION",
			Value: target.Spec.ObjectStoreCredentials.Region,
		},
	}

	// Add credentials from secret if present
	if target.HasObjectStoreCredentialSecret() {
		envVars = append(envVars,
			corev1.EnvVar{
				Name: "AWS_ACCESS_KEY_ID",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: target.Spec.ObjectStoreCredentials.CredentialSecret.Name,
						},
						Key: internal.AccessKeyName,
					},
				},
			},
			corev1.EnvVar{
				Name: "AWS_SECRET_ACCESS_KEY",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: target.Spec.ObjectStoreCredentials.CredentialSecret.Name,
						},
						Key: internal.SecretKeyName,
					},
				},
			},
		)
	}

	return envVars
}

// getValidatorImage returns the image to use for target validation
func getValidatorImage() string {
	if img := os.Getenv(internal.RelatedImageValidator); img != "" {
		return img
	}
	return internal.DefaultValidatorImage
}

// GetJobStatus returns the status of a job based on job conditions
func GetJobStatus(job *batchv1.Job) v1.Status {
	// Check job conditions first for more accurate status
	for _, condition := range job.Status.Conditions {
		if condition.Type == batchv1.JobComplete && condition.Status == corev1.ConditionTrue {
			return v1.Completed
		}
		if condition.Type == batchv1.JobFailed && condition.Status == corev1.ConditionTrue {
			return v1.Failed
		}
	}

	// Fall back to job status counters
	if job.Status.Succeeded > 0 {
		return v1.Completed
	}
	if job.Status.Failed > 0 {
		return v1.Failed
	}
	if job.Status.Active > 0 {
		return v1.InProgress
	}
	return v1.InProgress
}

// GetJobStatusWithPodCheck returns the status of a job by checking pod states for error conditions
// This is more accurate than just checking job status as it can detect CrashLoopBackOff, ImagePullBackOff, etc.
func GetJobStatusWithPodCheck(ctx context.Context, cl client.Client, job *batchv1.Job) v1.Status {
	// First check the job-level status
	jobStatus := GetJobStatus(job)

	// If job is already completed or failed, return that
	if jobStatus == v1.Completed || jobStatus == v1.Failed {
		return jobStatus
	}

	// For in-progress jobs, check pod status to detect errors early
	podList := &corev1.PodList{}
	err := cl.List(ctx, podList, client.InNamespace(job.Namespace), client.MatchingLabels{
		"job-name": job.Name,
	})
	if err != nil {
		// If we can't list pods, fall back to job status
		return jobStatus
	}

	// Check pod statuses for error conditions
	for _, pod := range podList.Items {
		// Check pod phase
		if pod.Status.Phase == corev1.PodFailed {
			return v1.Failed
		}
		if pod.Status.Phase == corev1.PodSucceeded {
			return v1.Completed
		}

		// Check container statuses for error states
		for _, containerStatus := range pod.Status.ContainerStatuses {
			// Check for waiting states that indicate failure
			if containerStatus.State.Waiting != nil {
				waiting := containerStatus.State.Waiting
				// These are error states that won't recover
				if waiting.Reason == "CrashLoopBackOff" ||
					waiting.Reason == "ImagePullBackOff" ||
					waiting.Reason == "ErrImagePull" ||
					waiting.Reason == "CreateContainerConfigError" ||
					waiting.Reason == "InvalidImageName" {
					return v1.Failed
				}
			}

			// Check for terminated states with non-zero exit code
			if containerStatus.State.Terminated != nil {
				terminated := containerStatus.State.Terminated
				if terminated.ExitCode != 0 {
					return v1.Failed
				}
				if terminated.Reason == "Error" {
					return v1.Failed
				}
			}
		}
	}

	return jobStatus
}

// IsJobPendingDeadlineExceeded checks if the job has exceeded the pending deadline
// This should only return true if the job is stuck in Pending state (not starting),
// not if the job is actively running (which is expected for sleep 60)
func IsJobPendingDeadlineExceeded(job *batchv1.Job) bool {
	if job.Status.StartTime == nil {
		return false
	}

	// If job has active pods (running), it's not stuck in pending - let it continue
	if job.Status.Active > 0 {
		return false
	}

	// If job succeeded or failed, no need to check deadline
	if job.Status.Succeeded > 0 || job.Status.Failed > 0 {
		return false
	}

	// Only check deadline if job has been created but has no active pods
	// (meaning it's stuck in pending/scheduling phase)
	deadline := job.Status.StartTime.Time.Add(time.Duration(internal.JobPendingDeadlineSeconds) * time.Second)
	return metav1.Now().After(deadline)
}

// GetTargetResourceLabels returns centralized labels for target-related resources
// This allows easy addition of new labels across all target resources
// Uses credentialHash instead of target name since resources are shared across targets with same credentials
func GetTargetResourceLabels(credentialHash, component string) map[string]string {
	labels := internal.GetRecommendedLabels(component, internal.ManagedBy)
	labels[internal.ResourceCreatorKindLabelKey] = internal.TargetKind
	labels[internal.TargetCredentialsHashAnnotationKey] = credentialHash
	return labels
}

// GetTargetResourceAnnotations returns centralized annotations for target-related resources
func GetTargetResourceAnnotations(target *v1.Target, credentialHash string) map[string]string {
	annotations := make(map[string]string)
	annotations[internal.TargetCredentialsHashAnnotationKey] = credentialHash
	annotations[internal.TargetNameAnnotationKey] = target.Name
	return annotations
}

// GetTargetPollerCronJob creates a cronjob spec for polling the target
func GetTargetPollerCronJob(ctx context.Context, cl client.Client, target *v1.Target, credentialHash string) (*batchv1.CronJob, error) {
	var (
		pollerCmd    string
		volumes      []corev1.Volume
		volumeMounts []corev1.VolumeMount
	)

	// Build poller command based on target type
	if target.IsNFSTarget() {
		pollerCmd = fmt.Sprintf("echo 'Polling NFS target: %s' && ls -la /mnt/target && echo 'Polling completed'", target.Name)
		volumes, volumeMounts = getNFSVolumes(target, credentialHash)
	} else {
		pollerCmd = fmt.Sprintf("echo 'Polling ObjectStore target: %s' && echo 'Polling completed'", target.Name)

		if target.HasObjectStoreCredentialSecret() {
			secretVolume, secretMount := getSecretVolume(target)
			volumes = append(volumes, secretVolume)
			volumeMounts = append(volumeMounts, secretMount)
		}

		if target.HasSSLCertConfig() {
			certVolume, certMount := getCertVolume(target)
			volumes = append(volumes, certVolume)
			volumeMounts = append(volumeMounts, certMount)
		}
	}

	// Create the poller container
	pollerContainer := corev1.Container{
		Name:            "poller",
		Image:           getPollerImage(),
		Command:         []string{"/bin/sh", "-c"},
		Args:            []string{pollerCmd},
		ImagePullPolicy: corev1.PullIfNotPresent,
		VolumeMounts:    volumeMounts,
		Resources: corev1.ResourceRequirements{
			Requests: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("100m"),
				corev1.ResourceMemory: resource.MustParse("128Mi"),
			},
			Limits: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("500m"),
				corev1.ResourceMemory: resource.MustParse("512Mi"),
			},
		},
	}

	// Add environment variables for object store targets
	if target.IsObjectStoreTarget() {
		pollerContainer.Env = getObjectStoreEnvVars(target)
	}

	// Generate cronjob name using credentialHash (shared across targets with same credentials)
	cronJobName := GetTargetResourceName(internal.TargetPollerPrefix, credentialHash)

	// Get centralized labels and annotations
	labels := GetTargetResourceLabels(credentialHash, "target-poller")
	annotations := GetTargetResourceAnnotations(target, credentialHash)
	annotations[internal.Operation] = internal.TargetPollerOperation

	// Get schedule from environment or use default
	schedule := os.Getenv("POLLER_SCHEDULE")
	if schedule == "" {
		schedule = internal.DefaultPollerSchedule
	}

	cronJob := &batchv1.CronJob{
		ObjectMeta: metav1.ObjectMeta{
			Name:        cronJobName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		Spec: batchv1.CronJobSpec{
			Schedule: schedule,
			JobTemplate: batchv1.JobTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      labels,
					Annotations: annotations,
				},
				Spec: batchv1.JobSpec{
					Template: corev1.PodTemplateSpec{
						ObjectMeta: metav1.ObjectMeta{
							Labels: labels,
						},
						Spec: corev1.PodSpec{
							ServiceAccountName: internal.ControllerServiceAccount,
							Containers:         []corev1.Container{pollerContainer},
							Volumes:            volumes,
							RestartPolicy:      corev1.RestartPolicyNever,
						},
					},
				},
			},
		},
	}

	return cronJob, nil
}

// getPollerImage returns the image to use for target polling
func getPollerImage() string {
	if img := os.Getenv(internal.RelatedImagePoller); img != "" {
		return img
	}
	return internal.DefaultPollerImage
}

// GetPreScanJob creates a job spec to perform pre-scan validation for a scan instance
func GetPreScanJob(ctx context.Context, cl client.Client, scanInstance interface{}, targetName, backupUID, backupPath string) (*batchv1.Job, error) {
	// Type assertion to get the scan instance name
	// For now, we'll use a simple placeholder implementation
	// TODO: Replace with actual pre-scan logic that:
	// 1. Validates the backup target accessibility (webhook validates existence and availability)
	// 2. Validates the backup path exists
	// 3. Determines the backup type - TVK/TVO
	// 4. Reads metadata and updates labels/annotations

	var (
		preScanCmd   string
		scanInstName string
	)

	// Extract scan instance name using reflection or type assertion
	// For now, we'll use a simple approach
	type NameGetter interface {
		GetName() string
	}
	if ng, ok := scanInstance.(NameGetter); ok {
		scanInstName = ng.GetName()
	} else {
		return nil, fmt.Errorf("unable to get scan instance name")
	}

	annotations := map[string]string{
		internal.Operation:             "pre-scan",
		internal.ScanInstanceNameLabel: scanInstName,
	}

	// Build pre-scan command - placeholder that prints the captured values
	// TODO: Replace with actual pre-scan script that:
	// - Fetches target CR using targetName
	// - Validates target accessibility
	// - Mounts target and validates backup path exists
	// - Determines backup type and reads metadata
	// - Updates ScanInstance labels/annotations via Kubernetes API
	preScanCmd = fmt.Sprintf(`
echo "=========================================="
echo "PreScan Job - ScanInstance: %s"
echo "=========================================="
echo "Target Name: %s"
echo "Backup UID: %s"
echo "Backup Path: %s"
echo "=========================================="
echo ""
echo "Starting pre-scan validation..."
echo "- Fetching target CR: %s"
echo "- Validating target accessibility..."
echo "- Validating backup path exists: %s"
echo "- Determining backup type (TVK/TVO)..."
echo "- Reading metadata files..."
echo "- Checking for VM workloads..."
echo ""
echo "Pre-scan validation completed successfully!"
echo "=========================================="
sleep 5
`,
		scanInstName,
		targetName,
		backupUID,
		backupPath,
		targetName,
		backupPath)

	// Create the pre-scan container
	// PreScan job will fetch target CR and mount it based on target type
	preScanContainer := corev1.Container{
		Name:            "prescan",
		Image:           getValidatorImage(), // Reuse validator image for now
		Command:         []string{"/bin/sh", "-c"},
		Args:            []string{preScanCmd},
		ImagePullPolicy: corev1.PullIfNotPresent,
		Resources: corev1.ResourceRequirements{
			Requests: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("100m"),
				corev1.ResourceMemory: resource.MustParse("128Mi"),
			},
			Limits: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("500m"),
				corev1.ResourceMemory: resource.MustParse("512Mi"),
			},
		},
		// PreScan job needs access to Kubernetes API to:
		// 1. Fetch target CR
		// 2. Update ScanInstance labels/annotations
		// ServiceAccount: threat-scanning-controller (has required RBAC)
	}

	// Create the job
	jobName := GetScanInstanceResourceName(internal.ScanInstancePreScanPrefix, scanInstName)
	backoffLimit := internal.JobBackoffLimit
	ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished

	// Get centralized labels and annotations
	labels := GetScanInstanceResourceLabels(scanInstName, "prescan")
	annotations = internal.MergeMaps(annotations, GetScanInstanceResourceAnnotations(scanInstName))

	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:        jobName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		Spec: batchv1.JobSpec{
			BackoffLimit:            &backoffLimit,
			TTLSecondsAfterFinished: &ttlSecondsAfterFinished,
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: internal.ControllerServiceAccount,
					Containers:         []corev1.Container{preScanContainer},
					RestartPolicy:      corev1.RestartPolicyNever,
				},
			},
		},
	}

	return job, nil
}

// GetScanInstanceResourceName generates a resource name for scan instance related resources
func GetScanInstanceResourceName(prefix, scanInstanceName string) string {
	// Truncate scan instance name if too long to fit within k8s name limits (253 chars)
	maxNameLen := 253 - len(prefix) - 1 // -1 for the hyphen
	if len(scanInstanceName) > maxNameLen {
		scanInstanceName = scanInstanceName[:maxNameLen]
	}
	return fmt.Sprintf("%s-%s", prefix, scanInstanceName)
}

// GetScanInstanceResourceLabels returns centralized labels for scan instance related resources
func GetScanInstanceResourceLabels(scanInstanceName, component string) map[string]string {
	labels := internal.GetRecommendedLabels(component, internal.ManagedBy)
	labels[internal.ResourceCreatorKindLabelKey] = internal.ScanInstanceKind
	labels[internal.ScanInstanceNameLabel] = scanInstanceName
	return labels
}

// GetScanInstanceResourceAnnotations returns centralized annotations for scan instance related resources
func GetScanInstanceResourceAnnotations(scanInstanceName string) map[string]string {
	annotations := make(map[string]string)
	annotations[internal.ScanInstanceNameLabel] = scanInstanceName
	return annotations
}
