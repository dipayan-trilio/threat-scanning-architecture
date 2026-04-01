# Cleanup Logic Removal - Summary

## Change Overview
Removed automatic cleanup of ScanInstance resources after successful completion. Cleanup will now be handled by a separate Janitor service.

## What Was Removed

### From `processScanJobStatus()` (line ~586-605)
**Before:**
```go
// Cleanup jobs and configmap now that scan is complete
log.Info("Cleaning up jobs and configmap after scan completion")
cleanupErr := r.cleanupScanInstanceJobs(ctx, scanInstance)

var conditionReason string
if cleanupErr != nil {
    // Cleanup failed - log warning
    r.Log.Warn(fmt.Sprintf("cleanup failed for completed ScanInstance, orphaned resources will be handled by janitor: %v", cleanupErr))
    conditionReason = fmt.Sprintf("Scan completed successfully, but cleanup failed: %v. Orphaned resources will be cleaned by janitor.", cleanupErr)
} else {
    // Cleanup succeeded
    log.Info("Successfully cleaned up all resources for completed ScanInstance")
    conditionReason = "All scan phases completed, resources cleaned up successfully"
}
```

**After:**
```go
// Add Scanning/Completed condition
// Note: Cleanup of jobs, configmap, and Redis resources will be handled by janitor service
if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.Scanning, v1.Completed,
    "Scan completed successfully"); uErr != nil {
    return ctrl.Result{}, uErr
}
```

### Function Removed
**`cleanupScanInstanceJobs()`** - Entire function removed (~117 lines)
- This function was responsible for deleting:
  - PreScan Job
  - Scan Job
  - ConfigMap
  - Redis Deployment
  - Redis Service

## What Was Kept

### `cleanupScanInstanceResources()` - Still Active
This function is still called by the **finalizer** when ScanInstance is deleted:
- Deletes PreScan Job
- Deletes Scan Job
- Deletes ConfigMap
- Deletes Redis Deployment
- Deletes Redis Service

**Location**: Called from `reconcileScanInstanceDeleteFinalizer()` at line ~70

## Current Behavior

### On Successful Scan Completion
1. ✅ Scan Job completes successfully
2. ✅ `Scanning/Completed` condition added with reason: "Scan completed successfully"
3. ✅ Overall status set to `Completed`
4. ✅ **All resources remain** (no automatic cleanup)
   - PreScan Job
   - Scan Job
   - ConfigMap
   - Redis Deployment
   - Redis Service

### On ScanInstance Deletion
1. User deletes ScanInstance CR: `kubectl delete scaninstance <name>`
2. Finalizer triggers: `reconcileScanInstanceDeleteFinalizer()`
3. Calls: `cleanupScanInstanceResources()`
4. All child resources deleted
5. Finalizer removed
6. ScanInstance CR deleted

## Benefits of This Approach

### 1. **Debugging**
- All resources remain available for post-scan analysis
- Logs from jobs are preserved
- Redis data can be inspected
- ConfigMap shows what was scanned

### 2. **Janitor Service Flexibility**
- Centralized cleanup logic
- Can implement retention policies (e.g., keep completed scans for 24 hours)
- Can batch cleanup operations
- Can implement different cleanup strategies for different scan types
- Can handle cleanup failures gracefully with retries

### 3. **Audit Trail**
- Resources serve as evidence of what was scanned
- Timestamps on resources show scan duration
- Job logs provide detailed scan history

### 4. **Resource Recovery**
- If Janitor service is down, resources don't get orphaned during completion
- Can manually inspect/cleanup if needed
- Resources have OwnerReferences, so deleting ScanInstance cleans everything

## Janitor Service Requirements

The Janitor service should:

1. **List completed ScanInstances**
   ```go
   kubectl get scaninstances --field-selector status.status=Completed
   ```

2. **Apply retention policy**
   - Example: Delete ScanInstances completed > 24 hours ago
   - Example: Keep last N completed scans per backup

3. **Delete ScanInstance CR**
   - This triggers finalizer
   - Finalizer calls `cleanupScanInstanceResources()`
   - All child resources cleaned up automatically

4. **Handle failures gracefully**
   - Retry if deletion fails
   - Log cleanup operations
   - Expose metrics (completed scans cleaned, failed cleanups)

## Example Janitor Pseudocode

```go
func CleanupCompletedScans(ctx context.Context, retentionPeriod time.Duration) error {
    // List all completed ScanInstances
    scanInstances := &v1.ScanInstanceList{}
    err := client.List(ctx, scanInstances, &client.ListOptions{
        // Filter for completed status if possible
    })
    
    for _, si := range scanInstances.Items {
        if si.Status.Status != v1.ScanCompleted {
            continue
        }
        
        // Check if scan completed before retention period
        completedTime := getCompletionTime(si)
        if time.Since(completedTime) < retentionPeriod {
            continue
        }
        
        // Delete ScanInstance (finalizer will cleanup child resources)
        if err := client.Delete(ctx, &si); err != nil {
            log.Errorf("Failed to delete ScanInstance %s: %v", si.Name, err)
            continue
        }
        
        log.Infof("Cleaned up ScanInstance %s (completed at %v)", si.Name, completedTime)
    }
    
    return nil
}

func getCompletionTime(si v1.ScanInstance) time.Time {
    // Find Scanning/Completed condition timestamp
    for _, condition := range si.Status.Condition {
        if condition.Phase == v1.Scanning && condition.Status == v1.Completed {
            return condition.Timestamp.Time
        }
    }
    return time.Time{}
}
```

## Migration Notes

### For Existing Deployments
- No migration needed
- Existing ScanInstances will not be affected
- New ScanInstances will not auto-cleanup after completion
- Deploy Janitor service to handle cleanup

### For Testing
- Manually delete completed ScanInstances: `kubectl delete scaninstance <name>`
- Verify finalizer cleans up all resources
- Test Janitor service separately

## Files Modified
1. `controllers/scaninstance/controller_helper.go`
   - Removed `cleanupScanInstanceJobs()` function
   - Updated `processScanJobStatus()` to skip cleanup on success
   - Kept `cleanupScanInstanceResources()` for finalizer

2. `REDIS_DEPLOYMENT_IMPLEMENTATION.md`
   - Updated documentation to reflect new cleanup behavior
