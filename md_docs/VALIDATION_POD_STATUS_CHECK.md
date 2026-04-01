# Validation Job Pod Status Checking

## Overview

The target controller now performs enhanced pod-level status checking for validation jobs to accurately detect failures like `CrashLoopBackOff`, `ImagePullBackOff`, and other container errors that may not immediately reflect in the Job status.

## Changes Made

### 1. Updated Validation Command

The validation command has been simplified to `sleep 60` for testing purposes:

```bash
echo 'Starting validation for target: <target-name>' && sleep 60 && echo 'Validation completed successfully'
```

**Purpose**: 
- Simulates a 60-second validation process
- Easy to test and observe job lifecycle
- Will be replaced with actual validation logic later

### 2. Enhanced Job Status Checking

Added two functions for job status checking:

#### `GetJobStatus(job *batchv1.Job) v1.Status`

Basic job status checker that looks at job conditions and status counters:

```go
// Check job conditions first
for _, condition := range job.Status.Conditions {
    if condition.Type == batchv1.JobComplete && condition.Status == corev1.ConditionTrue {
        return v1.Completed
    }
    if condition.Type == batchv1.JobFailed && condition.Status == corev1.ConditionTrue {
        return v1.Failed
    }
}

// Fall back to status counters
if job.Status.Succeeded > 0 {
    return v1.Completed
}
if job.Status.Failed > 0 {
    return v1.Failed
}
```

#### `GetJobStatusWithPodCheck(ctx, cl, job) v1.Status` ⭐ **NEW**

Enhanced status checker that examines pod phases and container statuses:

```go
// Check pod phase
if pod.Status.Phase == corev1.PodFailed {
    return v1.Failed
}
if pod.Status.Phase == corev1.PodSucceeded {
    return v1.Completed
}

// Check container statuses for error states
for _, containerStatus := range pod.Status.ContainerStatuses {
    if containerStatus.State.Waiting != nil {
        // Detect non-recoverable error states
        if waiting.Reason == "CrashLoopBackOff" ||
           waiting.Reason == "ImagePullBackOff" ||
           waiting.Reason == "ErrImagePull" ||
           waiting.Reason == "CreateContainerConfigError" ||
           waiting.Reason == "InvalidImageName" {
            return v1.Failed
        }
    }
    
    if containerStatus.State.Terminated != nil {
        if terminated.ExitCode != 0 || terminated.Reason == "Error" {
            return v1.Failed
        }
    }
}
```

### 3. Controller Integration

Updated `reconcileValidationJob` in `controllers/target/controller_helper.go`:

```go
// OLD: Only checked job status
jobStatus := helpers.GetJobStatus(validationJob)

// NEW: Checks pod statuses for early error detection
jobStatus := helpers.GetJobStatusWithPodCheck(ctx, r.Client, validationJob)
```

## Target Status Mapping

The controller maps job/pod statuses to target statuses as follows:

| Job/Pod Status | Container State | Target Status | Target Condition |
|----------------|----------------|---------------|------------------|
| Job Completed | Exit Code 0 | `Available` | `Validation: Succeeded` |
| Job Failed | Exit Code ≠ 0 | `Unavailable` | `Validation: Failed` |
| Pod Failed | Any | `Unavailable` | `Validation: Failed` |
| CrashLoopBackOff | Waiting | `Unavailable` | `Validation: Failed` |
| ImagePullBackOff | Waiting | `Unavailable` | `Validation: Failed` |
| ErrImagePull | Waiting | `Unavailable` | `Validation: Failed` |
| CreateContainerConfigError | Waiting | `Unavailable` | `Validation: Failed` |
| InvalidImageName | Waiting | `Unavailable` | `Validation: Failed` |
| Job Running | Running | `InProgress` | `Validation: InProgress` |
| Pod Pending | Waiting | `InProgress` | `Validation: InProgress` |

## Error States Detected

### 1. CrashLoopBackOff

**Scenario**: Container repeatedly crashes after starting

```yaml
containerStatuses:
- name: validator
  state:
    waiting:
      reason: CrashLoopBackOff
      message: back-off 5m0s restarting failed container
```

**Result**: Target marked as `Unavailable` immediately

### 2. ImagePullBackOff / ErrImagePull

**Scenario**: Container image cannot be pulled

```yaml
containerStatuses:
- name: validator
  state:
    waiting:
      reason: ImagePullBackOff
      message: Back-off pulling image "invalid-image:latest"
```

**Result**: Target marked as `Unavailable` immediately

### 3. Container Exit Code ≠ 0

**Scenario**: Container exits with error

```yaml
containerStatuses:
- name: validator
  state:
    terminated:
      exitCode: 1
      reason: Error
```

**Result**: Target marked as `Unavailable`

### 4. Pod Failed

**Scenario**: Pod enters failed state

```yaml
status:
  phase: Failed
```

**Result**: Target marked as `Unavailable`

## Testing Scenarios

### Scenario 1: Successful Validation (sleep 60 completes)

```bash
# Apply target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# Check target status
kubectl get target test-s3-target -o jsonpath='{.status.status}'
# Expected: InProgress (for 60 seconds)

# Wait for job completion (60+ seconds)
kubectl get jobs -n threat-scanning-system

# Check target status again
kubectl get target test-s3-target -o jsonpath='{.status.status}'
# Expected: Available
```

**Timeline**:
```
T=0s    : Target created → Status: InProgress
T=0-5s  : Validation job created
T=5s    : Pod starts, sleep begins
T=5-65s : Pod running (sleep in progress) → Status: InProgress
T=65s   : Pod completes (sleep finished) → Status: Available
T=365s  : Job deleted by TTL (300s after completion)
```

### Scenario 2: Failed Validation (bad image)

```bash
# Set invalid image
export RELATED_IMAGE_VALIDATOR="invalid-image:does-not-exist"

# Apply target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# Check pod status
kubectl get pods -n threat-scanning-system -l trilio.io/component=target-validator

# Expected pod status:
# NAME                                          READY   STATUS             RESTARTS   AGE
# threat-scan-target-validation-xxx-yyy         0/1     ImagePullBackOff   0          30s

# Check target status
kubectl get target test-s3-target -o jsonpath='{.status.status}'
# Expected: Unavailable (detected from ImagePullBackOff)
```

### Scenario 3: Crash Loop (container exits with error)

Create a test with a failing command:

```go
// Temporarily modify validation command
validationCmd = "echo 'Starting' && exit 1"  // Force failure
```

**Expected**:
```
T=0s    : Job created
T=5s    : Pod starts, command runs
T=6s    : Container exits with code 1
T=7s    : Pod status: Error
T=8s    : Controller detects terminated.exitCode=1 → Target: Unavailable
```

### Scenario 4: CrashLoopBackOff

Create a test with a command that crashes:

```go
// Temporarily modify validation command
validationCmd = "kill -9 $$"  // Kill the shell
```

**Expected**:
```
T=0s    : Job created
T=5s    : Pod starts, gets killed
T=10s   : Kubelet restarts container
T=15s   : Container killed again
T=25s   : Backoff begins
T=30s   : Pod status: CrashLoopBackOff
T=31s   : Controller detects CrashLoopBackOff → Target: Unavailable
```

## Validation Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Target Created/Updated                       │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Target Status:        │
                    │  InProgress            │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Create Validation Job  │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   Pod Starting...      │
                    └────────────┬───────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
                ▼                ▼                ▼
    ┌───────────────────┐ ┌──────────────┐ ┌────────────────┐
    │ ImagePullBackOff  │ │ Pod Running  │ │CrashLoopBackOff│
    │ ErrImagePull      │ │ (sleep 60)   │ │ Exit Code ≠ 0  │
    │ InvalidImageName  │ │              │ │                │
    └─────────┬─────────┘ └──────┬───────┘ └────────┬───────┘
              │                  │                   │
              ▼                  ▼                   ▼
    ┌───────────────────┐ ┌──────────────┐ ┌────────────────┐
    │ Target Status:    │ │ Pod Complete │ │ Target Status: │
    │ Unavailable       │ │ Exit Code: 0 │ │ Unavailable    │
    └───────────────────┘ └──────┬───────┘ └────────────────┘
                                 │
                                 ▼
                        ┌────────────────┐
                        │ Target Status: │
                        │ Available      │
                        └────────┬───────┘
                                 │
                                 ▼
                        ┌────────────────┐
                        │  Delete Job    │
                        │  (if Available)│
                        └────────────────┘
```

## Benefits

### 1. **Early Error Detection**

Previously, the controller only checked job-level status, which might take minutes to update. Now it detects pod-level errors immediately.

**Before**:
```
T=30s  : Pod in ImagePullBackOff
T=60s  : Still waiting...
T=90s  : Still waiting...
T=600s : Job finally marked as failed
```

**After**:
```
T=30s  : Pod in ImagePullBackOff
T=31s  : Controller detects error → Target: Unavailable ✅
```

### 2. **Accurate Status**

Pod states provide more granular information than job states:

- **Job Status**: `Active: 1` (just means something is running)
- **Pod Status**: `CrashLoopBackOff` (tells you exactly what's wrong)

### 3. **User Experience**

Users get immediate feedback about validation failures instead of waiting for job timeout.

## Implementation Details

### Pod Listing

The function lists pods using the `job-name` label:

```go
podList := &corev1.PodList{}
err := cl.List(ctx, podList, 
    client.InNamespace(job.Namespace), 
    client.MatchingLabels{"job-name": job.Name})
```

Kubernetes automatically adds the `job-name` label to all pods created by a Job.

### Graceful Degradation

If pod listing fails, the function falls back to basic job status:

```go
if err != nil {
    // If we can't list pods, fall back to job status
    return jobStatus
}
```

This ensures the controller continues working even if pod access is restricted.

### Container State Checking

The function checks three possible container states:

1. **Waiting**: Container hasn't started or is waiting to restart
2. **Running**: Container is currently running
3. **Terminated**: Container has finished (successfully or with error)

```go
type ContainerState struct {
    Waiting    *ContainerStateWaiting
    Running    *ContainerStateRunning
    Terminated *ContainerStateTerminated
}
```

## Future Improvements

### 1. Add More Error Reasons

Currently checking:
- CrashLoopBackOff
- ImagePullBackOff
- ErrImagePull
- CreateContainerConfigError
- InvalidImageName

Could add:
- `OOMKilled` (Out of Memory)
- `DeadlineExceeded`
- `Evicted`

### 2. Capture Error Messages

Store the error reason in target conditions:

```go
if waiting.Reason == "ImagePullBackOff" {
    r.updateTargetCondition(ctx, target, 
        v1.ValidationOperation, 
        v1.Failed, 
        fmt.Sprintf("Image pull failed: %s", waiting.Message))
}
```

### 3. Retry Logic

For transient errors (like network issues), implement retry:

```go
if waiting.Reason == "ErrImagePull" && retryCount < maxRetries {
    // Don't mark as failed yet, allow retry
    return v1.InProgress
}
```

### 4. Actual Validation Logic

Replace `sleep 60` with real validation:

```go
// For NFS targets
validationCmd = "mount | grep /mnt/target && ls -la /mnt/target && touch /mnt/target/.test && rm /mnt/target/.test"

// For S3 targets  
validationCmd = "aws s3 ls s3://$TARGET_BUCKET/ --region $TARGET_REGION"
```

## Monitoring and Debugging

### Check Validation Job Pods

```bash
# List all validation job pods
kubectl get pods -n threat-scanning-system -l trilio.io/component=target-validator

# Describe a specific pod
kubectl describe pod <pod-name> -n threat-scanning-system

# Check pod logs
kubectl logs <pod-name> -n threat-scanning-system
```

### Check Target Conditions

```bash
# Full target status
kubectl get target test-s3-target -o yaml

# Just the conditions
kubectl get target test-s3-target -o jsonpath='{.status.conditions}' | jq
```

### Check Job Status

```bash
# List jobs
kubectl get jobs -n threat-scanning-system

# Describe job
kubectl describe job <job-name> -n threat-scanning-system
```

## Summary

✅ **Validation command**: Changed to `sleep 60` for testing  
✅ **Pod status checking**: Enhanced to detect CrashLoopBackOff, ImagePullBackOff, etc.  
✅ **Target status**: Accurately reflects pod completion or error states  
✅ **Early failure detection**: Errors detected immediately, not after job timeout  
✅ **Graceful degradation**: Falls back to job status if pod access fails  

The controller now provides accurate, real-time feedback about target validation status by examining pod-level states!

