package scaninstance

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	"github.com/trilioData/threat-scanning-architecture/internal"
	"github.com/trilioData/threat-scanning-architecture/pkg/helpers"
)

// getRedisDeployment retrieves the Redis deployment for the given ScanInstance
func (r *Reconciler) getRedisDeployment(ctx context.Context, scanInstance *v1.ScanInstance) (*appsv1.Deployment, error) {
	deployName := helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisDeployPrefix, scanInstance.Name)
	deploy := &appsv1.Deployment{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      deployName,
	}, deploy); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, nil
		}
		return nil, err
	}
	return deploy, nil
}

// getRedisService retrieves the Redis service for the given ScanInstance
func (r *Reconciler) getRedisService(ctx context.Context, scanInstance *v1.ScanInstance) (*corev1.Service, error) {
	svcName := helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisServicePrefix, scanInstance.Name)
	svc := &corev1.Service{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: internal.GetInstallNamespace(),
		Name:      svcName,
	}, svc); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, nil
		}
		return nil, err
	}
	return svc, nil
}

// createRedisDeployment creates a Redis deployment for the given ScanInstance
func (r *Reconciler) createRedisDeployment(ctx context.Context, scanInstance *v1.ScanInstance) (*appsv1.Deployment, error) {
	deployName := helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisDeployPrefix, scanInstance.Name)
	replicas := int32(1)

	// Create labels matching scan job pattern
	labels := map[string]string{
		"app":                          "redis",
		"scan-instance":                scanInstance.Name,
		"app.kubernetes.io/name":       "redis",
		"app.kubernetes.io/component":  "cache",
		"app.kubernetes.io/managed-by": internal.ManagedBy,
		internal.ScanInstanceNameLabel: scanInstance.Name,
	}

	// Propagate labels from ScanInstance
	if scanInstance.Labels != nil {
		for k, v := range scanInstance.Labels {
			if _, exists := labels[k]; !exists {
				labels[k] = v
			}
		}
	}

	deploy := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      deployName,
			Namespace: internal.GetInstallNamespace(),
			Labels:    labels,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{
					"app":           "redis",
					"scan-instance": scanInstance.Name,
				},
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:  "redis",
							Image: internal.GetRedisImage(),
							Command: []string{
								"redis-server",
								"--maxmemory", "1gb",
								"--maxmemory-policy", "allkeys-lru",
								"--appendonly", "yes",
								"--appendfsync", "everysec",
							},
							Ports: []corev1.ContainerPort{
								{
									Name:          "redis",
									ContainerPort: 6379,
									Protocol:      corev1.ProtocolTCP,
								},
							},
							VolumeMounts: []corev1.VolumeMount{
								{
									Name:      "redis-data",
									MountPath: "/data",
								},
							},
							Resources: corev1.ResourceRequirements{
								Limits: corev1.ResourceList{
									corev1.ResourceMemory: resource.MustParse("1Gi"),
									corev1.ResourceCPU:    resource.MustParse("500m"),
								},
								Requests: corev1.ResourceList{
									corev1.ResourceMemory: resource.MustParse("512Mi"),
									corev1.ResourceCPU:    resource.MustParse("250m"),
								},
							},
							LivenessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									Exec: &corev1.ExecAction{
										Command: []string{"redis-cli", "ping"},
									},
								},
								InitialDelaySeconds: 5,
								PeriodSeconds:       5,
								TimeoutSeconds:      3,
								SuccessThreshold:    1,
								FailureThreshold:    3,
							},
							ReadinessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									Exec: &corev1.ExecAction{
										Command: []string{"redis-cli", "ping"},
									},
								},
								InitialDelaySeconds: 5,
								PeriodSeconds:       3,
								TimeoutSeconds:      2,
								SuccessThreshold:    1,
								FailureThreshold:    3,
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "redis-data",
							VolumeSource: corev1.VolumeSource{
								EmptyDir: &corev1.EmptyDirVolumeSource{},
							},
						},
					},
				},
			},
		},
	}

	// Set owner reference to ScanInstance
	if err := ctrl.SetControllerReference(scanInstance, deploy, r.Scheme); err != nil {
		return nil, fmt.Errorf("error setting owner reference on redis deployment: %w", err)
	}

	// Propagate annotations from ScanInstance
	if scanInstance.Annotations != nil {
		if deploy.Annotations == nil {
			deploy.Annotations = make(map[string]string)
		}
		for k, v := range scanInstance.Annotations {
			deploy.Annotations[k] = v
		}
	}

	// Check if deployment already exists (idempotency)
	existingDeploy := &appsv1.Deployment{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: deploy.Namespace,
		Name:      deploy.Name,
	}, existingDeploy); err == nil {
		// Deployment already exists, return it
		return existingDeploy, nil
	} else if !apierrors.IsNotFound(err) {
		return nil, fmt.Errorf("error checking for existing redis deployment: %w", err)
	}

	// Create the deployment
	if err := r.Client.Create(ctx, deploy); err != nil {
		// If deployment already exists, fetch and return it
		if apierrors.IsAlreadyExists(err) {
			if err := r.Client.Get(ctx, types.NamespacedName{
				Namespace: deploy.Namespace,
				Name:      deploy.Name,
			}, existingDeploy); err != nil {
				return nil, fmt.Errorf("error fetching existing redis deployment after AlreadyExists: %w", err)
			}
			return existingDeploy, nil
		}

		r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "RedisDeploymentCreateFailed",
			"Redis deployment creation failed for ScanInstance: %s", scanInstance.Name)
		return nil, fmt.Errorf("error creating redis deployment: %w", err)
	}

	r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "RedisDeploymentCreated",
		"Redis deployment %s created for ScanInstance: %s", deploy.Name, scanInstance.Name)

	return deploy, nil
}

// createRedisService creates a Redis service for the given ScanInstance
func (r *Reconciler) createRedisService(ctx context.Context, scanInstance *v1.ScanInstance) (*corev1.Service, error) {
	svcName := helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisServicePrefix, scanInstance.Name)

	// Create labels matching scan job pattern
	labels := map[string]string{
		"app":                          "redis",
		"scan-instance":                scanInstance.Name,
		"app.kubernetes.io/name":       "redis",
		"app.kubernetes.io/component":  "cache",
		"app.kubernetes.io/managed-by": internal.ManagedBy,
		internal.ScanInstanceNameLabel: scanInstance.Name,
	}

	// Propagate labels from ScanInstance
	if scanInstance.Labels != nil {
		for k, v := range scanInstance.Labels {
			if _, exists := labels[k]; !exists {
				labels[k] = v
			}
		}
	}

	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      svcName,
			Namespace: internal.GetInstallNamespace(),
			Labels:    labels,
		},
		Spec: corev1.ServiceSpec{
			Selector: map[string]string{
				"app":           "redis",
				"scan-instance": scanInstance.Name,
			},
			Ports: []corev1.ServicePort{
				{
					Name:       "redis",
					Port:       6379,
					TargetPort: intstr.FromInt(6379),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			Type: corev1.ServiceTypeClusterIP,
		},
	}

	// Set owner reference to ScanInstance
	if err := ctrl.SetControllerReference(scanInstance, svc, r.Scheme); err != nil {
		return nil, fmt.Errorf("error setting owner reference on redis service: %w", err)
	}

	// Propagate annotations from ScanInstance
	if scanInstance.Annotations != nil {
		if svc.Annotations == nil {
			svc.Annotations = make(map[string]string)
		}
		for k, v := range scanInstance.Annotations {
			svc.Annotations[k] = v
		}
	}

	// Check if service already exists (idempotency)
	existingSvc := &corev1.Service{}
	if err := r.Client.Get(ctx, types.NamespacedName{
		Namespace: svc.Namespace,
		Name:      svc.Name,
	}, existingSvc); err == nil {
		// Service already exists, return it
		return existingSvc, nil
	} else if !apierrors.IsNotFound(err) {
		return nil, fmt.Errorf("error checking for existing redis service: %w", err)
	}

	// Create the service
	if err := r.Client.Create(ctx, svc); err != nil {
		// If service already exists, fetch and return it
		if apierrors.IsAlreadyExists(err) {
			if err := r.Client.Get(ctx, types.NamespacedName{
				Namespace: svc.Namespace,
				Name:      svc.Name,
			}, existingSvc); err != nil {
				return nil, fmt.Errorf("error fetching existing redis service after AlreadyExists: %w", err)
			}
			return existingSvc, nil
		}

		r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "RedisServiceCreateFailed",
			"Redis service creation failed for ScanInstance: %s", scanInstance.Name)
		return nil, fmt.Errorf("error creating redis service: %w", err)
	}

	r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "RedisServiceCreated",
		"Redis service %s created for ScanInstance: %s", svc.Name, scanInstance.Name)

	return svc, nil
}

// isRedisDeploymentReady checks if the Redis deployment is ready
func (r *Reconciler) isRedisDeploymentReady(deploy *appsv1.Deployment) bool {
	// Check if deployment is available
	if deploy == nil {
		return false
	}

	// Check if at least one replica is ready
	if deploy.Status.ReadyReplicas < 1 {
		return false
	}

	// Check if deployment conditions indicate it's available
	for _, condition := range deploy.Status.Conditions {
		if condition.Type == appsv1.DeploymentAvailable && condition.Status == corev1.ConditionTrue {
			return true
		}
	}

	return false
}
