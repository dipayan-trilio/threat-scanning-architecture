# ImagePullBackOff Detection and Kubernetes Events

## Question 1: Is ImagePullBackOff Captured? ✅ YES!

### Pod Error Detection

The controller uses `GetJobStatusWithPodCheck()` which **actively checks pod status** to detect error conditions early, including `ImagePullBackOff`.

### Detected Pod Error States

From `pkg/helpers/job_helper.go`:

```go
// Check container statuses for error states
for _, containerStatus := range pod.Status.ContainerStatuses {
    if containerStatus.State.Waiting != nil {
        waiting := containerStatus.State.Waiting
        // These are error states that won't recover
        if waiting.Reason == "CrashLoopBackOff" ||
            waiting.Reason == "ImagePullBackOff" ||      // ← YES! Detected
            waiting.Reason == "ErrImagePull" ||
            waiting.Reason == "CreateContainerConfigError" ||
            waiting.Reason == "InvalidImageName" {
            return v1.Failed  // Mark job as failed
        }
    }
}
```

### What Gets Detected

| Pod Error State | Detected? | Result |
|----------------|-----------|--------|
| **ImagePullBackOff** | ✅ Yes | Job marked as Failed |
| **ErrImagePull** | ✅ Yes | Job marked as Failed |
| **CrashLoopBackOff** | ✅ Yes | Job marked as Failed |
| **InvalidImageName** | ✅ Yes | Job marked as Failed |
| **CreateContainerConfigError** | ✅ Yes | Job marked as Failed |
| **Container Exit Code != 0** | ✅ Yes | Job marked as Failed |
| **Pod Phase = Failed** | ✅ Yes | Job marked as Failed |

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. PreScan Job Created                                          │
│    └─> Job starts, tries to pull image                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Image Pull Fails                                             │
│    └─> Pod enters "ImagePullBackOff" state                      │
│    └─> Or "ErrImagePull" state                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Controller Reconciles (Job watcher triggered)               │
│    └─> Calls GetJobStatusWithPodCheck()                         │
│    └─> Checks pod.Status.ContainerStatuses                      │
│    └─> Detects ImagePullBackOff                                 │
│    └─> Returns: v1.Failed                                       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Controller Updates ScanInstance                              │
│    └─> Adds condition: PreScan/Failed                           │
│    └─> Reason: "Pre-scan validation failed"                     │
│    └─> Updates status: Failed                                   │
│    └─> Emits Event: PreScanFailed                               │
│    └─> Deletes failed job                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Example: ImagePullBackOff Scenario

**Initial State:**
```yaml
status:
  status: InProgress
  condition:
    - phase: PreScan
      status: InProgress
      timestamp: "2026-01-22T10:00:00Z"
      reason: "Starting pre-scan validation"
```

**After ImagePullBackOff Detected:**
```yaml
status:
  status: Failed
  condition:
    - phase: PreScan
      status: InProgress
      timestamp: "2026-01-22T10:00:00Z"
      reason: "Starting pre-scan validation"
    
    - phase: PreScan
      status: Failed
      timestamp: "2026-01-22T10:00:15Z"
      reason: "Pre-scan validation failed"  # ← Generic failure reason
```

**Note:** The reason is generic `"Pre-scan validation failed"`, not specifically mentioning ImagePullBackOff. The detailed error is in the pod events (see Question 2 below).

---

## Question 2: Are These in Kubernetes Events? ✅ YES!

### Two Types of Events

1. **ScanInstance Events** - Emitted by the controller
2. **Pod Events** - Emitted by Kubernetes for the job pods

### ScanInstance Events (Controller-Emitted)

The controller emits events that appear when you describe the ScanInstance:

#### Event Types

| Event Type | Reason | Message | When |
|------------|--------|---------|------|
| **Normal** | `StatusUpdate` | `ScanInstance status updated to: <status>` | Every status change |
| **Normal** | `PreScanJobCreated` | `Pre-scan job <name> created for ScanInstance: <name>` | Job created |
| **Normal** | `PreScanCompleted` | `Pre-scan completed successfully for ScanInstance: <name>` | PreScan succeeds |
| **Warning** | `PreScanJobCreateFailed` | `Pre-scan job creation failed for ScanInstance: <name>` | Job creation fails |
| **Warning** | `PreScanFailed` | `Pre-scan failed for ScanInstance: <name>` | PreScan fails |
| **Warning** | `PreScanTimeout` | `Pre-scan job timed out for ScanInstance: <name>` | Job timeout |

#### Implementation

From `controllers/scaninstance/controller.go`:

```go
// On job creation
r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "PreScanJobCreated",
    "Pre-scan job %s created for ScanInstance: %s", newPreScanJob.Name, scanInstance.Name)

// On success
r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "PreScanCompleted",
    "Pre-scan completed successfully for ScanInstance: %s", scanInstance.Name)

// On failure
r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanFailed",
    "Pre-scan failed for ScanInstance: %s", scanInstance.Name)

// On timeout
r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanTimeout",
    "Pre-scan job timed out for ScanInstance: %s", scanInstance.Name)

// On job creation failure
r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanJobCreateFailed",
    "Pre-scan job creation failed for ScanInstance: %s", scanInstance.Name)

// On status update
r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "StatusUpdate",
    "ScanInstance status updated to: %s", status)
```

### Viewing ScanInstance Events

```bash
# Describe ScanInstance to see events
kubectl describe scaninstance scaninstance-sample
```

**Example Output:**

```yaml
Name:         scaninstance-sample
Namespace:    
Labels:       <none>
Annotations:  <none>
API Version:  threatscanning.trilio.io/v1
Kind:         ScanInstance
# ... spec details ...

Status:
  Condition:
    Phase:       PreScan
    Reason:      Starting pre-scan validation
    Status:      InProgress
    Timestamp:   2026-01-22T10:00:00Z
    Phase:       PreScan
    Reason:      Pre-scan validation failed
    Status:      Failed
    Timestamp:   2026-01-22T10:00:15Z
  Status:        Failed

Events:
  Type     Reason               Age   From                          Message
  ----     ------               ----  ----                          -------
  Normal   StatusUpdate         60s   scaninstance-controller       ScanInstance status updated to: Queued
  Normal   StatusUpdate         60s   scaninstance-controller       ScanInstance status updated to: InProgress
  Normal   PreScanJobCreated    60s   scaninstance-controller       Pre-scan job threat-scan-prescan-scaninstance-sample created for ScanInstance: scaninstance-sample
  Warning  PreScanFailed        45s   scaninstance-controller       Pre-scan failed for ScanInstance: scaninstance-sample
  Normal   StatusUpdate         45s   scaninstance-controller       ScanInstance status updated to: Failed
```

### Pod Events (For ImagePullBackOff)

For detailed error information (like ImagePullBackOff), you need to check the **Pod events**:

```bash
# Get the job pod name
kubectl get pods -n threat-scanning-system -l job-name=threat-scan-prescan-scaninstance-sample

# Describe the pod to see detailed events
kubectl describe pod -n threat-scanning-system <pod-name>
```

**Example Pod Events with ImagePullBackOff:**

```yaml
Name:         threat-scan-prescan-scaninstance-sample-abc123
Namespace:    threat-scanning-system
# ... pod details ...

Events:
  Type     Reason             Age   From               Message
  ----     ------             ----  ----               -------
  Normal   Scheduled          30s   default-scheduler  Successfully assigned threat-scanning-system/threat-scan-prescan-scaninstance-sample-abc123 to node1
  Normal   Pulling            30s   kubelet            Pulling image "eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v2"
  Warning  Failed             25s   kubelet            Failed to pull image "eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v2": rpc error: code = Unknown desc = Error response from daemon: pull access denied for eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher, repository does not exist or may require 'docker login'
  Warning  Failed             25s   kubelet            Error: ErrImagePull
  Normal   BackOff            10s   kubelet            Back-off pulling image "eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v2"
  Warning  Failed             10s   kubelet            Error: ImagePullBackOff
```

### Complete Event Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ ScanInstance Events (kubectl describe scaninstance)            │
├─────────────────────────────────────────────────────────────────┤
│ • StatusUpdate: Queued                                          │
│ • StatusUpdate: InProgress                                      │
│ • PreScanJobCreated: Job created                                │
│ • PreScanFailed: Pre-scan failed                                │
│ • StatusUpdate: Failed                                          │
└─────────────────────────────────────────────────────────────────┘
                            +
┌─────────────────────────────────────────────────────────────────┐
│ Pod Events (kubectl describe pod)                              │
├─────────────────────────────────────────────────────────────────┤
│ • Scheduled: Pod assigned to node                               │
│ • Pulling: Pulling image                                        │
│ • Failed: Failed to pull image (detailed error)                 │
│ • Failed: Error: ErrImagePull                                   │
│ • BackOff: Back-off pulling image                               │
│ • Failed: Error: ImagePullBackOff                               │
└─────────────────────────────────────────────────────────────────┘
                            =
┌─────────────────────────────────────────────────────────────────┐
│ Complete Picture of What Happened                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Detailed Comparison

### What Each Event Source Shows

| Information | ScanInstance Events | Pod Events | Condition Reason |
|------------|-------------------|-----------|-----------------|
| **High-level status** | ✅ Yes | ❌ No | ✅ Yes |
| **Phase transitions** | ✅ Yes | ❌ No | ✅ Yes |
| **Job lifecycle** | ✅ Yes | ❌ No | ❌ No |
| **Image pull errors** | ❌ No | ✅ Yes | ❌ No |
| **Container errors** | ❌ No | ✅ Yes | ❌ No |
| **Scheduling issues** | ❌ No | ✅ Yes | ❌ No |
| **Exit codes** | ❌ No | ✅ Yes | ❌ No |
| **Detailed error messages** | ❌ No | ✅ Yes | Partial |

### Debugging Workflow

```bash
# 1. Check ScanInstance status and high-level events
kubectl describe scaninstance scaninstance-sample

# Shows:
# - Current status (Queued/InProgress/Completed/Failed)
# - Conditions with phases and reasons
# - High-level events (job created, failed, completed)

# 2. If failed, check the job
kubectl get job -n threat-scanning-system threat-scan-prescan-scaninstance-sample

# 3. Check the pod
kubectl get pods -n threat-scanning-system -l job-name=threat-scan-prescan-scaninstance-sample

# 4. Get detailed pod events and error messages
kubectl describe pod -n threat-scanning-system <pod-name>

# Shows:
# - Image pull errors (ImagePullBackOff, ErrImagePull)
# - Container crash details
# - Scheduling issues
# - Resource constraints
# - Volume mount errors

# 5. Check pod logs (if container started)
kubectl logs -n threat-scanning-system <pod-name>
```

---

## Enhancement: More Detailed Condition Reasons

### Current Limitation

Currently, when ImagePullBackOff is detected, the condition reason is generic:

```yaml
- phase: PreScan
  status: Failed
  reason: "Pre-scan validation failed"  # Generic
```

### Enhancement Suggestion

We could make the condition reason more specific by capturing the pod error:

```go
// Enhanced version (future improvement)
func GetJobStatusWithPodCheck(ctx context.Context, cl client.Client, job *batchv1.Job) (v1.Status, string) {
    // ... existing code ...
    
    for _, containerStatus := range pod.Status.ContainerStatuses {
        if containerStatus.State.Waiting != nil {
            waiting := containerStatus.State.Waiting
            if waiting.Reason == "ImagePullBackOff" {
                // Return detailed reason
                return v1.Failed, fmt.Sprintf("Image pull failed: %s", waiting.Message)
            }
        }
    }
    
    return jobStatus, ""
}
```

Then in the controller:

```go
jobStatus, reason := helpers.GetJobStatusWithPodCheck(ctx, r.Client, preScanJob)

if jobStatus == v1.Failed {
    if reason == "" {
        reason = "Pre-scan validation failed"
    }
    r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
        v1.PreScan, v1.Failed, reason)  // ← More specific reason
}
```

**Result:**
```yaml
- phase: PreScan
  status: Failed
  reason: "Image pull failed: rpc error: code = Unknown desc = pull access denied"
```

---

## Summary

### ✅ Question 1: Is ImagePullBackOff Captured?

**YES!** The controller actively detects these pod errors:
- ✅ ImagePullBackOff
- ✅ ErrImagePull
- ✅ CrashLoopBackOff
- ✅ InvalidImageName
- ✅ CreateContainerConfigError

### ✅ Question 2: Are These in Events?

**YES!** Two levels of events:

1. **ScanInstance Events** (high-level):
   - PreScanJobCreated
   - PreScanFailed
   - PreScanCompleted
   - PreScanTimeout
   - StatusUpdate

2. **Pod Events** (detailed):
   - Image pull failures
   - Container crashes
   - Scheduling issues
   - Resource constraints

### 🔍 How to Debug

```bash
# High-level view
kubectl describe scaninstance <name>

# Detailed error info
kubectl describe pod -n threat-scanning-system <pod-name>
```

---

**Both ImagePullBackOff detection and Kubernetes Events are fully implemented!** 🎉

