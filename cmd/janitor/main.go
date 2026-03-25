package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/sirupsen/logrus"
	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"

	threatv1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	"github.com/trilioData/threat-scanning-architecture/internal"
	"github.com/trilioData/threat-scanning-architecture/pkg/helpers"
)

var (
	scheme = runtime.NewScheme()
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(threatv1.AddToScheme(scheme))
}

type Config struct {
	ScanInstanceName string
	Status           string
	DryRun           bool
	ThresholdMinutes int
}

func main() {
	var config Config

	flag.StringVar(&config.ScanInstanceName, "scan-instance", "", "Name of the ScanInstance to cleanup. If not provided, cleans up all ScanInstances matching the status criteria")
	flag.StringVar(&config.Status, "status", "Failed", "Status filter for cleanup: 'Failed' or 'Available' (Completed)")
	flag.BoolVar(&config.DryRun, "dry-run", false, "Dry run mode - only log what would be deleted without actually deleting")
	flag.IntVar(&config.ThresholdMinutes, "threshold-minutes", 4320, "Threshold in minutes for cleaning up failed ScanInstances. Only ScanInstances older than this threshold will have jobs/configmaps deleted. Default: 4320 (3 days)")
	flag.Parse()

	// Setup logger
	logger := logrus.New()
	logger.SetFormatter(&logrus.JSONFormatter{})
	logger.SetOutput(os.Stdout)
	logger.SetLevel(logrus.InfoLevel)

	log := logger.WithFields(logrus.Fields{
		"component":         "janitor",
		"scan-instance":     config.ScanInstanceName,
		"status":            config.Status,
		"dry-run":           config.DryRun,
		"threshold-minutes": config.ThresholdMinutes,
	})

	log.Info("Starting janitor service")

	// Validate status flag
	if config.Status != "Failed" && config.Status != "Available" {
		log.Fatalf("Invalid status flag: %s. Must be 'Failed' or 'Available'", config.Status)
	}

	// Validate threshold
	if config.ThresholdMinutes < 0 {
		log.Fatalf("Invalid threshold-minutes: %d. Must be >= 0", config.ThresholdMinutes)
	}

	// Create Kubernetes client
	k8sConfig := ctrl.GetConfigOrDie()
	k8sClient, err := client.New(k8sConfig, client.Options{Scheme: scheme})
	if err != nil {
		log.WithError(err).Fatal("Failed to create Kubernetes client")
	}

	ctx := context.Background()

	// Run cleanup
	if err := runCleanup(ctx, k8sClient, config, log); err != nil {
		log.WithError(err).Fatal("Cleanup failed")
	}

	log.Info("Janitor service completed successfully")
}

func runCleanup(ctx context.Context, k8sClient client.Client, config Config, log *logrus.Entry) error {
	var scanInstances []threatv1.ScanInstance

	// Log the install namespace being used
	installNs := internal.GetInstallNamespace()
	log.Infof("Using INSTALL_NAMESPACE: %s", installNs)

	if config.ScanInstanceName != "" {
		// Cleanup specific ScanInstance
		log.Infof("Fetching specific ScanInstance: %s", config.ScanInstanceName)
		si := &threatv1.ScanInstance{}
		if err := k8sClient.Get(ctx, types.NamespacedName{Name: config.ScanInstanceName}, si); err != nil {
			if apierrors.IsNotFound(err) {
				log.Warnf("ScanInstance not found: %s", config.ScanInstanceName)
				return nil
			}
			return fmt.Errorf("failed to get ScanInstance %s: %w", config.ScanInstanceName, err)
		}
		scanInstances = append(scanInstances, *si)
	} else {
		// List all ScanInstances matching the status filter
		log.Info("Listing all ScanInstances matching status criteria")
		siList := &threatv1.ScanInstanceList{}
		if err := k8sClient.List(ctx, siList); err != nil {
			return fmt.Errorf("failed to list ScanInstances: %w", err)
		}

		// Filter by status
		for _, si := range siList.Items {
			if config.Status == "Available" && si.Status.Status == threatv1.ScanCompleted {
				scanInstances = append(scanInstances, si)
			} else if config.Status == "Failed" && si.Status.Status == threatv1.ScanFailed {
				scanInstances = append(scanInstances, si)
			}
		}
	}

	if len(scanInstances) == 0 {
		log.Info("No ScanInstances found matching criteria")
		return nil
	}

	log.Infof("Found %d ScanInstance(s) to process", len(scanInstances))

	// Process each ScanInstance
	for _, si := range scanInstances {
		if err := processScanInstance(ctx, k8sClient, &si, config, log); err != nil {
			log.WithError(err).Errorf("Failed to process ScanInstance: %s", si.Name)
			// Continue processing other ScanInstances
		}
	}

	return nil
}

func processScanInstance(ctx context.Context, k8sClient client.Client, si *threatv1.ScanInstance, config Config, log *logrus.Entry) error {
	log = log.WithField("scaninstance", si.Name)
	log.Infof("Processing ScanInstance with status: %s", si.Status.Status)

	if config.Status == "Available" {
		// On-demand cleanup for completed ScanInstances
		// Delete: prescan job, redis deployment, service, scan configmap, scan job
		// Do NOT delete the ScanInstance itself
		return cleanupCompletedScanInstance(ctx, k8sClient, si, config.DryRun, log)
	} else if config.Status == "Failed" {
		// Periodic cleanup for failed ScanInstances
		return cleanupFailedScanInstance(ctx, k8sClient, si, config.DryRun, config.ThresholdMinutes, log)
	}

	return nil
}

// cleanupCompletedScanInstance handles cleanup for completed (Available) ScanInstances
// This is triggered on-demand by the controller after scanning completes
func cleanupCompletedScanInstance(ctx context.Context, k8sClient client.Client, si *threatv1.ScanInstance, dryRun bool, log *logrus.Entry) error {
	log.Info("Starting cleanup for completed ScanInstance")
	installNs := internal.GetInstallNamespace()

	// List of resources to delete
	resources := []struct {
		name     string
		resource client.Object
	}{
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstancePreScanPrefix, si.Name),
			resource: &batchv1.Job{},
		},
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceScanJobPrefix, si.Name),
			resource: &batchv1.Job{},
		},
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, si.Name),
			resource: &corev1.ConfigMap{},
		},
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisDeployPrefix, si.Name),
			resource: &appsv1.Deployment{},
		},
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisServicePrefix, si.Name),
			resource: &corev1.Service{},
		},
	}

	deletedCount := 0
	for _, res := range resources {
		key := types.NamespacedName{
			Namespace: installNs,
			Name:      res.name,
		}

		// Determine resource type for logging
		resourceType := ""
		switch res.resource.(type) {
		case *batchv1.Job:
			resourceType = "Job"
		case *corev1.ConfigMap:
			resourceType = "ConfigMap"
		case *appsv1.Deployment:
			resourceType = "Deployment"
		case *corev1.Service:
			resourceType = "Service"
		default:
			resourceType = fmt.Sprintf("%T", res.resource)
		}

		if err := k8sClient.Get(ctx, key, res.resource); err != nil {
			if apierrors.IsNotFound(err) {
				log.Debugf("Resource not found (already deleted): %s %s in namespace %s", resourceType, res.name, installNs)
				continue
			}
			log.WithError(err).Warnf("Error checking resource: %s %s in namespace %s", resourceType, res.name, installNs)
			continue
		}

		if dryRun {
			log.Infof("[DRY-RUN] Would delete: %s %s in namespace %s", resourceType, res.name, installNs)
			deletedCount++
			continue
		}

		// Use Background propagation for Jobs and Deployments to delete pods
		deleteOptions := &client.DeleteOptions{}
		if _, ok := res.resource.(*batchv1.Job); ok {
			backgroundPolicy := metav1.DeletePropagationBackground
			deleteOptions.PropagationPolicy = &backgroundPolicy
		} else if _, ok := res.resource.(*appsv1.Deployment); ok {
			backgroundPolicy := metav1.DeletePropagationBackground
			deleteOptions.PropagationPolicy = &backgroundPolicy
		}

		if err := k8sClient.Delete(ctx, res.resource, deleteOptions); err != nil && !apierrors.IsNotFound(err) {
			log.WithError(err).Errorf("Failed to delete resource: %s %s in namespace %s", resourceType, res.name, installNs)
			continue
		}

		log.Infof("Deleted: %s %s in namespace %s", resourceType, res.name, installNs)
		deletedCount++
	}

	log.Infof("Cleanup completed. Deleted %d resources", deletedCount)
	return nil
}

// cleanupFailedScanInstance handles cleanup for failed ScanInstances
// This runs periodically via CronJob
func cleanupFailedScanInstance(ctx context.Context, k8sClient client.Client, si *threatv1.ScanInstance, dryRun bool, thresholdMinutes int, log *logrus.Entry) error {
	log.Info("Starting cleanup for failed ScanInstance")
	installNs := internal.GetInstallNamespace()

	// First, always delete Redis deployment and service for failed ScanInstances
	redisResources := []struct {
		name     string
		resource client.Object
	}{
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisDeployPrefix, si.Name),
			resource: &appsv1.Deployment{},
		},
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceRedisServicePrefix, si.Name),
			resource: &corev1.Service{},
		},
	}

	redisDeletedCount := 0
	for _, res := range redisResources {
		key := types.NamespacedName{
			Namespace: installNs,
			Name:      res.name,
		}

		// Determine resource type for logging
		resourceType := ""
		switch res.resource.(type) {
		case *appsv1.Deployment:
			resourceType = "Deployment"
		case *corev1.Service:
			resourceType = "Service"
		default:
			resourceType = fmt.Sprintf("%T", res.resource)
		}

		if err := k8sClient.Get(ctx, key, res.resource); err != nil {
			if apierrors.IsNotFound(err) {
				log.Debugf("Redis resource not found: %s %s in namespace %s", resourceType, res.name, installNs)
				continue
			}
			log.WithError(err).Warnf("Error checking Redis resource: %s %s in namespace %s", resourceType, res.name, installNs)
			continue
		}

		if dryRun {
			log.Infof("[DRY-RUN] Would delete Redis resource: %s %s in namespace %s", resourceType, res.name, installNs)
			redisDeletedCount++
			continue
		}

		deleteOptions := &client.DeleteOptions{}
		if _, ok := res.resource.(*appsv1.Deployment); ok {
			backgroundPolicy := metav1.DeletePropagationBackground
			deleteOptions.PropagationPolicy = &backgroundPolicy
		}

		if err := k8sClient.Delete(ctx, res.resource, deleteOptions); err != nil && !apierrors.IsNotFound(err) {
			log.WithError(err).Errorf("Failed to delete Redis resource: %s %s in namespace %s", resourceType, res.name, installNs)
			continue
		}

		log.Infof("Deleted Redis resource: %s %s in namespace %s", resourceType, res.name, installNs)
		redisDeletedCount++
	}

	// Check if ScanInstance is older than threshold
	thresholdDuration := time.Duration(thresholdMinutes) * time.Minute
	thresholdTime := time.Now().Add(-thresholdDuration)
	creationTime := si.CreationTimestamp.Time

	if creationTime.After(thresholdTime) {
		log.Infof("ScanInstance is newer than threshold (created: %s, threshold: %d minutes). Skipping job/configmap cleanup for debugging purposes",
			creationTime.Format(time.RFC3339), thresholdMinutes)
		log.Infof("Cleanup completed. Deleted %d Redis resources", redisDeletedCount)
		return nil
	}

	// If older than threshold, delete prescan job, scan job, and scan configmap
	log.Infof("ScanInstance is older than threshold (created: %s, threshold: %d minutes). Proceeding with full cleanup",
		creationTime.Format(time.RFC3339), thresholdMinutes)

	oldResources := []struct {
		name     string
		resource client.Object
	}{
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstancePreScanPrefix, si.Name),
			resource: &batchv1.Job{},
		},
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceScanJobPrefix, si.Name),
			resource: &batchv1.Job{},
		},
		{
			name:     helpers.GetScanInstanceResourceName(internal.ScanInstanceScanConfigPrefix, si.Name),
			resource: &corev1.ConfigMap{},
		},
	}

	oldDeletedCount := 0
	for _, res := range oldResources {
		key := types.NamespacedName{
			Namespace: installNs,
			Name:      res.name,
		}

		// Determine resource type for logging
		resourceType := ""
		switch res.resource.(type) {
		case *batchv1.Job:
			resourceType = "Job"
		case *corev1.ConfigMap:
			resourceType = "ConfigMap"
		default:
			resourceType = fmt.Sprintf("%T", res.resource)
		}

		if err := k8sClient.Get(ctx, key, res.resource); err != nil {
			if apierrors.IsNotFound(err) {
				log.Debugf("Resource not found: %s %s in namespace %s", resourceType, res.name, installNs)
				continue
			}
			log.WithError(err).Warnf("Error checking resource: %s %s in namespace %s", resourceType, res.name, installNs)
			continue
		}

		if dryRun {
			log.Infof("[DRY-RUN] Would delete old resource: %s %s in namespace %s", resourceType, res.name, installNs)
			oldDeletedCount++
			continue
		}

		deleteOptions := &client.DeleteOptions{}
		if _, ok := res.resource.(*batchv1.Job); ok {
			backgroundPolicy := metav1.DeletePropagationBackground
			deleteOptions.PropagationPolicy = &backgroundPolicy
		}

		if err := k8sClient.Delete(ctx, res.resource, deleteOptions); err != nil && !apierrors.IsNotFound(err) {
			log.WithError(err).Errorf("Failed to delete old resource: %s %s in namespace %s", resourceType, res.name, installNs)
			continue
		}

		log.Infof("Deleted old resource: %s %s in namespace %s", resourceType, res.name, installNs)
		oldDeletedCount++
	}

	totalDeleted := redisDeletedCount + oldDeletedCount
	log.Infof("Cleanup completed. Deleted %d resources (%d Redis, %d old resources)", totalDeleted, redisDeletedCount, oldDeletedCount)
	return nil
}
