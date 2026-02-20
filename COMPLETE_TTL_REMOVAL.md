# Complete TTL Removal - All Jobs Pattern

## Summary

Removed `TTLSecondsAfterFinished` from **ALL** jobs (ScanInstance and Target validation) to match k8s-triliovault pattern. Jobs are now manually cleaned up by the controller based on success/failure, with failed jobs kept for debugging.

## Jobs Affected

### 1. Target Validation Jobs
- **Function**: `GetTargetValidatorJob()` in `pkg/helpers/job_helper.go`
- **Purpose**: Validate target accessibility and credentials
- **Cleanup**:
  - ✅ Success → Deleted when target becomes `Available`
  - ❌ Failure → Kept for debugging, awaiting manual cleanup
  - ⏱️ Timeout → Kept for debugging, awaiting manual cleanup

### 2. ScanInstance PreScan Jobs
- **Function**: `GetPreScanJob()` in `pkg/helpers/job_helper.go`
- **Purpose**: Validate backup path, detect workload type
- **Cleanup**:
  - ✅ Success → Deleted when ScanInstance reaches `Completed`
  - ❌ Failure → Kept for debugging, cleaned on CR deletion
  - ⏱️ Timeout → Kept for debugging, cleaned on CR deletion

## Changes Made

### 1. Job Creation - Removed TTL

**File**: `pkg/helpers/job_helper.go`

#### Target Validation Jobs (lines ~118-149)
```go
// BEFORE (with TTL)
backoffLimit := internal.JobBackoffLimit
ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished
job := &batchv1.Job{
    Spec: batchv1.JobSpec{
        BackoffLimit:            &backoffLimit,
        TTLSecondsAfterFinished: &ttlSecondsAfterFinished,  // ❌ Removed
    },
}

// AFTER (no TTL)
backoffLimit := internal.JobBackoffLimit
job := &batchv1.Job{
    Spec: batchv1.JobSpec{
        BackoffLimit: &backoffLimit,
        // TTLSecondsAfterFinished intentionally not set ✅
        // Jobs cleaned manually based on validation result
    },
}
```

#### ScanInstance PreScan Jobs (lines ~638-669)
```go
// BEFORE (with TTL)
backoffLimit := internal.JobBackoffLimit
ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished
job := &batchv1.Job{
    Spec: batchv1.JobSpec{
        BackoffLimit:            &backoffLimit,
        TTLSecondsAfterFinished: &ttlSecondsAfterFinished,  // ❌ Removed
    },
}

// AFTER (no TTL)
backoffLimit := internal.JobBackoffLimit
job := &batchv1.Job{
    Spec: batchv1.JobSpec{
        BackoffLimit: &backoffLimit,
        // TTLSecondsAfterFinished intentionally not set ✅
        // Jobs cleaned by cleanupScanInstanceJobs when complete
    },
}
```

### 2. Target Controller - Keep Failed Jobs

**File**: `controllers/target/controller_helper.go`

#### Removed Deletion of Failed Jobs (lines ~453-490)
```go
// BEFORE (deleted timeout jobs)
if helpers.IsJobPendingDeadlineExceeded(validationJob) {
    status = v1.Unavailable
    operationStatus = v1.Failed
    eventReason = "ValidationFailed"
    deleteJob = true  // ❌ This caused deletion
    specificReason = "Job pending deadline exceeded"
}

if status == v1.Available || deleteJob {  // ❌ Deleted on timeout
    r.Client.Delete(ctx, validationJob, ...)
}

// AFTER (keep failed jobs)
if helpers.IsJobPendingDeadlineExceeded(validationJob) {
    status = v1.Unavailable
    operationStatus = v1.Failed
    eventReason = "ValidationFailed"
    // deleteJob removed - keep for debugging ✅
    specificReason = "Job pending deadline exceeded"
}

// Delete ONLY on success
if status == v1.Available {
    r.Client.Delete(ctx, validationJob, ...)
    log.Infof("Deleted successful validation job")
} else if operationStatus == v1.Failed {
    // Keep failed job for debugging ✅
    log.Infof("Keeping failed validation job for debugging")
}
```

### 3. ScanInstance Controller - Keep Failed Jobs

**File**: `controllers/scaninstance/controller.go`

Already updated to keep failed jobs (see `JOB_CLEANUP_PATTERN.md`).

## Cleanup Matrix

| Job Type | Result | Immediate Action | Long-term Cleanup |
|----------|--------|------------------|-------------------|
| **Target Validation** | Success | Deleted when target `Available` | N/A |
| **Target Validation** | Failure | Kept for debugging | Manual cleanup required |
| **Target Validation** | Timeout | Kept for debugging | Manual cleanup required |
| **PreScan** | Success | Kept until ScanInstance completes | Deleted when ScanInstance `Completed` |
| **PreScan** | Failure | Kept for debugging | Deleted when ScanInstance deleted (finalizer) |
| **PreScan** | Timeout | Kept for debugging | Deleted when ScanInstance deleted (finalizer) |

## Why All Jobs Need Manual Cleanup

### Target Validation Jobs
Even though validation is "quick", failed validations need debugging:
- ❌ Wrong credentials → Need to inspect error messages
- ❌ Network connectivity → Need to see timeout details
- ❌ Permission issues → Need to examine access denied errors
- ❌ Target misconfiguration → Need full error context

### ScanInstance Jobs
Scan operations are long-running and complex:
- ❌ Backup not found → Need to verify path and metadata
- ❌ Unsupported backup format → Need to analyze structure
- ❌ Mount failures → Need to debug volume/credential issues
- ❌ Metadata parsing errors → Need to see raw data

## Testing

### Test Target Validation (No TTL)

```bash
# Create target with wrong credentials
kubectl apply -f broken-target.yaml

# Wait for validation to fail
kubectl wait --for=condition=Unavailable target/broken-target --timeout=120s

# Verify job exists without TTL
kubectl get job -l trilio.io/target-credential-hash=<hash> -o yaml | grep ttlSecondsAfterFinished
# Expected: No output (TTL not set) ✅

# Wait 6 minutes (past old TTL)
sleep 360

# Verify job still exists
kubectl get job -l trilio.io/target-credential-hash=<hash>
# Expected: Job found ✅

# Verify logs accessible
kubectl logs job/<validation-job-name>
# Expected: Full error details ✅

# Fix credentials and update target
kubectl apply -f fixed-target.yaml

# Verify job deleted after success
kubectl wait --for=condition=Available target/fixed-target --timeout=120s
kubectl get job -l trilio.io/target-credential-hash=<new-hash>
# Expected: No jobs (cleaned up) ✅
```

### Test ScanInstance (No TTL)

```bash
# Create ScanInstance with invalid backup path
kubectl apply -f broken-scaninstance.yaml

# Wait for PreScan to fail
kubectl get scaninstance test -o jsonpath='{.status.status}'
# Expected: Failed

# Verify job exists without TTL
kubectl get job threat-scan-prescan-test -o yaml | grep ttlSecondsAfterFinished
# Expected: No output (TTL not set) ✅

# Wait 6 minutes (past old TTL)
sleep 360

# Verify job still exists
kubectl get job threat-scan-prescan-test
# Expected: Job found ✅

# Verify logs accessible
kubectl logs job/threat-scan-prescan-test
# Expected: Full error details ✅

# Delete ScanInstance
kubectl delete scaninstance test

# Verify job cleaned by finalizer
kubectl get job threat-scan-prescan-test
# Expected: Not found (cleaned by finalizer) ✅
```

## Manual Cleanup Commands

### Clean Failed Target Validation Jobs

```bash
# List failed validation jobs
kubectl get jobs -l app.kubernetes.io/component=target-validator,app.kubernetes.io/managed-by=threat-scanning-controller

# Delete specific job
kubectl delete job <validation-job-name>

# Delete all failed validation jobs (careful!)
kubectl delete jobs -l app.kubernetes.io/component=target-validator --field-selector status.failed=1
```

### Clean Failed ScanInstance Jobs

```bash
# List failed PreScan jobs
kubectl get jobs -l app.kubernetes.io/component=prescan,app.kubernetes.io/managed-by=threat-scanning-controller

# Delete specific job
kubectl delete job threat-scan-prescan-<name>

# Or delete the ScanInstance (finalizer will clean up)
kubectl delete scaninstance <name>
```

## k8s-triliovault Alignment

This now fully matches TVK's pattern:

### TVK Job Creation
```go
// k8s-triliovault/controllers/helpers/job_helper.go
func GetJob(...) *batchv1.Job {
    job := &batchv1.Job{
        Spec: batchv1.JobSpec{
            // NO TTLSecondsAfterFinished set ✅
            ActiveDeadlineSeconds: &jobActiveDeadlineSeconds,
            Template: ...
        },
    }
}
```

### TVK Job Cleanup
```go
// k8s-triliovault/controllers/helpers/cleanup_helper.go
func CleanupJobs(ctx, cli, jobs) {
    propagationPolicy := metav1.DeletePropagationForeground
    for _, job := range jobs {
        cli.Delete(ctx, &job, &client.DeleteOptions{
            PropagationPolicy: &propagationPolicy,
        })
    }
}
```

### TVK Cleanup Timing
- Backup: Jobs deleted when status = `Available`, `Canceling`, or `Canceled`
- Restore: Jobs deleted when status = `Completed`
- No automatic TTL cleanup, all manual

## Benefits

| Benefit | Description |
|---------|-------------|
| **Debugging** | Failed jobs remain available for log inspection |
| **Consistency** | Same pattern for all job types (target, prescan, scan) |
| **TVK Alignment** | Matches k8s-triliovault behavior exactly |
| **Control** | Controller decides cleanup timing, not Kubernetes |
| **Operations** | Can troubleshoot issues hours/days after they occur |

## Migration Notes

### For Existing Deployments

If you have existing jobs with TTL:
1. They will be deleted by TTL if already finished
2. New jobs will not have TTL
3. No migration action needed - behavior improves automatically

### For Monitoring/Alerts

Update any monitoring that assumes jobs auto-delete:
- Alert on old failed validation jobs (manual cleanup needed)
- Alert on old failed ScanInstance jobs (CR deletion or manual cleanup)
- Don't alert on job age for succeeded operations (normal to see briefly)

## Files Modified

1. `pkg/helpers/job_helper.go`
   - `GetTargetValidatorJob()` - Removed TTL
   - `GetPreScanJob()` - Removed TTL

2. `controllers/target/controller_helper.go`
   - `reconcileValidationJob()` - Keep failed jobs, only delete on success

3. `controllers/scaninstance/controller.go`
   - Already updated to keep failed jobs

4. `controllers/scaninstance/controller_helper.go`
   - `cleanupScanInstanceJobs()` - Manual cleanup on completion

## Documentation

- `JOB_CLEANUP_PATTERN.md` - Full pattern explanation
- `TTL_REMOVAL_FIX.md` - TTL removal rationale
- This file - Complete summary

## Rollback

If needed (not recommended):

```go
// Add TTL back
ttlSecondsAfterFinished := internal.JobTTLSecondsAfterFinished
job.Spec.TTLSecondsAfterFinished = &ttlSecondsAfterFinished
```

However, this would:
- Break debugging for failed operations
- Diverge from TVK pattern
- Make troubleshooting impossible
