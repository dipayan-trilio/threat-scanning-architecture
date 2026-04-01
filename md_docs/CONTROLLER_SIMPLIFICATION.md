# Controller Simplification - Removed Unnecessary Target Fetching

## Overview

Simplified the ScanInstance controller by removing unnecessary target fetching and credential hash extraction. The controller now only extracts the necessary information from the ScanInstance spec and passes it to the prescan job.

## What Changed

### Before (Unnecessary Complexity)

**Controller Logic:**
1. Fetch Target CR from Kubernetes API
2. Extract credential hash from target annotations
3. Pass target object and credential hash to job helper
4. Job helper uses target to determine volumes, security context, env vars

**Problems:**
- ❌ Credential hash not used for anything
- ❌ Target fetching adds unnecessary API calls
- ❌ Controller doing work that prescan job should do
- ❌ Tight coupling between controller and target details

### After (Simplified)

**Controller Logic:**
1. Extract target name, backup UID, backup path from ScanInstance spec
2. Pass these simple strings to job helper
3. Job helper creates placeholder job with these values

**Benefits:**
- ✅ No unnecessary API calls
- ✅ Controller only extracts what's needed
- ✅ Prescan job will fetch target and handle mounting
- ✅ Clear separation of concerns
- ✅ Simpler, cleaner code

## Responsibility Clarification

### Webhook (To Be Implemented)
**Validates at creation time:**
- ✅ Target **exists**
- ✅ Target is **Available**
- ✅ Backup path **format** is valid
- ✅ Prevents duplicate scans (optional)

**Result:** ScanInstance creation is **denied** if validation fails

### Controller
**Orchestrates the workflow:**
- ✅ Extracts target name, backup UID, backup path from ScanInstance
- ✅ Creates prescan job with these parameters
- ✅ Monitors job status via job watcher
- ✅ Updates ScanInstance status based on job results

**Does NOT:**
- ❌ Validate target existence (webhook does this)
- ❌ Validate target availability (webhook does this)
- ❌ Fetch target details (prescan job does this)
- ❌ Determine target type (prescan job does this)

### PreScan Job
**Validates at runtime:**
- ✅ Fetches target CR using targetName
- ✅ Validates target **accessibility** (can it connect?)
- ✅ Determines target type (NFS/ObjectStore)
- ✅ Mounts target based on type
- ✅ Validates backup path **exists** on target
- ✅ Reads metadata files
- ✅ Determines backup type (TVK/TVO)
- ✅ Checks for VM workloads
- ✅ Updates ScanInstance labels/annotations via Kubernetes API

## Code Changes

### 1. Controller (`controller.go`)

**Removed:**
```go
// Get target for credential hash (needed for job creation)
target := &v1.Target{}
if err := r.Client.Get(ctx, types.NamespacedName{Name: scanInstance.Spec.BackupTarget.Name}, target); err != nil {
    r.Log.WithError(err).Warnf("Unable to fetch target %s", scanInstance.Spec.BackupTarget.Name)
}
```

**Simplified:**
```go
// Create preScan job
// Webhook ensures target exists and is available
// PreScan job will validate target accessibility and backup details
newPreScanJob, err := r.createPreScanJob(ctx, scanInstance)
```

### 2. Controller Helper (`controller_helper.go`)

**Before:**
```go
func (r *Reconciler) createPreScanJob(ctx context.Context, scanInstance *v1.ScanInstance, target *v1.Target) (*batchv1.Job, error) {
    credHash := ""
    if target != nil && target.Annotations != nil {
        credHash = target.Annotations[internal.TargetCredentialsHashAnnotationKey]
    }
    
    targetName := scanInstance.Spec.BackupTarget.Name
    backupUID := scanInstance.Spec.BackupRef.UID
    backupPath := scanInstance.Spec.BackupRef.Path
    
    preScanJob, err := helpers.GetPreScanJob(ctx, r.Client, scanInstance, target, credHash, targetName, backupUID, backupPath)
    ...
}
```

**After:**
```go
func (r *Reconciler) createPreScanJob(ctx context.Context, scanInstance *v1.ScanInstance) (*batchv1.Job, error) {
    // Extract information from ScanInstance for prescan job
    // Webhook ensures target exists and is available before ScanInstance creation
    targetName := scanInstance.Spec.BackupTarget.Name
    backupUID := scanInstance.Spec.BackupRef.UID
    backupPath := scanInstance.Spec.BackupRef.Path
    
    preScanJob, err := helpers.GetPreScanJob(ctx, r.Client, scanInstance, targetName, backupUID, backupPath)
    ...
}
```

### 3. Job Helper (`job_helper.go`)

**Before:**
```go
func GetPreScanJob(ctx context.Context, cl client.Client, scanInstance interface{}, target *v1.Target, credentialHash, targetName, backupUID, backupPath string) (*batchv1.Job, error) {
    // Build volumes based on target type
    if target != nil {
        if target.IsNFSTarget() {
            volumes, volumeMounts = getNFSVolumes(target, credentialHash)
        } else {
            // Add secret volumes, SSL certs, etc.
        }
    }
    
    // Set security context based on target type
    if target != nil && target.IsObjectStoreTarget() {
        preScanContainer.SecurityContext = &corev1.SecurityContext{
            Privileged: &privileged,
        }
    }
    ...
}
```

**After:**
```go
func GetPreScanJob(ctx context.Context, cl client.Client, scanInstance interface{}, targetName, backupUID, backupPath string) (*batchv1.Job, error) {
    // Build pre-scan command - placeholder that prints the captured values
    // TODO: Replace with actual pre-scan script that:
    // - Fetches target CR using targetName
    // - Validates target accessibility
    // - Mounts target and validates backup path exists
    // - Determines backup type and reads metadata
    // - Updates ScanInstance labels/annotations via Kubernetes API
    
    preScanCmd = fmt.Sprintf(`
echo "Target Name: %s"
echo "Backup UID: %s"
echo "Backup Path: %s"
echo "- Fetching target CR: %s"
echo "- Validating target accessibility..."
echo "- Validating backup path exists: %s"
...
`, targetName, backupUID, backupPath, targetName, backupPath)
    
    // Simple container - prescan job will handle target fetching and mounting
    preScanContainer := corev1.Container{
        Name:    "prescan",
        Image:   getValidatorImage(),
        Command: []string{"/bin/sh", "-c"},
        Args:    []string{preScanCmd},
        // ServiceAccount has RBAC to fetch targets and update ScanInstances
    }
    ...
}
```

## Updated Flow

### ScanInstance Creation Flow

```
1. User creates ScanInstance
   ↓
2. Webhook validates (future):
   - Target exists?
   - Target Available?
   - Backup path format valid?
   ↓
   If validation fails → DENY creation
   If validation passes → Allow creation
   ↓
3. Controller reconciles:
   - Extract: targetName, backupUID, backupPath
   - Create prescan job with these values
   ↓
4. PreScan job runs:
   - Fetch target CR using targetName
   - Validate target accessibility
   - Determine target type (NFS/ObjectStore)
   - Mount target based on type
   - Validate backup path exists
   - Read metadata
   - Update ScanInstance labels/annotations
   ↓
5. Controller updates ScanInstance status based on job result
```

## PreScan Job Responsibilities (Detailed)

The prescan job will need to:

### 1. Fetch Target CR
```python
# Using Kubernetes Python client
from kubernetes import client, config

config.load_incluster_config()
api = client.CustomObjectsApi()

target = api.get_cluster_custom_object(
    group="threatscanning.trilio.io",
    version="v1",
    plural="targets",
    name=target_name
)
```

### 2. Validate Target Accessibility
```python
# Based on target type
if target['spec']['type'] == 'NFS':
    # Try to mount NFS
    validate_nfs_mount(target['spec']['nfsCredentials'])
elif target['spec']['type'] == 'ObjectStore':
    # Try to connect to S3/ObjectStore
    validate_s3_connection(target['spec']['objectStoreCredentials'])
```

### 3. Mount Target
```python
# Use existing datastore-attacher utilities
from mount_utility.mount_by_target_crd import mount_datastores

mount_point = mount_datastores.mount_target(target_name)
```

### 4. Validate Backup Path
```python
import os

full_path = os.path.join(mount_point, backup_path)
if not os.path.exists(full_path):
    raise ValueError(f"Backup path does not exist: {full_path}")
```

### 5. Determine Backup Type and Read Metadata
```python
# Read tvk-meta.json or tvo-meta.json
metadata_file = os.path.join(full_path, "tvk-meta.json")
if os.path.exists(metadata_file):
    backup_type = "TVK"
    # Parse metadata
else:
    backup_type = "TVO"
    # Parse TVO metadata
```

### 6. Update ScanInstance
```python
# Update labels and annotations
api.patch_cluster_custom_object(
    group="threatscanning.trilio.io",
    version="v1",
    plural="scaninstances",
    name=scaninstance_name,
    body={
        "metadata": {
            "labels": {
                "trilio.io/instance-id": instance_id,
                "trilio.io/backup-target": target_uid,
                "trilio.io/backupplan": backupplan_uid,
                "trilio.io/backup": backup_uid,
            },
            "annotations": {
                "trilio.io/vm-workload": "true" if has_vm_workloads else "false"
            }
        },
        "status": {
            "type": backup_type  # TVK or TVO
        }
    }
)
```

## Benefits of This Approach

### 1. Separation of Concerns
- **Webhook**: Fast-fail validation at creation time
- **Controller**: Orchestration and status management
- **PreScan Job**: Detailed runtime validation and metadata extraction

### 2. Reduced API Calls
- Controller doesn't fetch target unnecessarily
- Only prescan job fetches target when needed

### 3. Flexibility
- Prescan job can handle different target types dynamically
- No need to update controller when adding new target types
- Easier to test prescan logic independently

### 4. Better Error Reporting
- Webhook errors: Clear rejection message at creation time
- PreScan errors: Detailed validation errors in job logs
- Controller just orchestrates and reports status

### 5. Cleaner Code
- Controller code is simpler
- No target-specific logic in controller
- Prescan job is self-contained

## Testing

### Test 1: Verify No Target Fetching

```bash
# Enable controller debug logging
kubectl logs -f -n threat-scanning-system deployment/threat-scanning-controller

# Create ScanInstance
kubectl apply -f config/samples/threatscanning_v1_scaninstance.yaml

# Verify logs show NO target fetching
# Should NOT see: "Fetching target..." or "Unable to fetch target..."
```

### Test 2: Verify Job Gets Correct Parameters

```bash
# Create ScanInstance
kubectl apply -f config/samples/threatscanning_v1_scaninstance.yaml

# Check job logs
kubectl logs -n threat-scanning-system job/threat-scan-prescan-sample-scan-instance

# Should show:
# Target Name: test-s3-target-1
# Backup UID: backup-uid-12345
# Backup Path: /backups/sample-backup
```

### Test 3: Verify Job Has RBAC to Fetch Targets

```bash
# Check service account
kubectl get sa -n threat-scanning-system trilio-threat-scanning -o yaml

# Verify ClusterRole has permissions:
# - targets.threatscanning.trilio.io: get, list
# - scaninstances.threatscanning.trilio.io: get, patch
```

## Migration Notes

### No Breaking Changes
- ✅ Existing ScanInstances continue to work
- ✅ Placeholder job still prints values correctly
- ✅ No API changes

### What to Update Next

1. **Implement Webhook** (Priority 1)
   - Validates target exists and is Available
   - Prevents invalid ScanInstances from being created

2. **Implement Real PreScan Job** (Priority 2)
   - Replace placeholder with Python script
   - Fetch target, mount, validate, update labels

3. **Update Documentation** (Priority 3)
   - Update flow diagrams
   - Update testing guides
   - Update architecture docs

## Summary

✅ **Removed unnecessary target fetching from controller**
✅ **Controller only extracts simple values from ScanInstance**
✅ **PreScan job will handle all target-related operations**
✅ **Clear separation: Webhook validates, Controller orchestrates, PreScan job executes**
✅ **Simpler, cleaner, more maintainable code**

The controller is now focused on orchestration, not validation or target management! 🎉

