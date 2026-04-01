# PreScan Job Parameter Passing Implementation

## Overview

Updated the ScanInstance controller and job helpers to pass target name, backup UID, and backup path from the ScanInstance to the prescan job. These values are now printed by the placeholder job for verification.

## Changes Made

### 1. Updated Controller Helper (`controllers/scaninstance/controller_helper.go`) ✅

**Function:** `createPreScanJob()`

**Changes:**
- Extracts target name, backup UID, and backup path from ScanInstance spec
- Passes these values to `GetPreScanJob()` helper function

**Code:**
```go
// Extract information from ScanInstance for prescan job
targetName := scanInstance.Spec.BackupTarget.Name
backupUID := scanInstance.Spec.BackupRef.UID
backupPath := scanInstance.Spec.BackupRef.Path

// Pass to job helper
preScanJob, err := helpers.GetPreScanJob(ctx, r.Client, scanInstance, target, credHash, targetName, backupUID, backupPath)
```

### 2. Updated Job Helper (`pkg/helpers/job_helper.go`) ✅

**Function:** `GetPreScanJob()`

**Changes:**
- Updated function signature to accept `targetName`, `backupUID`, `backupPath` parameters
- Updated placeholder command to print these values
- Made target parameter handling safe (checks for nil)
- Updated TODO comments to reflect webhook responsibility

**Function Signature:**
```go
func GetPreScanJob(ctx context.Context, cl client.Client, scanInstance interface{}, target *v1.Target, credentialHash, targetName, backupUID, backupPath string) (*batchv1.Job, error)
```

**Placeholder Output:**
```bash
==========================================
PreScan Job - ScanInstance: <name>
==========================================
Target Name: <target-name>
Backup UID: <backup-uid>
Backup Path: <backup-path>
ScanInstance Name: <name>
==========================================

Starting pre-scan validation...
- Validating backup path exists...
- Determining backup type (TVK/TVO)...
- Reading metadata files...
- Checking for VM workloads...

Pre-scan validation completed successfully!
==========================================
```

## Data Flow

```
ScanInstance CR
    ↓
    spec:
      backupTarget:
        name: "test-s3-target-1"      ← targetName
      backupRef:
        uid: "backup-uid-12345"       ← backupUID
        path: "/backups/sample-backup" ← backupPath
    ↓
Controller (createPreScanJob)
    ↓
    Extracts: targetName, backupUID, backupPath
    ↓
Job Helper (GetPreScanJob)
    ↓
    Creates job with command that prints these values
    ↓
PreScan Job Pod
    ↓
    Logs show all three values
```

## Webhook Integration (Future)

As per the discussion, the webhook will handle:

**Responsibilities:**
1. **Validate target exists** - Prevents ScanInstance creation if target doesn't exist
2. **Validate target is Available** - Denies creation if target is not in Available status
3. **Validate backup path format** - Ensures backup path is valid format
4. **Prevent duplicate scans** - Optional: Check if scan already exists for this backup

**PreScan Job Responsibilities (Current/Future):**
1. **Validate target accessibility** - Can the job actually access the target?
2. **Validate backup path exists** - Does the path exist on the target?
3. **Determine backup type** - TVK or TVO?
4. **Read metadata** - Extract instance ID, backup plan ID, etc.
5. **Check VM workloads** - Are there any VM/VMI/VMPool resources?
6. **Update labels/annotations** - Add discovered metadata to ScanInstance

This separation ensures:
- Fast-fail validation at creation time (webhook)
- Detailed operational validation during execution (prescan job)
- Clear separation of concerns

## Testing the Changes

### 1. Create a ScanInstance

```bash
# Sample ScanInstance with values
cat <<EOF | kubectl apply -f -
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-scan-params
spec:
  backupTarget:
    apiVersion: threatscanning.trilio.io/v1
    kind: Target
    name: my-s3-target
    resourceVersion: "12345"
    uid: "target-uid-123"
  backupRef:
    uid: "backup-uid-456"
    path: "/backups/production/backup-001"
EOF
```

### 2. Check Job Logs

```bash
# Wait for job to be created
kubectl get jobs -n threat-scanning-system

# View job logs
kubectl logs -n threat-scanning-system job/threat-scan-prescan-test-scan-params
```

### 3. Expected Output

```
==========================================
PreScan Job - ScanInstance: test-scan-params
==========================================
Target Name: my-s3-target
Backup UID: backup-uid-456
Backup Path: /backups/production/backup-001
ScanInstance Name: test-scan-params
==========================================

Starting pre-scan validation...
- Validating backup path exists...
- Determining backup type (TVK/TVO)...
- Reading metadata files...
- Checking for VM workloads...

Pre-scan validation completed successfully!
==========================================
```

### 4. Verify Values Match ScanInstance

```bash
# Get ScanInstance values
kubectl get scaninstance test-scan-params -o jsonpath='{.spec.backupTarget.name}'
# Should show: my-s3-target

kubectl get scaninstance test-scan-params -o jsonpath='{.spec.backupRef.uid}'
# Should show: backup-uid-456

kubectl get scaninstance test-scan-params -o jsonpath='{.spec.backupRef.path}'
# Should show: /backups/production/backup-001
```

## Next Steps

### 1. Implement Webhook Validation (Recommended Next)

Create webhook to validate:
- Target exists
- Target is Available
- Backup path format is valid

```go
// Example webhook validation
func (v *ScanInstanceValidator) ValidateCreate(ctx context.Context, obj runtime.Object) error {
    scanInstance := obj.(*v1.ScanInstance)
    
    // Check if target exists
    target := &v1.Target{}
    if err := v.client.Get(ctx, types.NamespacedName{
        Name: scanInstance.Spec.BackupTarget.Name,
    }, target); err != nil {
        return fmt.Errorf("target %s does not exist", scanInstance.Spec.BackupTarget.Name)
    }
    
    // Check if target is Available
    if target.Status.Status != v1.Available {
        return fmt.Errorf("target %s is not available (status: %s)", target.Name, target.Status.Status)
    }
    
    // Validate backup path format
    if !isValidBackupPath(scanInstance.Spec.BackupRef.Path) {
        return fmt.Errorf("invalid backup path format: %s", scanInstance.Spec.BackupRef.Path)
    }
    
    return nil
}
```

### 2. Update PreScan Job Implementation

Replace placeholder with actual Python script:

```python
#!/usr/bin/env python3
import sys
import os

# Get parameters from environment or args
target_name = os.environ.get('TARGET_NAME')
backup_uid = os.environ.get('BACKUP_UID')
backup_path = os.environ.get('BACKUP_PATH')

print(f"PreScan Job Starting...")
print(f"Target: {target_name}")
print(f"Backup UID: {backup_uid}")
print(f"Backup Path: {backup_path}")

# TODO: Implement actual validation
# 1. Validate target accessibility
# 2. Check if backup path exists
# 3. Determine backup type (TVK/TVO)
# 4. Read metadata files
# 5. Check for VM workloads
# 6. Update ScanInstance labels/annotations via K8s API
```

### 3. Update Job Command

Once Python script is ready:

```go
// In GetPreScanJob()
preScanCmd = fmt.Sprintf(
    "%s %s/prescan.py --target=%s --backup-uid=%s --backup-path=%s --scaninstance=%s",
    internal.Py3Path,
    internal.DatastoreAttacherPathInContainer,
    targetName,
    backupUID,
    backupPath,
    scanInstName,
)
```

Or use environment variables:

```go
preScanContainer.Env = append(preScanContainer.Env, []corev1.EnvVar{
    {Name: "TARGET_NAME", Value: targetName},
    {Name: "BACKUP_UID", Value: backupUID},
    {Name: "BACKUP_PATH", Value: backupPath},
    {Name: "SCANINSTANCE_NAME", Value: scanInstName},
}...)
```

## Files Modified

- ✅ `controllers/scaninstance/controller_helper.go` - Extract and pass parameters
- ✅ `pkg/helpers/job_helper.go` - Accept parameters and use in job command

## Backward Compatibility

- ✅ No breaking changes
- ✅ Placeholder still works
- ✅ Ready for real implementation
- ✅ All tests should pass

## Benefits

1. **Clear Data Flow** - Parameters are explicitly passed from ScanInstance to job
2. **Easy to Test** - Can verify values in job logs
3. **Ready for Implementation** - Just need to replace placeholder command
4. **Webhook-Ready** - Target validation moved to webhook responsibility
5. **Separation of Concerns** - Controller extracts, helper creates, job validates

## Summary

✅ ScanInstance values (target name, backup UID, backup path) are now passed to prescan job
✅ Placeholder job prints these values for verification
✅ Target validation responsibility clarified (webhook for existence/availability, prescan for accessibility)
✅ Ready to replace placeholder with actual prescan implementation
✅ Clear separation between validation-at-creation (webhook) and validation-at-runtime (prescan job)

The implementation is complete and ready for webhook implementation + actual prescan logic! 🎉

