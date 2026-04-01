# Job Retry Fix - Scan Job Failure Handling

## Problem

The ScanInstance controller was marking ScanInstances as `Failed` after the first pod failure, even though scan jobs are configured with `BackoffLimit: 3` (allowing 3 retries).

### Root Cause

There were **two issues** causing premature failure detection:

#### Issue 1: `GetJobStatus()` Function
The function was incorrectly checking `job.Status.Failed > 0` to determine if a job had failed. In Kubernetes:
- `job.Status.Failed` counts the number of failed pod attempts
- A job is only considered failed when `job.Status.Failed` reaches `spec.BackoffLimit + 1`
- Kubernetes sets the `JobFailed` condition when the backoff limit is exhausted

The old logic:
```go
if job.Status.Failed > 0 {
    return v1.Failed  // ❌ Wrong: treats first failure as terminal
}
```

#### Issue 2: `GetJobStatusWithPodCheck()` Function
This function was checking **all pods** (including failed pods from previous retry attempts) and returning `Failed` when it found:
1. Any pod with `PodFailed` phase (line 355-356)
2. Any terminated container with non-zero exit code (line 378-384)

This meant that even when the job was on retry attempt #3 (running), it would find the 2 failed pods from attempts #1 and #2, and incorrectly mark the job as failed.

The old logic:
```go
for _, pod := range podList.Items {
    if pod.Status.Phase == corev1.PodFailed {
        return v1.Failed  // ❌ Wrong: could be from previous retry attempt
    }
    // ... check terminated containers
    if terminated.ExitCode != 0 {
        return v1.Failed  // ❌ Wrong: could be from previous retry attempt
    }
}
```

This caused:
1. Attempt #1 fails → Pod #1 goes to `PodFailed`
2. Attempt #2 fails → Pod #2 goes to `PodFailed`
3. Attempt #3 starts → Pod #3 is `Running`, but controller sees Pod #1 and Pod #2 in `PodFailed` state
4. Controller incorrectly returns `v1.Failed` → ScanInstance marked as `Failed`
5. Attempt #3 never gets a chance to complete

## Solution

### Fix 1: Modified `GetJobStatus()`
Correctly handle job retries by:

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

### Fix 2: Modified `GetJobStatusWithPodCheck()`
Only check **currently active pods** (Running or Pending), not failed pods from previous attempts:

1. **Skip Failed Pods**: Explicitly skip pods with `PodFailed` phase (these are from previous attempts)
2. **Only Check Active Pods**: Only examine containers in `Running` or `Pending` pods
3. **Rely on Job Conditions**: Let Kubernetes' `JobFailed` condition be the authoritative source

The fixed logic:
```go
for _, pod := range podList.Items {
    // Skip pods from previous retry attempts (Failed phase)
    if pod.Status.Phase == corev1.PodFailed {
        continue  // ✓ Ignore previous retry attempts
    }
    
    if pod.Status.Phase == corev1.PodSucceeded {
        return v1.Completed
    }
    
    // Only check Running or Pending pods (current attempt)
    if pod.Status.Phase == corev1.PodRunning || pod.Status.Phase == corev1.PodPending {
        // Check container states, but don't prematurely fail
        // Let the job's backoff limit handle failures
    }
}
```

## Behavior After Fix

### Scan Jobs (BackoffLimit: 3)
- Attempt #1 fails: Job status = `InProgress`, ScanInstance status = `InProgress`, Pod #1 = `Failed`
- Attempt #2 fails: Job status = `InProgress`, ScanInstance status = `InProgress`, Pod #2 = `Failed`
- Attempt #3 runs: Job status = `InProgress`, ScanInstance status = `InProgress`, Pod #3 = `Running`
  - Controller now **skips** Pod #1 and Pod #2 (failed from previous attempts)
  - Only checks Pod #3 (current active attempt)
- Attempt #3 fails: Kubernetes sets `JobFailed` condition → Job status = `Failed`, ScanInstance status = `Failed`

### Validation/Poller Jobs (BackoffLimit: 0)
- Attempt #1 fails: Kubernetes sets `JobFailed` condition immediately → Job status = `Failed`
- No change in behavior (already working correctly)

## Files Changed

- `pkg/helpers/job_helper.go`: 
  - Fixed `GetJobStatus()` function
  - Fixed `GetJobStatusWithPodCheck()` function

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
