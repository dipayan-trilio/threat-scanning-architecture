# Job Retry Fix - Scan Job Failure Handling

## Problem

The ScanInstance controller was marking ScanInstances as `Failed` after the first pod failure, even though scan jobs are configured with `BackoffLimit: 3` (allowing 3 retries).

### Root Cause

The `GetJobStatus` function in `pkg/helpers/job_helper.go` was incorrectly checking `job.Status.Failed > 0` to determine if a job had failed. In Kubernetes:
- `job.Status.Failed` counts the number of failed pod attempts
- A job is only considered failed when `job.Status.Failed` reaches `spec.BackoffLimit + 1`
- Kubernetes sets the `JobFailed` condition when the backoff limit is exhausted

The old logic:
```go
if job.Status.Failed > 0 {
    return v1.Failed  // ❌ Wrong: treats first failure as terminal
}
```

This caused:
1. First pod fails → `job.Status.Failed = 1`
2. Controller sees `job.Status.Failed > 0` → marks job as `Failed`
3. ScanInstance marked as `Failed` immediately
4. No retries occur despite `BackoffLimit: 3`

## Solution

Modified `GetJobStatus` to correctly handle job retries by:

1. **Prioritizing Job Conditions**: Check `JobFailed` condition first (authoritative source)
2. **Treating Failed Attempts as In-Progress**: If pods have failed but the `JobFailed` condition is not set, the job is still retrying
3. **Maintaining Backward Compatibility**: Jobs with `BackoffLimit: 0` still fail immediately

The fixed logic:
```go
// Check job conditions first (authoritative)
for _, condition := range job.Status.Conditions {
    if condition.Type == batchv1.JobFailed && condition.Status == corev1.ConditionTrue {
        return v1.Failed  // ✓ Job exhausted retries
    }
}

// If there are failed attempts but no JobFailed condition,
// the job is retrying (between attempts)
if job.Status.Failed > 0 {
    return v1.InProgress  // ✓ Job will retry
}
```

## Behavior After Fix

### Scan Jobs (BackoffLimit: 3)
- Pod failure #1: Job status = `InProgress`, ScanInstance status = `InProgress`
- Pod failure #2: Job status = `InProgress`, ScanInstance status = `InProgress`
- Pod failure #3: Job status = `InProgress`, ScanInstance status = `InProgress`
- Pod failure #4: Kubernetes sets `JobFailed` condition → Job status = `Failed`, ScanInstance status = `Failed`

### Validation/Poller Jobs (BackoffLimit: 0)
- Pod failure #1: Kubernetes sets `JobFailed` condition immediately → Job status = `Failed`
- No change in behavior (already working correctly)

## Files Changed

- `pkg/helpers/job_helper.go`: Fixed `GetJobStatus` function

## Testing

Run the verification script to test the fix:

```bash
./verify_job_retry_fix.sh
```

The script:
1. Creates a test ScanInstance
2. Monitors the scan job for pod failures
3. Verifies that the ScanInstance remains `InProgress` during retries
4. Confirms the ScanInstance is marked `Failed` only after all retries are exhausted

## References

- Kubernetes Job BackoffLimit: https://kubernetes.io/docs/concepts/workloads/controllers/job/#pod-backoff-failure-policy
- Job Status Conditions: https://kubernetes.io/docs/concepts/workloads/controllers/job/#job-tracking-with-finalizers
