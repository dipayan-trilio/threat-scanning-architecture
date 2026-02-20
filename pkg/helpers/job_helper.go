package helpers

import (
	"context"
	"encoding/json"
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

	// Build poller command: mount datastore first, then poll
	mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
		internal.Py3Path,
		fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
		target.Name)

	pollCmd := fmt.Sprintf("target-poller --target-name=%s --group=threatscanning.trilio.io --version=v1",
		target.Name)

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

	// Build pre-scan command: mount datastore first, then run prescan
	// The prescan script will:
	// 1. Validate backup path exists (on mounted target)
	// 2. Determine backup type (TVK/TVO)
	// 3. Read metadata and detect VM workloads
	// 4. Update ScanInstance CR with labels, annotations, and status.type
	mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
		internal.Py3Path,
		fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
		targetName)

	prescanCmd := fmt.Sprintf("prescan --target-name=%s --backup-path=%s --backup-uid=%s --scaninstance-name=%s",
		targetName,
		backupPath,
		backupUID,
		scanInstName)

	// Mount first, then run prescan
	preScanCmd := fmt.Sprintf("%s && %s", mountCmd, prescanCmd)

	// Create the pre-scan container
	// PreScan job needs:
	// - Privileged access for mounting (s3fuse for ObjectStore, direct NFS mount)
	// - Access to Kubernetes API to fetch target CR and update ScanInstance
	// - ServiceAccount: threat-scanning-controller (has required RBAC)
	privileged := true
	preScanContainer := corev1.Container{
		Name:            "prescan",
		Image:           getValidatorImage(), // datastore-attacher image with prescan CLI
		Command:         []string{"/bin/bash", "-c"},
		Args:            []string{preScanCmd},
		ImagePullPolicy: corev1.PullAlways,
		SecurityContext: &corev1.SecurityContext{
			Privileged: &privileged,
			Capabilities: &corev1.Capabilities{
				Add: []corev1.Capability{"SYS_ADMIN"},
			},
		},
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
// The format matches the user's requirement: vm_artifacts with VM name as key, disk_image array, collection_time, priority, suspected_compromise
func GetScanConfigMapData(scanLocations []v1.ScanLocation) (map[string]string, error) {
	// Build the vm_artifacts structure
	vmArtifacts := make(map[string]interface{})

	for _, location := range scanLocations {
		for _, vm := range location.VMs {
			// Each VM has a name and list of PVC paths (disk images)
			vmArtifacts[vm.VMName] = map[string]interface{}{
				"disk_image":           vm.PVCPaths,
				"collection_time":      time.Now().UTC().Format(time.RFC3339),
				"priority":             "high",
				"suspected_compromise": true,
			}
		}
	}

	// Marshal to JSON
	data := map[string]interface{}{
		"vm_artifacts": vmArtifacts,
	}

	jsonData, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("failed to marshal scan config data: %w", err)
	}

	// Return as configmap data (single file named "config.json")
	return map[string]string{
		"config.json": string(jsonData),
	}, nil
}

// GetScanConfigMap creates a configmap for scan job configuration
func GetScanConfigMap(scanInstance *v1.ScanInstance) (*corev1.ConfigMap, error) {
	configMapName := GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, scanInstance.Name)

	// Generate configmap data from scanLocations
	data, err := GetScanConfigMapData(scanInstance.Status.ScanLocations)
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

// GetScanJob creates a job spec for scanning VM disk images
func GetScanJob(ctx context.Context, cl client.Client, scanInstance *v1.ScanInstance) (*batchv1.Job, error) {
	scanInstName := scanInstance.Name
	configMapName := GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, scanInstName)

	annotations := map[string]string{
		internal.Operation:             "scan",
		internal.ScanInstanceNameLabel: scanInstName,
	}

	// Build scan command: print config and sleep for 5 minutes (placeholder for actual scanning)
	// The configmap will be mounted at /config/config.json
	scanCmd := "cat /config/config.json && echo 'Scan job started' && sleep 60"

	// Create the scan container
	// For now, this is a placeholder that just prints the config and sleeps
	// TODO: Replace with actual scanning logic
	scanContainer := corev1.Container{
		Name:            "scanner",
		Image:           getScannerImage(), // Scanner image from env var RELATED_IMAGE_SCANNER
		Command:         []string{"/bin/bash", "-c"},
		Args:            []string{scanCmd},
		ImagePullPolicy: corev1.PullAlways,
		VolumeMounts: []corev1.VolumeMount{
			{
				Name:      "scan-config",
				MountPath: "/config",
				ReadOnly:  true,
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

	// Create the job
	jobName := GetScanInstanceResourceName(internal.ScanInstanceScanJobPrefix, scanInstName)
	backoffLimit := internal.JobBackoffLimit

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
			// Jobs are manually cleaned up by cleanupScanInstanceJobs when ScanInstance completes
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: internal.ControllerServiceAccount,
					Containers:         []corev1.Container{scanContainer},
					Volumes: []corev1.Volume{
						{
							Name: "scan-config",
							VolumeSource: corev1.VolumeSource{
								ConfigMap: &corev1.ConfigMapVolumeSource{
									LocalObjectReference: corev1.LocalObjectReference{
										Name: configMapName,
									},
								},
							},
						},
					},
					RestartPolicy: corev1.RestartPolicyNever,
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
