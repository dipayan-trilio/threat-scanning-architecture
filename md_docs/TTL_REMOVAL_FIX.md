# TTL Removal for ScanInstance Jobs - Critical Fix

## Problem

ScanInstance jobs were being automatically deleted by Kubernetes 5 minutes after completion due to `TTLSecondsAfterFinished: 300` setting. This made debugging impossible and didn't match the k8s-triliovault pattern.

## Root Cause

```go
// pkg/helpers/job_helper.go (OLD - INCORRECT)
func GetPreScanJob(...) (*batchv1.Job, error) {
    backoffLimit := internal.JobBackoffLimit
    ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished  // 300 seconds
    
    job := &batchv1.Job{
        Spec: batchv1.JobSpec{
            BackoffLimit:            &backoffLimit,
            TTLSecondsAfterFinished: &ttlSecondsAfterFinished,  // ❌ This was the problem
            Template: ...
        },
    }
}
```

**Result**: Kubernetes TTL controller automatically deleted jobs 5 minutes after they finished (success or failure), regardless of controller cleanup logic.

## Solution

Removed `TTLSecondsAfterFinished` from ScanInstance jobs to match k8s-triliovault pattern:

```go
// pkg/helpers/job_helper.go (NEW - CORRECT)
func GetPreScanJob(...) (*batchv1.Job, error) {
    backoffLimit := internal.JobBackoffLimit
    // Do NOT set TTLSecondsAfterFinished for ScanInstance jobs
    // Following TVK pattern: jobs are kept until manually cleaned up by the controller
    
    job := &batchv1.Job{
        Spec: batchv1.JobSpec{
            BackoffLimit: &backoffLimit,
            // TTLSecondsAfterFinished is intentionally not set ✅
            Template: ...
        },
    }
}
```

## Files Changed

1. **`pkg/helpers/job_helper.go`**
   - Removed `ttlSecondsAfterFinished` variable assignment (line 641)
   - Removed `TTLSecondsAfterFinished: &ttlSecondsAfterFinished` from job spec (line 656)
   - Added comments explaining why TTL is not set

2. **`controllers/scaninstance/controller.go`**
   - Removed immediate job deletion on failure
   - Removed immediate job deletion on timeout
   - Added cleanup on ScanInstance completion

3. **`controllers/scaninstance/controller_helper.go`**
   - Added `cleanupScanInstanceJobs()` function for manual cleanup

## k8s-triliovault Pattern

k8s-triliovault does NOT use `TTLSecondsAfterFinished` on any of its jobs:

```go
// k8s-triliovault/controllers/helpers/job_helper.go
func GetJob(ctx context.Context, cli client.Client, owner client.Object, ...) *batchv1.Job {
    job := &batchv1.Job{
        Spec: batchv1.JobSpec{
            // NO TTLSecondsAfterFinished set ✅
            ActiveDeadlineSeconds: &jobActiveDeadlineSeconds,  // Only this is set
            Template: ...
        },
    }
}
```

TVK only uses:
- `ActiveDeadlineSeconds`: Maximum runtime for a job (timeout)
- Manual cleanup via `CleanupJobs()` when CR reaches terminal state

## Behavior Comparison

### Before (with TTL)

```
1. PreScan job created with TTLSecondsAfterFinished: 300
2. Job fails
3. Controller tries to keep job for debugging
4. 5 minutes later: Kubernetes TTL controller deletes job ❌
5. Logs lost, debugging impossible ❌
```

### After (without TTL)

```
1. PreScan job created WITHOUT TTL
2. Job fails
3. Controller keeps job for debugging ✅
4. Hours/days later: Job still exists ✅
5. Logs available for debugging ✅
6. Job cleaned only when:
   - ScanInstance completes successfully (cleanupScanInstanceJobs), OR
   - ScanInstance is deleted (finalizer cleanup)
```

## Impact

| Aspect | Before (with TTL) | After (without TTL) |
|--------|-------------------|---------------------|
| **Job retention** | 5 minutes max | Until manual cleanup |
| **Debug capability** | None (logs lost) | Full (logs persist) |
| **Failed job inspection** | Impossible | Possible |
| **TVK consistency** | Inconsistent | Aligned |
| **Automatic cleanup** | Kubernetes TTL | Controller logic |

## Testing

### Verify TTL Not Set

```bash
# Create ScanInstance
kubectl apply -f scaninstance.yaml

# Check job spec
kubectl get job threat-scan-prescan-test -o yaml | grep ttlSecondsAfterFinished
# Expected: No output (field not set) ✅
```

### Verify Job Persists After Failure

```bash
# Wait for job to fail
kubectl wait --for=condition=failed job/threat-scan-prescan-test --timeout=120s

# Wait 6 minutes (past old TTL of 300 seconds)
sleep 360

# Verify job still exists
kubectl get job threat-scan-prescan-test
# Expected: Job found ✅

# Verify logs accessible
kubectl logs job/threat-scan-prescan-test
# Expected: Full logs available ✅
```

### Verify Manual Cleanup Works

```bash
# For successful scans: jobs cleaned when ScanInstance completes
kubectl get scaninstance test -o jsonpath='{.status.status}'
# If "Completed": jobs should be deleted

# For failed scans: jobs kept until CR deleted
kubectl delete scaninstance test
# Jobs deleted by finalizer
```

## Why This Matters

1. **Debugging**: Failed scans can be debugged by inspecting job logs
2. **Operations**: Can troubleshoot issues hours or days after they occur
3. **Consistency**: Matches TVK behavior users are familiar with
4. **Control**: Controller decides when to clean up, not Kubernetes

## Important Note: All Jobs Follow Same Pattern

**Updated**: Both ScanInstance jobs and Target validation jobs now follow the same pattern - no TTL, manual cleanup.

### Job Types and Cleanup

| Job Type | TTL | Success Cleanup | Failure Cleanup |
|----------|-----|-----------------|-----------------|
| **Target Validation** | None ❌ | Deleted when target `Available` | Kept for debugging |
| **PreScan** | None ❌ | Deleted when ScanInstance `Completed` | Kept for debugging |
| **Scan** (future) | None ❌ | Deleted when ScanInstance `Completed` | Kept for debugging |

### Why Both Need Manual Cleanup

1. **Failed validations need debugging**
   - Wrong credentials
   - Network connectivity issues
   - Permission problems
   - Target configuration errors

2. **Consistency across all job types**
   - Same pattern for all operations
   - Predictable behavior
   - Easier to understand and maintain

3. **Matches k8s-triliovault pattern**
   - TVK doesn't use TTL on any jobs
   - All cleanup is manual and controlled

## Rollback

If this change needs to be reverted (not recommended):

```go
// Restore TTL
ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished
job.Spec.TTLSecondsAfterFinished = &ttlSecondsAfterFinished
```

However, this would:
- Break debugging capability
- Diverge from TVK pattern
- Make failed scans impossible to troubleshoot

## Related Documentation

- `JOB_CLEANUP_PATTERN.md` - Full pattern explanation
- k8s-triliovault `controllers/helpers/job_helper.go` - Reference implementation
- k8s-triliovault `controllers/helpers/cleanup_helper.go` - Cleanup functions
