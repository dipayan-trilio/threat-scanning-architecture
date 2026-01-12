# Poller CronJob Implementation

## Overview

This document describes the implementation of automatic poller CronJob creation for validated targets that are not reporting targets.

## Changes Made

### 1. Environment Variable Configuration

#### Added Constants (`internal/constants.go`)

```go
// Environment variable names for container images
RelatedImageValidator = "RELATED_IMAGE_VALIDATOR"
RelatedImagePoller = "RELATED_IMAGE_POLLER"

// Default images if env vars not set
DefaultValidatorImage = "busybox:1.36"
DefaultPollerImage = "threat-scan-poller:latest"

// Poller configuration
TargetPollerCronJobPrefix = "poller"
TargetPollerOperation = "target-polling"
DefaultPollerSchedule = "0 */6 * * *"  // Every 6 hours

// New annotations
TargetNameAnnotationKey = "trilio.io/target-name"
```

### 2. Centralized Labels and Annotations

Created reusable functions for consistent labeling across all target resources:

#### `GetTargetResourceLabels()` - Centralized Label Management

```go
func GetTargetResourceLabels(target *v1.Target, component string) map[string]string {
    labels := internal.GetRecommendedLabels(component, internal.ManagedBy)
    labels[internal.ResourceCreatorKindLabelKey] = internal.TargetKind
    labels[internal.TargetNameAnnotationKey] = target.Name
    return labels
}
```

**Usage**: All target-related resources (validation jobs, poller cronjobs) now use this function, making it easy to add new labels globally.

#### `GetTargetResourceAnnotations()` - Centralized Annotation Management

```go
func GetTargetResourceAnnotations(target *v1.Target, credentialHash string) map[string]string {
    annotations := make(map[string]string)
    annotations[internal.TargetCredentialsHashAnnotationKey] = credentialHash
    annotations[internal.TargetNameAnnotationKey] = target.Name
    return annotations
}
```

### 3. Validator Image from Environment Variable

Updated validator image selection to read from `RELATED_IMAGE_VALIDATOR`:

```go
func getValidatorImage() string {
    if img := os.Getenv(internal.RelatedImageValidator); img != "" {
        return img
    }
    return internal.DefaultValidatorImage
}
```

**Benefits**:
- Easy to customize validator image via environment variable
- No code changes needed for different images
- Falls back to default if not set

### 4. Poller CronJob Creation

#### `GetTargetPollerCronJob()` - Creates Poller CronJob

**Features**:
- Generates random 5-character suffix for unique cronjob names
- Uses same volume mounting logic as validation jobs
- Configurable schedule via `POLLER_SCHEDULE` environment variable
- Image from `RELATED_IMAGE_POLLER` environment variable
- Uses centralized labels and annotations

**CronJob Naming**: `{target-name}-poller-{random-5-chars}`

Example: `nfs-backup-target-poller-x7k2m`

#### `reconcilePollerCronJob()` - Controller Logic

**Behavior**:
- Only creates cronjob when target status is `Available`
- Skips creation for reporting targets
- Checks if cronjob already exists (idempotent)
- Uses target name label for association

### 5. Controller Updates

#### Reconciliation Flow

```go
// After target becomes available
if target.Status.Status == v1.Available && !target.IsReportingTarget() {
    if err := r.reconcilePollerCronJob(ctx, target, currentSpecCredentialsHash); err != nil {
        // Handle error
    }
}
```

#### Cleanup on Target Deletion

Poller cronjobs are automatically deleted when target is deleted:

```go
func (r *Reconciler) cleanupTargetResources(ctx context.Context, target *v1.Target) error {
    // ... delete validation job ...
    
    // Delete poller cronjobs associated with this target
    cronJobs := &batchv1beta1.CronJobList{}
    if err := r.Client.List(ctx, cronJobs,
        client.InNamespace(internal.GetInstallNamespace()),
        client.MatchingLabels{internal.TargetNameAnnotationKey: target.Name}); err == nil {
        for i := range cronJobs.Items {
            // Delete each cronjob
        }
    }
}
```

#### CronJob Event Handler

Added watch for CronJob changes:

```go
func (r *Reconciler) cronjobHandler(ctx context.Context, obj client.Object) []reconcile.Request {
    targetName, exists := obj.GetLabels()[internal.TargetNameAnnotationKey]
    if !exists {
        return nil
    }
    return []reconcile.Request{
        {NamespacedName: types.NamespacedName{Name: targetName}},
    }
}
```

### 6. RBAC Updates

Added CronJob permissions to ClusterRole:

```yaml
- apiGroups:
  - batch
  resources:
  - cronjobs
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch
```

## Labels and Annotations

### Common Labels (Applied to all resources)

| Label | Value | Purpose |
|-------|-------|---------|
| `app.kubernetes.io/part-of` | `threat-scanning` | Part of threat scanning system |
| `app.kubernetes.io/managed-by` | `threat-scanning-controller` | Managed by controller |
| `app.kubernetes.io/component` | `target-validator` or `target-poller` | Component type |
| `trilio.io/creator-kind` | `Target` | Created by Target resource |
| `trilio.io/target-name` | `{target-name}` | Associated target name |

### Common Annotations

| Annotation | Value | Purpose |
|------------|-------|---------|
| `trilio.io/target-credentials-hash` | `{hash}` | Credential hash for deduplication |
| `trilio.io/target-name` | `{target-name}` | Associated target name |
| `trilio.io/operation` | `target-validation` or `target-polling` | Operation type |

## Usage Examples

### Example 1: Setting Custom Images

```bash
# Set environment variables in the controller deployment
export RELATED_IMAGE_VALIDATOR="my-registry/validator:v1.0.0"
export RELATED_IMAGE_POLLER="my-registry/poller:v1.0.0"
export POLLER_SCHEDULE="0 */4 * * *"  # Every 4 hours

# Run controller
./bin/manager
```

### Example 2: Target Lifecycle

```yaml
# 1. Create target
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: s3-backup-target
spec:
  type: ObjectStore
  vendor: AWS
  # ... credentials ...
```

**What happens**:
1. Controller validates target (creates validation job)
2. Validation job uses image from `RELATED_IMAGE_VALIDATOR`
3. Validation succeeds → Target status: `Available`
4. Controller creates poller cronjob: `s3-backup-target-poller-abc12`
5. Poller cronjob uses image from `RELATED_IMAGE_POLLER`
6. Poller runs on schedule (default: every 6 hours)

### Example 3: Reporting Target (No Poller)

```yaml
# Reporting target - no poller created
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  # ... credentials ...
```

**What happens**:
1. Controller validates target
2. Validation succeeds → Target status: `Available`
3. **No poller cronjob created** (reporting target excluded)

## Querying Resources

### Find all poller cronjobs for a target

```bash
kubectl get cronjobs -n threat-scanning-system \
  -l trilio.io/target-name=s3-backup-target
```

### Find all resources for a target

```bash
# Validation jobs
kubectl get jobs -n threat-scanning-system \
  -l trilio.io/target-name=s3-backup-target

# Poller cronjobs
kubectl get cronjobs -n threat-scanning-system \
  -l trilio.io/target-name=s3-backup-target

# All resources with target association
kubectl get all -n threat-scanning-system \
  -l trilio.io/target-name=s3-backup-target
```

### Check poller schedule

```bash
kubectl get cronjob -n threat-scanning-system \
  -l trilio.io/target-name=s3-backup-target \
  -o jsonpath='{.items[0].spec.schedule}'
```

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELATED_IMAGE_VALIDATOR` | `busybox:1.36` | Validator container image |
| `RELATED_IMAGE_POLLER` | `threat-scan-poller:latest` | Poller container image |
| `POLLER_SCHEDULE` | `0 */6 * * *` | Cron schedule for polling |

### Setting in Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-scanning-controller
spec:
  template:
    spec:
      containers:
      - name: manager
        image: threat-scanning-controller:latest
        env:
        - name: RELATED_IMAGE_VALIDATOR
          value: "my-registry/threat-scan-validator:v1.2.0"
        - name: RELATED_IMAGE_POLLER
          value: "my-registry/threat-scan-poller:v1.2.0"
        - name: POLLER_SCHEDULE
          value: "0 */4 * * *"  # Every 4 hours
```

## Adding New Labels/Annotations

To add a new label that applies to all target resources:

**1. Update `GetTargetResourceLabels()` in `pkg/helpers/job_helper.go`**:

```go
func GetTargetResourceLabels(target *v1.Target, component string) map[string]string {
    labels := internal.GetRecommendedLabels(component, internal.ManagedBy)
    labels[internal.ResourceCreatorKindLabelKey] = internal.TargetKind
    labels[internal.TargetNameAnnotationKey] = target.Name
    // Add your new label here
    labels["my-new-label"] = "my-value"
    return labels
}
```

**2. Rebuild and deploy**:

```bash
make build
make docker-build IMG=my-registry/threat-scanning-controller:latest
kubectl apply -k config/default
```

All validation jobs and poller cronjobs will automatically get the new label!

## Troubleshooting

### Poller CronJob Not Created

**Check 1**: Is target available?
```bash
kubectl get target my-target -o jsonpath='{.status.status}'
# Should output: Available
```

**Check 2**: Is it a reporting target?
```bash
kubectl get target my-target -o jsonpath='{.metadata.annotations}'
# Should NOT have "trilio.io/reporting-target": "true"
```

**Check 3**: Check controller logs
```bash
kubectl logs -n threat-scanning-system deployment/threat-scanning-controller
```

### Wrong Image Used

**Check environment variables**:
```bash
kubectl get deployment threat-scanning-controller -n threat-scanning-system \
  -o jsonpath='{.spec.template.spec.containers[0].env}'
```

### Poller Not Running on Schedule

**Check cronjob**:
```bash
kubectl get cronjob -n threat-scanning-system -l trilio.io/target-name=my-target
kubectl describe cronjob -n threat-scanning-system {cronjob-name}
```

**Check schedule**:
```bash
kubectl get cronjob {cronjob-name} -o jsonpath='{.spec.schedule}'
```

## Benefits of This Implementation

1. **Centralized Configuration**: Single function to manage labels/annotations
2. **Easy Customization**: Environment variables for images and schedules
3. **Automatic Cleanup**: Poller cronjobs deleted with target
4. **Idempotent**: Safe to reconcile multiple times
5. **Selective Polling**: Excludes reporting targets automatically
6. **Unique Naming**: Random suffix prevents conflicts
7. **Consistent Labeling**: Same labels across all resources
8. **Easy Extension**: Add new labels in one place

## Next Steps

To customize the poller logic:

1. Build your own poller image that implements the scanning logic
2. Set `RELATED_IMAGE_POLLER` to your image
3. Adjust `POLLER_SCHEDULE` as needed
4. Deploy the controller

The poller will automatically be created for all non-reporting targets!

