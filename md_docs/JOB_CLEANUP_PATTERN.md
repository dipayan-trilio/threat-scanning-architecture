# Job Cleanup Pattern - Aligned with k8s-triliovault

## Overview

The ScanInstance controller now follows the same job cleanup pattern as k8s-triliovault's Backup/Restore controllers. Jobs are retained until the entire scanning process completes successfully, rather than being deleted immediately after each job finishes.

## Pattern Comparison

### Previous Pattern (Immediate Deletion)
```
PreScan Job Created → PreScan Job Completes → Job Deleted Immediately ❌
PreScan Job Created → PreScan Job Fails → Job Deleted Immediately ❌
PreScan Job Created → PreScan Job Timeout → Job Deleted Immediately ❌
```

### New Pattern (k8s-triliovault Aligned) ✅
```
PreScan Job Created → PreScan Job Completes → Job Kept → ScanInstance Completes → All Jobs Deleted
PreScan Job Created → PreScan Job Fails → Job Kept for Debugging → ScanInstance Deleted → Jobs Cleaned
```

## Critical Change: Removed TTL

**IMPORTANT**: The most critical change is removing `TTLSecondsAfterFinished` from ScanInstance jobs.

### Before (with TTL):
```go
ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished // 300 seconds
job.Spec.TTLSecondsAfterFinished = &ttlSecondsAfterFinished
```

Result: Kubernetes automatically deleted jobs 5 minutes after completion, making debugging impossible.

### After (no TTL):
```go
// TTLSecondsAfterFinished is intentionally not set
// Jobs are manually cleaned up by cleanupScanInstanceJobs when ScanInstance completes
job.Spec.TTLSecondsAfterFinished = nil // Not set at all
```

Result: Jobs remain until manually cleaned by the controller, allowing full debugging capability.

### Why This Matters

| Scenario | With TTL (old) | Without TTL (new) |
|----------|----------------|-------------------|
| **Successful job** | Deleted after 5 min ❌ | Kept until ScanInstance completes ✅ |
| **Failed job** | Deleted after 5 min ❌ | Kept for debugging ✅ |
| **Logs accessible** | Only 5 minutes ❌ | Until manual cleanup ✅ |
| **Debug failed scans** | Impossible ❌ | Full logs available ✅ |

## Implementation Details

### 1. Job Retention Strategy

#### Successful Jobs
- **Kept during scan process**: All successful jobs (PreScan, Scan, etc.) are retained while ScanInstance is in progress
- **Cleaned on completion**: When ScanInstance reaches `Completed` status, all jobs are deleted in batch
- **Use case**: Allows inspection of job logs during later phases if issues arise

#### Failed Jobs
- **Always kept**: Failed or timeout jobs are never deleted during reconciliation
- **Kept for debugging**: Provides ability to inspect logs and troubleshoot failures
- **Cleaned on CR deletion**: Only cleaned up when ScanInstance itself is deleted via finalizer

### 2. Code Changes

#### Controller Main Logic (`controller.go`)

**Added Cleanup on Completion:**
```go
// Cleanup jobs if ScanInstance has completed successfully
// Following TVK pattern: jobs are cleaned up only after the entire process completes
if scanInstance.Status.Status == v1.ScanCompleted {
    log.Info("ScanInstance completed, cleaning up jobs")
    if err := r.cleanupScanInstanceJobs(ctx, scanInstance); err != nil {
        // Log error but don't fail reconciliation - cleanup is best-effort
        r.Log.WithError(err).Error("error while cleaning up scan instance jobs")
    }
    return ctrl.Result{}, nil
}
```

**Removed Immediate Deletion on Failure:**
```go
case v1.Failed:
    // ... update status ...
    
    // Keep failed job for debugging - it will be cleaned up when ScanInstance is deleted
    // Following TVK pattern: failed jobs are kept for log inspection
    log.Debug("PreScan job failed, keeping job for debugging")
```

**Removed Deletion on Timeout:**
```go
if helpers.IsJobPendingDeadlineExceeded(preScanJob) {
    // ... update status ...
    
    // Keep stuck job for debugging - it will be cleaned up when ScanInstance is deleted
    // Following TVK pattern: failed/stuck jobs are kept for log inspection
    log.Debug("PreScan job exceeded pending deadline, keeping job for debugging")
    return ctrl.Result{}, nil
}
```

#### Helper Functions (`controller_helper.go`)

**Added New Cleanup Function:**
```go
// cleanupScanInstanceJobs cleans up all jobs associated with a completed ScanInstance
// Following TVK pattern: jobs are deleted only when the main CR reaches terminal Completed state
// Failed jobs are not cleaned up here - they are kept for debugging and cleaned during CR deletion
func (r *Reconciler) cleanupScanInstanceJobs(ctx context.Context, scanInstance *v1.ScanInstance) error {
    // Uses DeletePropagationForeground like TVK's CleanupJobs function
    // Deletes PreScan job (and later: Scan job, PostScan job)
    // Best-effort cleanup - logs errors but doesn't fail reconciliation
}
```

**Existing Finalizer Cleanup (unchanged):**
```go
func (r *Reconciler) cleanupScanInstanceResources(ctx context.Context, scanInstance *v1.ScanInstance) error {
    // Still handles cleanup when ScanInstance is deleted
    // Uses DeletePropagationBackground
    // Cleans up ALL jobs (successful and failed)
}
```

#### Job Creation (`pkg/helpers/job_helper.go`)

**Critical Change - Removed TTL:**
```go
func GetPreScanJob(...) (*batchv1.Job, error) {
    backoffLimit := internal.JobBackoffLimit
    // Do NOT set TTLSecondsAfterFinished for ScanInstance jobs
    // Following TVK pattern: jobs are kept until manually cleaned up by the controller
    
    job := &batchv1.Job{
        Spec: batchv1.JobSpec{
            BackoffLimit: &backoffLimit,
            // TTLSecondsAfterFinished is intentionally not set
            // Jobs are manually cleaned up by cleanupScanInstanceJobs when ScanInstance completes
            Template: ...
        },
    }
}
```

**Before (incorrect):**
- Used `TTLSecondsAfterFinished: 300`
- Kubernetes auto-deleted jobs after 5 minutes
- Logs lost, debugging impossible

**After (correct - matches TVK):**
- No TTL set
- Jobs remain until controller cleans them
- Full debugging capability preserved

### 3. Deletion Propagation Policies

Following k8s-triliovault patterns:

| Function | Propagation Policy | Use Case |
|----------|-------------------|----------|
| `cleanupScanInstanceJobs` | `Foreground` | Ensures pods are deleted before job (matching TVK's `CleanupJobs`) |
| `cleanupScanInstanceResources` | `Background` | Faster cleanup on CR deletion (finalizer) |

## Benefits

### 1. **Debugging Support**
- Failed jobs remain available for log inspection
- Can debug issues even after they occur
- Consistent with TVK user expectations

### 2. **Observability**
- All job logs available during entire scan lifecycle
- Can correlate issues across multiple phases
- Better troubleshooting experience

### 3. **Consistency with TVK**
- Same pattern as Backup/Restore controllers
- Familiar behavior for TVK developers
- Unified job management approach

### 4. **Clean Batch Operations**
- Single cleanup operation when scan completes
- Reduces API calls during reconciliation
- Simpler state management

## Lifecycle Examples

### Successful Scan Flow

```
1. ScanInstance created (Status: Queued)
2. PreScan job created
3. PreScan job completes ✅ (Job kept)
   └─ ScanInstance condition: PreScan/Completed
   └─ ScanInstance status: InProgress
4. Scan job created (future)
5. Scan job completes ✅ (Job kept)
   └─ ScanInstance condition: Scanning/Completed
   └─ ScanInstance status: InProgress
6. ScanInstance status → Completed
   └─ cleanupScanInstanceJobs() called
   └─ PreScan job deleted 🗑️
   └─ Scan job deleted 🗑️
7. User deletes ScanInstance
   └─ Finalizer runs (no-op, jobs already cleaned)
```

### Failed Scan Flow

```
1. ScanInstance created (Status: Queued)
2. PreScan job created
3. PreScan job fails ❌ (Job kept for debugging)
   └─ ScanInstance condition: PreScan/Failed
   └─ ScanInstance status: Failed
4. User inspects PreScan job logs for debugging
5. User deletes ScanInstance
   └─ Finalizer runs
   └─ cleanupScanInstanceResources() called
   └─ PreScan job deleted 🗑️ (cleanup on deletion)
```

### Timeout Flow

```
1. ScanInstance created (Status: Queued)
2. PreScan job created
3. PreScan job stuck in Pending
4. Timeout detected (IsJobPendingDeadlineExceeded)
   └─ ScanInstance condition: PreScan/Failed
   └─ ScanInstance status: Failed
   └─ Job kept for debugging ✅
5. User inspects why job couldn't schedule
6. User deletes ScanInstance
   └─ Finalizer runs
   └─ Job deleted 🗑️
```

## k8s-triliovault Reference

This implementation follows these TVK patterns:

### No TTL in TVK Jobs

**Important**: k8s-triliovault does NOT use `TTLSecondsAfterFinished` on any of its jobs:

```go
// controllers/helpers/job_helper.go in k8s-triliovault
func GetJob(ctx context.Context, cli client.Client, owner client.Object, ...) *batchv1.Job {
    job := &batchv1.Job{
        Spec: batchv1.JobSpec{
            // NO TTLSecondsAfterFinished set
            ActiveDeadlineSeconds: &jobActiveDeadlineSeconds, // Only this is set
            Template: ...
        },
    }
}
```

TVK only sets `ActiveDeadlineSeconds` (job runtime limit), never `TTLSecondsAfterFinished` (auto-cleanup after finish).

### Restore Controller
```go
// controllers/restore/controller.go
if restore.Status.Status == v1.Completed {
    _, _ = controllerHelpers.CleanupJobs(ctx, r.Client, childJobs.Items)
    return ctrl.Result{}, nil
}
```

### Backup Controller
```go
// controllers/backup/controller.go
if backup.Status.Status == v1.Available || backup.Status.Status == v1.Canceling || backup.Status.Status == v1.Canceled {
    cleanOpts := controllerHelpers.CleanupOptions{
        Jobs: true, PVCs: true,
        VS: vs,
    }
    if cErr := r.cleanupResources(apiContext, &backup, originalBackup, backupPlan, target, cleanOpts, restartCleanup); cErr != nil {
        // ...
    }
}
```

### CleanupJobs Function
```go
// controllers/helpers/cleanup_helper.go
func CleanupJobs(ctx context.Context, cli client.Client, jobs []batchv1.Job) (cleanCount int, err error) {
    propagationPolicy := metav1.DeletePropagationForeground
    for index := range jobs {
        job := jobs[index]
        jErr := cli.Delete(ctx, &job, &client.DeleteOptions{PropagationPolicy: &propagationPolicy})
        // ...
    }
}
```

## Testing Considerations

When testing, verify:

1. **Successful completion**: Jobs are deleted when ScanInstance reaches `Completed`
2. **Failed jobs retained**: Failed/timeout jobs remain after failure (indefinitely, no TTL)
3. **Finalizer cleanup**: All jobs deleted when ScanInstance is deleted
4. **Idempotency**: Cleanup can be called multiple times safely
5. **Log access**: Failed job logs accessible for debugging
6. **No TTL deletion**: Verify jobs are NOT deleted by Kubernetes TTL controller after 5 minutes

### Test Commands

```bash
# Create a ScanInstance
kubectl apply -f scaninstance.yaml

# Verify PreScan job created WITHOUT TTL
kubectl get job threat-scan-prescan-<name> -o yaml | grep ttlSecondsAfterFinished
# Should return nothing (field not set)

# Wait for job to fail
kubectl wait --for=condition=failed job/threat-scan-prescan-<name> --timeout=120s

# After 5+ minutes, verify job still exists (no TTL deletion)
sleep 330
kubectl get job threat-scan-prescan-<name>
# Should still exist ✅

# Verify logs accessible
kubectl logs job/threat-scan-prescan-<name>
# Should return logs ✅
```

## Note: All Jobs Now Follow the Same Pattern

**All jobs** (both ScanInstance and Target validation) now follow the same pattern - no TTL, manual cleanup:

```go
// Target validation jobs (GetTargetValidatorJob) - NO TTL
// TTLSecondsAfterFinished is intentionally not set
job.Spec.TTLSecondsAfterFinished = nil // Not set

// ScanInstance jobs (GetPreScanJob) - NO TTL
// TTLSecondsAfterFinished is intentionally not set
job.Spec.TTLSecondsAfterFinished = nil // Not set
```

### Target Validation Job Cleanup

Target validation jobs are cleaned up based on success/failure:

| Job Result | Cleanup Behavior |
|------------|------------------|
| **Success** | Deleted when target becomes `Available` ✅ |
| **Failed** | Kept for debugging, awaiting manual cleanup ✅ |
| **Timeout** | Kept for debugging, awaiting manual cleanup ✅ |

```go
// controllers/target/controller_helper.go
if status == v1.Available {
    // Delete successful validation job
    r.Client.Delete(ctx, validationJob, ...)
} else if operationStatus == v1.Failed {
    // Keep failed validation job for debugging
    log.Infof("Keeping failed validation job for debugging: %s", validationJob.Name)
}
```

### Why Target Validation Jobs Don't Need Long-Term Retention

Even though target validation is a "quick check", failed validation jobs still need to be kept because:
- Failed validations need debugging (wrong credentials, network issues, etc.)
- Quick doesn't mean disposable - failures need investigation
- Consistent pattern across all job types
- Matches k8s-triliovault behavior

## Future Enhancements

When implementing additional phases (Scan, PostScan), extend `cleanupScanInstanceJobs`:

```go
func (r *Reconciler) cleanupScanInstanceJobs(ctx context.Context, scanInstance *v1.ScanInstance) error {
    // ... existing PreScan cleanup ...
    
    // TODO: Delete scan job when implemented
    scanJobName := helpers.GetScanInstanceResourceName(internal.ScanInstanceScanPrefix, scanInstance.Name)
    // ... delete scan job ...
    
    // TODO: Delete post-scan/cleanup jobs when implemented
    postScanJobName := helpers.GetScanInstanceResourceName(internal.ScanInstancePostScanPrefix, scanInstance.Name)
    // ... delete post-scan job ...
}
```

## Summary

| Aspect | Previous | New (TVK-aligned) |
|--------|----------|-------------------|
| **Successful jobs** | Deleted immediately | Kept until ScanInstance completes |
| **Failed jobs** | Deleted immediately | Kept for debugging |
| **Timeout jobs** | Deleted immediately | Kept for debugging |
| **Cleanup timing** | Per-job (immediate) | Batch (on completion) |
| **Debug support** | None (logs lost) | Full (logs available) |
| **TVK consistency** | Different pattern | Aligned pattern |
