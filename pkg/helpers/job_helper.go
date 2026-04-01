package helpers

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
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

	// Build validation command: mount datastore first, then validate
	// For NFS targets and reporting targets: mount via NFS volume or use boto3 API
	// For backup ObjectStore targets: mount via s3fuse, then validate
	mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
		internal.Py3Path,
		fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
		target.Name)

	validateCmd := fmt.Sprintf("target-validator --target-name=%s --type=%s --group=threatscanning.trilio.io --version=v1",
		target.Name,
		targetType)

	// For NFS targets and reporting targets, mounting is handled differently
	if target.IsNFSTarget() {
		// NFS: Direct mount via volume, no need for mount command
		validationCmd = validateCmd
	} else if target.IsReportingTarget() {
		// Reporting: Uses boto3 API, no mounting needed
		validationCmd = validateCmd
	} else {
		// ObjectStore backup targets: mount first, then validate
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
		Command:         []string{"/bin/bash", "-c"},
		Args:            []string{validationCmd},
		ImagePullPolicy: corev1.PullAlways,
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
	// Do NOT set TTLSecondsAfterFinished for target validation jobs
	// Following TVK pattern: jobs are kept until manually cleaned up by the controller
	// Successful validations: cleaned when target becomes Available
	// Failed validations: kept for debugging, awaiting manual cleanup

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
			BackoffLimit: &backoffLimit,
			// TTLSecondsAfterFinished is intentionally not set
			// Jobs are manually cleaned up:
			// - On success: when target becomes Available (see reconcileValidationJob)
			// - On failure: kept for debugging, manual cleanup required
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
// Uses PVC instead of inline NFS to support mount options
func getNFSVolumes(target *v1.Target, credentialHash string) ([]corev1.Volume, []corev1.VolumeMount) {
	volumeName := "nfs-target"
	pvcName := GetTargetResourceName(internal.TargetNFSVolumePrefix, credentialHash)

	// Use PVC to mount NFS volume so that mount options from PV are applied
	volume := corev1.Volume{
		Name: volumeName,
		VolumeSource: corev1.VolumeSource{
			PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
				ClaimName: pvcName,
			},
		},
	}

	volumeMount := corev1.VolumeMount{
		Name:      volumeName,
		MountPath: internal.DefaultDatastoreBase,
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
	// Check job conditions first for most accurate status
	// Job conditions are set by Kubernetes when the job reaches a terminal state
	for _, condition := range job.Status.Conditions {
		if condition.Type == batchv1.JobComplete && condition.Status == corev1.ConditionTrue {
			return v1.Completed
		}
		if condition.Type == batchv1.JobFailed && condition.Status == corev1.ConditionTrue {
			return v1.Failed
		}
	}

	// Fall back to job status counters
	// IMPORTANT: job.Status.Failed counts failed pod attempts, not job failure
	// A job is only considered failed when it exhausts all retries (backoffLimit)
	// Kubernetes sets the JobFailed condition when backoffLimit is reached
	if job.Status.Succeeded > 0 {
		return v1.Completed
	}
	
	// Job is still in progress if it has active pods or failed attempts below backoff limit
	if job.Status.Active > 0 {
		return v1.InProgress
	}
	
	// If there are failed attempts but no Active condition or Failed condition,
	// the job is likely retrying (between attempts)
	if job.Status.Failed > 0 {
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
// timeoutSeconds: the timeout duration in seconds (use 0 for default JobPendingDeadlineSeconds)
func IsJobPendingDeadlineExceeded(job *batchv1.Job, timeoutSeconds int64) bool {
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

	// Use default timeout if not specified
	if timeoutSeconds <= 0 {
		timeoutSeconds = internal.JobPendingDeadlineSeconds
	}

	// Only check deadline if job has been created but has no active pods
	// (meaning it's stuck in pending/scheduling phase)
	deadline := job.Status.StartTime.Time.Add(time.Duration(timeoutSeconds) * time.Second)
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
func GetTargetPollerCronJob(ctx context.Context, cl client.Client, target *v1.Target, credentialHash string, logger interface {
	Warnf(format string, args ...interface{})
}) (*batchv1.CronJob, error) {
	var (
		pollerCmd    string
		volumes      []corev1.Volume
		volumeMounts []corev1.VolumeMount
	)

	// Build poller command: mount datastore first, then poll
	mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
		internal.Py3Path,
		fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
		target.Name)

	pollCmd := fmt.Sprintf("target-poller --target-name=%s --target-type=%s --group=threatscanning.trilio.io --version=v1",
		target.Name,
		target.Spec.TargetType)

	// For NFS targets, mounting is handled via volume, no need for mount command
	if target.IsNFSTarget() {
		pollerCmd = pollCmd
	} else {
		// ObjectStore targets: mount first, then poll
		pollerCmd = fmt.Sprintf("%s && %s", mountCmd, pollCmd)
	}

	// Add volumes based on target type
	if target.IsNFSTarget() {
		volumes, volumeMounts = getNFSVolumes(target, credentialHash)
	} else {
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
		Command:         []string{"/bin/bash", "-c"},
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

	// For ObjectStore targets, we need privileged container for s3fuse mounting
	if target.IsObjectStoreTarget() {
		privileged := true
		pollerContainer.SecurityContext = &corev1.SecurityContext{
			Privileged: &privileged,
			Capabilities: &corev1.Capabilities{
				Add: []corev1.Capability{"SYS_ADMIN"},
			},
		}
	}

	// Generate cronjob name using credentialHash (shared across targets with same credentials)
	cronJobName := GetTargetResourceName(internal.TargetPollerPrefix, credentialHash)

	// Get centralized labels and annotations
	labels := GetTargetResourceLabels(credentialHash, "target-poller")
	annotations := GetTargetResourceAnnotations(target, credentialHash)
	annotations[internal.Operation] = internal.TargetPollerOperation

	// Get schedule from environment with validation
	schedule := internal.GetTargetPollingCron(logger)

	// Check if polling is disabled
	suspend := internal.IsTargetPollingDisabled()

	// Set concurrency policy to Forbid (only one job at a time)
	concurrencyPolicy := batchv1.ForbidConcurrent

	cronJob := &batchv1.CronJob{
		ObjectMeta: metav1.ObjectMeta{
			Name:        cronJobName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		Spec: batchv1.CronJobSpec{
			Schedule:          schedule,
			Suspend:           &suspend,
			ConcurrencyPolicy: concurrencyPolicy,
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
func GetPreScanJob(ctx context.Context, cl client.Client, scanInstance interface{}, target *v1.Target, backupUID, backupPath string) (*batchv1.Job, error) {
	// Type assertion to get the scan instance name
	var scanInstName string

	// Extract scan instance name using reflection or type assertion
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

	// Get target credentials hash for volume lookups
	credentialHash := target.GetAnnotations()[internal.TargetCredentialsHashAnnotationKey]

	var (
		preScanCmd   string
		volumes      []corev1.Volume
		volumeMounts []corev1.VolumeMount
	)

	prescanCmd := fmt.Sprintf("prescan --target-name=%s --backup-path=%s --backup-uid=%s --scaninstance-name=%s --target-type=%s",
		target.Name,
		backupPath,
		backupUID,
		scanInstName,
		target.Spec.TargetType)

	// For NFS targets: PVC is already mounted at /triliodata, no need for mount command
	// For ObjectStore targets: need to mount via s3fuse first
	if target.IsNFSTarget() {
		preScanCmd = prescanCmd
		volumes, volumeMounts = getNFSVolumes(target, credentialHash)
	} else {
		// ObjectStore: mount first, then run prescan
		mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
			internal.Py3Path,
			fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
			target.Name)
		preScanCmd = fmt.Sprintf("%s && %s", mountCmd, prescanCmd)
	}

	// Create the pre-scan container
	// PreScan job needs:
	// - For ObjectStore: Privileged access for s3fuse mounting
	// - For NFS: No privileged access needed (PVC mount handles it)
	// - Access to Kubernetes API to fetch target CR and update ScanInstance
	// - ServiceAccount: threat-scanning-controller (has required RBAC)
	preScanContainer := corev1.Container{
		Name:            "prescan",
		Image:           getValidatorImage(), // datastore-attacher image with prescan CLI
		Command:         []string{"/bin/bash", "-c"},
		Args:            []string{preScanCmd},
		ImagePullPolicy: corev1.PullAlways,
		VolumeMounts:    volumeMounts,
		Env: []corev1.EnvVar{
			// JOB_NAME and JOB_NAMESPACE for error annotation updates
			{
				Name: "JOB_NAME",
				ValueFrom: &corev1.EnvVarSource{
					FieldRef: &corev1.ObjectFieldSelector{
						FieldPath: "metadata.labels['job-name']",
					},
				},
			},
			{
				Name: "JOB_NAMESPACE",
				ValueFrom: &corev1.EnvVarSource{
					FieldRef: &corev1.ObjectFieldSelector{
						FieldPath: "metadata.namespace",
					},
				},
			},
		},
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

	// Add privileged security context only for ObjectStore targets (needed for s3fuse)
	if target.IsObjectStoreTarget() {
		privileged := true
		preScanContainer.SecurityContext = &corev1.SecurityContext{
			Privileged: &privileged,
			Capabilities: &corev1.Capabilities{
				Add: []corev1.Capability{"SYS_ADMIN"},
			},
		}
	}

	// Create the job
	jobName := GetScanInstanceResourceName(internal.ScanInstancePreScanPrefix, scanInstName)
	backoffLimit := internal.JobBackoffLimit
	// Do NOT set TTLSecondsAfterFinished for ScanInstance jobs
	// Following TVK pattern: jobs are kept until manually cleaned up by the controller
	// This allows inspection of logs for debugging and matches k8s-triliovault behavior

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
			BackoffLimit: &backoffLimit,
			// TTLSecondsAfterFinished is intentionally not set
			// Jobs are manually cleaned up by cleanupScanInstanceJobs when ScanInstance completes
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: internal.ControllerServiceAccount,
					Containers:         []corev1.Container{preScanContainer},
					Volumes:            volumes,
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

// GetScanConfigMapData generates the configmap data for scan job from scanLocations
// The format matches the enhanced-soc-analysis requirement with complete VM artifact structure
// Currently filters to scan only the boot disk (first PVC path) per VM
func GetScanConfigMapData(scanLocations []v1.ScanLocation, backupMetadata map[string]string) (map[string]string, error) {
	// Build the vm_artifacts structure
	vmArtifacts := make(map[string]interface{})

	for _, location := range scanLocations {
		for _, vm := range location.VMs {
			// For now, only scan the boot disk (first PVC path)
			// Future: Implement proper boot disk detection logic
			var diskImage, memoryDump string
			if len(vm.PVCPaths) > 0 {
				// Take only the first PVC path as boot disk approximation
				// Add DefaultDatastoreBase prefix since target is mounted there in scan job
				// Append /pv.qcow2 to get the actual disk image file
				// Append /memory.dmp to get the memory dump file (if exists)
				// Ensure proper path separator
				pvcPath := vm.PVCPaths[0]
				if !strings.HasPrefix(pvcPath, "/") {
					pvcPath = "/" + pvcPath
				}
				// Construct full paths
				diskImage = fmt.Sprintf("%s%s/pv.qcow2", internal.DefaultDatastoreBase, pvcPath)
				memoryDump = fmt.Sprintf("%s%s/memory.dmp", internal.DefaultDatastoreBase, pvcPath)
			} else {
				// No PVCs found for this VM, skip it
				continue
			}

			// Construct key as vmname_namespace
			// If namespace is empty (single namespace backup), use "default"
			namespace := location.Namespace
			if namespace == "" {
				namespace = "default"
			}
			vmKey := fmt.Sprintf("%s_%s", vm.VMName, namespace)

			// Create complete VM artifact structure matching enhanced-soc-analysis format
			vmArtifacts[vmKey] = map[string]interface{}{
				"description":          fmt.Sprintf("VM from backup %s", location.BackupUID),
				"hostname":             vm.VMName,
				"ip_address":           "0.0.0.0",  // Dummy value - not available from backup
				"os":                   "Unknown",  // Dummy value - not available from backup
				"memory_dump":          memoryDump, // Path to memory dump file
				"disk_image":           diskImage,  // Path to disk image file
				"collection_time":      time.Now().UTC().Format(time.RFC3339),
				"priority":             "high",
				"suspected_compromise": true,
			}
		}
	}

	// Build the complete config structure with vm_collection_metadata
	data := map[string]interface{}{
		"vm_artifacts": vmArtifacts,
	}

	// Add vm_collection_metadata if backup metadata is provided
	if backupMetadata != nil && len(backupMetadata) > 0 {
		vmCollectionMetadata := make(map[string]string)
		if instanceID, ok := backupMetadata["instance_id"]; ok && instanceID != "" {
			vmCollectionMetadata["instance_id"] = instanceID
		}
		if backupUID, ok := backupMetadata["backup_uid"]; ok && backupUID != "" {
			vmCollectionMetadata["backup_uid"] = backupUID
		}
		if targetName, ok := backupMetadata["backup_target_name"]; ok && targetName != "" {
			vmCollectionMetadata["backup_target_name"] = targetName
		}
		if planUID, ok := backupMetadata["backupplan_uid"]; ok && planUID != "" {
			vmCollectionMetadata["backupplan_uid"] = planUID
		}
		if timestamp, ok := backupMetadata["backup_timestamp"]; ok && timestamp != "" {
			vmCollectionMetadata["backup_timestamp"] = timestamp
		}

		// Add to data structure if any metadata present
		if len(vmCollectionMetadata) > 0 {
			data["vm_collection_metadata"] = map[string]interface{}{
				"backup-metadata": vmCollectionMetadata,
			}
		}
	}

	jsonData, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("failed to marshal scan config data: %w", err)
	}

	// Return as configmap data (single file named "vm_artifacts_configuration.json")
	return map[string]string{
		"vm_artifacts_configuration.json": string(jsonData),
	}, nil
}

// GetScanConfigMap creates a configmap for scan job configuration
func GetScanConfigMap(scanInstance *v1.ScanInstance) (*corev1.ConfigMap, error) {
	configMapName := GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, scanInstance.Name)

	// Extract backup metadata from ScanInstance labels and annotations
	backupMetadata := make(map[string]string)

	// Read from labels (set by prescan)
	if scanInstance.Labels != nil {
		if instanceID := scanInstance.Labels[internal.InstanceIDLabel]; instanceID != "" {
			backupMetadata["instance_id"] = instanceID
		}
		if backupUID := scanInstance.Labels[internal.BackupLabel]; backupUID != "" {
			backupMetadata["backup_uid"] = backupUID
		}
		if targetName := scanInstance.Labels[internal.BackupTargetLabel]; targetName != "" {
			backupMetadata["backup_target_name"] = targetName
		}
		if planUID := scanInstance.Labels[internal.BackupPlanLabel]; planUID != "" {
			backupMetadata["backupplan_uid"] = planUID
		}
	}

	// Read backup creation timestamp from annotations
	if scanInstance.Annotations != nil {
		if timestamp := scanInstance.Annotations[internal.BackupCreationTimestampAnnotation]; timestamp != "" {
			backupMetadata["backup_timestamp"] = timestamp
		}
	}

	// Generate configmap data from scanLocations with backup metadata
	data, err := GetScanConfigMapData(scanInstance.Status.ScanLocations, backupMetadata)
	if err != nil {
		return nil, err
	}

	// Get centralized labels and annotations
	labels := GetScanInstanceResourceLabels(scanInstance.Name, "scan-config")
	annotations := GetScanInstanceResourceAnnotations(scanInstance.Name)

	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:        configMapName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		Data: data,
	}

	return configMap, nil
}

// GetScanSecret creates a secret with PostgreSQL database credentials for scan job
func GetScanSecret(scanInstance *v1.ScanInstance) (*corev1.Secret, error) {
	secretName := GetScanInstanceResourceName(internal.ScanInstanceScanSecretPrefix, scanInstance.Name)

	// Get PostgreSQL configuration from environment
	pgHost := internal.GetPostgresHost()
	pgPort := internal.GetPostgresPort()
	pgUser := internal.GetPostgresUser()
	pgPassword := internal.GetPostgresPassword()
	pgDashboardDB := internal.GetPostgresDashboardDatabase()
	pgCacheDB := internal.GetPostgresCacheDatabase()

	// Build DATABASE_URL for cache database
	// Format: postgresql+asyncpg://user:password@host:port/database
	databaseURL := fmt.Sprintf("postgresql+asyncpg://%s:%s@%s:%s/%s",
		pgUser, pgPassword, pgHost, pgPort, pgCacheDB)

	// Create secret data
	secretData := map[string]string{
		"DATABASE_URL": databaseURL,
		"PG_HOST":      pgHost,
		"PG_PORT":      pgPort,
		"PG_DB":        pgDashboardDB,
		"PG_PASSWORD":  pgPassword,
		"PG_USER":      pgUser,
	}

	// Get centralized labels and annotations
	labels := GetScanInstanceResourceLabels(scanInstance.Name, "scan-secret")
	annotations := GetScanInstanceResourceAnnotations(scanInstance.Name)

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:        secretName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		StringData: secretData,
		Type:       corev1.SecretTypeOpaque,
	}

	return secret, nil
}

// GetScanJob creates a job spec for scanning VM disk images
func GetScanJob(ctx context.Context, cl client.Client, scanInstance *v1.ScanInstance, secretName string) (*batchv1.Job, error) {
	scanInstName := scanInstance.Name
	targetName := scanInstance.Spec.BackupTarget.Name
	configMapName := GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, scanInstName)

	annotations := map[string]string{
		internal.Operation:             "scan",
		internal.ScanInstanceNameLabel: scanInstName,
	}

	// Fetch target to determine type and get credentials hash
	target := &v1.Target{}
	err := cl.Get(ctx, client.ObjectKey{Name: targetName, Namespace: internal.GetInstallNamespace()}, target)
	if err != nil {
		return nil, fmt.Errorf("failed to get target %s: %w", targetName, err)
	}

	credentialHash := target.GetAnnotations()[internal.TargetCredentialsHashAnnotationKey]

	// Find reporting target (cluster-wide, single target with annotation)
	reportingTargetName, err := getReportingTargetName(ctx, cl)
	if err != nil {
		return nil, fmt.Errorf("failed to get reporting target: %w", err)
	}

	var (
		scanCmd      string
		volumes      []corev1.Volume
		volumeMounts []corev1.VolumeMount
	)

	// Get PRODUCTION environment variable (default: "true")
	productionMode := os.Getenv("PRODUCTION")
	if productionMode == "" {
		productionMode = "true"
	}

	// Build scan engine command
	// The configmap will be mounted at /config/vm_artifacts_configuration.json
	// minimal_working.json is at /app/config/minimal_working.json
	scanEngineCmd := "python3 /app/main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json --campaign-name \"TestReport 9\" --enable-dashboard-report"

	// Add --production flag only if PRODUCTION env is "true"
	if strings.ToLower(productionMode) == "true" {
		scanEngineCmd = scanEngineCmd + " --production"
	}

	// Build database setup command
	// Runs after scan completes to populate PostgreSQL database from reports
	dbSetupCmd := "/usr/local/bin/soc-db-setup --dir dashboard_reports"

	// Build report upload command
	// Upload happens only if scan succeeds (&&)
	// Report uploader uses API-only access (no datastore mount needed)
	reportUploadCmd := buildReportUploadCommand(scanInstance, reportingTargetName)

	// Combine: scan → database setup → upload reports (all only on previous success)
	fullScanCmd := fmt.Sprintf("%s && %s && %s", scanEngineCmd, dbSetupCmd, reportUploadCmd)
	// fullScanCmd = "sleep 5"

	// For NFS targets: PVC is already mounted at /triliodata, no need for mount command
	// For ObjectStore targets: need to mount via s3fuse first
	if target.IsNFSTarget() {
		scanCmd = fullScanCmd
		nfsVolumes, nfsVolumeMounts := getNFSVolumes(target, credentialHash)
		volumes = append(volumes, nfsVolumes...)
		volumeMounts = append(volumeMounts, nfsVolumeMounts...)
	} else {
		// ObjectStore: mount first, then run scan engine with report upload
		mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
			internal.Py3Path,
			fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
			targetName)
		scanCmd = fmt.Sprintf("%s && %s", mountCmd, fullScanCmd)
	}

	// Add scan config volume (always needed)
	configVolume := corev1.Volume{
		Name: "scan-config",
		VolumeSource: corev1.VolumeSource{
			ConfigMap: &corev1.ConfigMapVolumeSource{
				LocalObjectReference: corev1.LocalObjectReference{
					Name: configMapName,
				},
			},
		},
	}
	volumes = append(volumes, configVolume)

	configVolumeMount := corev1.VolumeMount{
		Name:      "scan-config",
		MountPath: "/config/vm_artifacts_configuration.json",
		SubPath:   "vm_artifacts_configuration.json",
		ReadOnly:  true,
	}
	volumeMounts = append(volumeMounts, configVolumeMount)

	// Construct Redis URL from service name
	// Format: redis://redis-svc-<scaninstance-name>:<namespace>:6379
	redisSvcName := GetScanInstanceResourceName(internal.ScanInstanceRedisServicePrefix, scanInstName)
	redisURL := fmt.Sprintf("redis://%s.%s.svc.cluster.local:6379", redisSvcName, internal.GetInstallNamespace())

	// Create the scan container
	// For ObjectStore: Privileged access for s3fuse mounting
	// For NFS: No privileged access needed (PVC mount handles it)
	runAsUser := int64(0) // Run as root
	scanContainer := corev1.Container{
		Name:            "scanner",
		Image:           getScannerImage(), // Scanner image from env var RELATED_IMAGE_SCANNER
		Command:         []string{"/bin/bash", "-c"},
		Args:            []string{scanCmd},
		ImagePullPolicy: corev1.PullIfNotPresent,
		SecurityContext: &corev1.SecurityContext{
			RunAsUser: &runAsUser,
		},
		VolumeMounts: volumeMounts,
		// Environment variables loaded from scan secret via envFrom
		EnvFrom: []corev1.EnvFromSource{
			{
				SecretRef: &corev1.SecretEnvSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: secretName,
					},
				},
			},
		},
		Env: []corev1.EnvVar{
			// JOB_NAME and JOB_NAMESPACE for error annotation updates (future use)
			{
				Name: "JOB_NAME",
				ValueFrom: &corev1.EnvVarSource{
					FieldRef: &corev1.ObjectFieldSelector{
						FieldPath: "metadata.labels['job-name']",
					},
				},
			},
			{
				Name: "JOB_NAMESPACE",
				ValueFrom: &corev1.EnvVarSource{
					FieldRef: &corev1.ObjectFieldSelector{
						FieldPath: "metadata.namespace",
					},
				},
			},
			// PRODUCTION mode flag (default: "true")
			// When "false", --production flag is not included in scan command
			{
				Name:  "PRODUCTION",
				Value: productionMode,
			},
			// Redis URL for scan job to connect to Redis service
			{
				Name:  "REDIS_URL",
				Value: redisURL,
			},
		},
		Resources: corev1.ResourceRequirements{
			Requests: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("500m"),
				corev1.ResourceMemory: resource.MustParse("512Mi"),
			},
			Limits: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("2000m"),
				corev1.ResourceMemory: resource.MustParse("2Gi"),
			},
		},
	}

	// CRITICAL: Always add privileged security context for scan jobs
	// Privileged mode is required for:
	// 1. s3fuse mounting (ObjectStore targets)
	// 2. qemu-nbd for QCOW2 disk images (ALL targets)
	// 3. losetup for RAW disk images (ALL targets)
	// 4. modprobe for loading nbd/loop kernel modules (ALL targets)
	// Without privileged mode, loop devices won't be available and mounting will fail
	privileged := true
	scanContainer.SecurityContext.Privileged = &privileged
	scanContainer.SecurityContext.Capabilities = &corev1.Capabilities{
		Add: []corev1.Capability{"SYS_ADMIN"},
	}

	// Create the job
	jobName := GetScanInstanceResourceName(internal.ScanInstanceScanJobPrefix, scanInstName)
	backoffLimit := internal.ScanJobBackoffLimit // 3 retries for scan jobs

	// Get centralized labels and annotations
	labels := GetScanInstanceResourceLabels(scanInstName, "scan")
	annotations = internal.MergeMaps(annotations, GetScanInstanceResourceAnnotations(scanInstName))

	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:        jobName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		Spec: batchv1.JobSpec{
			BackoffLimit: &backoffLimit,
			// TTLSecondsAfterFinished is intentionally not set
			// Jobs are kept for debugging and will be cleaned up by janitor service
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: internal.ControllerServiceAccount,
					Containers:         []corev1.Container{scanContainer},
					Volumes:            volumes,
					RestartPolicy:      corev1.RestartPolicyNever,
				},
			},
		},
	}

	return job, nil
}

// getScannerImage returns the scanner image from environment variable or default
func getScannerImage() string {
	if img := os.Getenv(internal.RelatedImageScanner); img != "" {
		return img
	}
	return internal.DefaultScannerImage
}

// getReportingTargetName finds and returns the cluster-wide reporting target name
// Returns error if no reporting target is found or multiple are found
func getReportingTargetName(ctx context.Context, cl client.Client) (string, error) {
	// List all targets
	targets := &v1.TargetList{}
	if err := cl.List(ctx, targets); err != nil {
		return "", fmt.Errorf("failed to list targets: %w", err)
	}

	// Find targets with reporting annotation
	var reportingTargets []string
	for i := range targets.Items {
		target := &targets.Items[i]
		if target.IsReportingTarget() {
			reportingTargets = append(reportingTargets, target.Name)
		}
	}

	// Validate exactly one reporting target exists
	if len(reportingTargets) == 0 {
		return "", fmt.Errorf("no reporting target found (target with annotation trilio.io/reporting-target=true)")
	}
	if len(reportingTargets) > 1 {
		return "", fmt.Errorf("multiple reporting targets found: %v (expected exactly one)", reportingTargets)
	}

	return reportingTargets[0], nil
}

// GetReportPath constructs and returns the report path (object prefix) for a ScanInstance
// This is the S3 path where reports are uploaded
// Format: reports/<instance-id>/<backup-target-name>/<backupplan-uid>/<backup-uid>/<timestamp>
func GetReportPath(scanInstance *v1.ScanInstance) string {
	return fmt.Sprintf("reports/%s/%s/%s/%s/%s",
		scanInstance.GetInstanceID(),
		scanInstance.GetBackupTargetName(),
		scanInstance.GetBackupPlanUID(),
		scanInstance.GetBackupUID(),
		scanInstance.CreationTimestamp.Format("2006-01-02T15-04-05"),
	)
}

// buildReportUploadCommand constructs the report uploader CLI command
// Report uploader runs after scan completes successfully (via &&)
// Uses API-only access to reporting target (no datastore mount needed)
func buildReportUploadCommand(scanInstance *v1.ScanInstance, reportingTargetName string) string {
	// Get object prefix path from helper function
	objectPrefix := GetReportPath(scanInstance)

	// Build report uploader command
	// Format: /usr/local/bin/report-uploader \
	//           --upload-directory dashboard_reports/ \
	//           --object-prefix <prefix> \
	//           --target-name <reporting-target-name>
	return fmt.Sprintf(
		"/usr/local/bin/report-uploader --upload-directory dashboard_reports/ --object-prefix %s --target-name %s",
		objectPrefix,
		reportingTargetName,
	)
}

// GetJanitorJob creates a job spec for cleaning up ScanInstance resources
// This job is triggered by the controller after a ScanInstance completes scanning
func GetJanitorJob(scanInstance *v1.ScanInstance) (*batchv1.Job, error) {
	scanInstName := scanInstance.Name

	// Create the janitor container
	janitorContainer := corev1.Container{
		Name:            "janitor",
		Image:           internal.GetJanitorImage(),
		Command:         []string{"/app/janitor"},
		Args:            []string{fmt.Sprintf("--scan-instance=%s", scanInstName), "--status=Available"},
		ImagePullPolicy: corev1.PullAlways,
		Env: []corev1.EnvVar{
			{
				Name:  internal.InstallNamespaceEnvVar,
				Value: internal.GetInstallNamespace(),
			},
		},
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

	// Create the job
	jobName := GetScanInstanceResourceName(internal.ScanInstanceJanitorJobPrefix, scanInstName)
	backoffLimit := internal.JobBackoffLimit // 0 retries for janitor jobs

	// Get centralized labels and annotations
	labels := GetScanInstanceResourceLabels(scanInstName, "janitor")
	annotations := GetScanInstanceResourceAnnotations(scanInstName)

	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:        jobName,
			Namespace:   internal.GetInstallNamespace(),
			Labels:      labels,
			Annotations: annotations,
		},
		Spec: batchv1.JobSpec{
			BackoffLimit: &backoffLimit,
			TTLSecondsAfterFinished: func() *int32 {
				ttl := int32(300) // 5 minutes - janitor job can be cleaned up quickly
				return &ttl
			}(),
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: internal.ControllerServiceAccount,
					Containers:         []corev1.Container{janitorContainer},
					RestartPolicy:      corev1.RestartPolicyNever,
				},
			},
		},
	}

	return job, nil
}
