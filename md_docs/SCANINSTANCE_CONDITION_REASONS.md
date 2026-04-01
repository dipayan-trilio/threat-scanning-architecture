# ScanInstance Condition Reasons - Failure & Success Tracking

## Overview

Yes! The `ScanInstanceCondition` structure includes a **`reason` field** that captures detailed failure reasons and success messages.

## Structure

```go
type ScanInstanceCondition struct {
    Phase     ScanPhase     // Queued, PreScan, Scanning
    Status    Status        // InProgress, Completed, Failed
    Timestamp *metav1.Time  // When condition occurred
    Reason    string        // ← Detailed message about why/what happened
}
```

## All Captured Reasons in Controller

### ✅ Success Reasons

| Phase | Status | Reason |
|-------|--------|--------|
| **PreScan** | InProgress | `"Starting pre-scan validation"` |
| **PreScan** | Completed | `"Pre-scan validation completed successfully"` |

### ❌ Failure Reasons

| Phase | Status | Reason | Scenario |
|-------|--------|--------|----------|
| **PreScan** | Failed | `"Failed to create pre-scan job: <error>"` | Job creation failed |
| **PreScan** | Failed | `"Pre-scan validation failed"` | PreScan job failed |
| **PreScan** | Failed | `"Pre-scan job pending deadline exceeded"` | Job stuck/timeout |

## Example Status with Conditions

### Successful PreScan

```yaml
status:
  status: InProgress
  type: TVK
  condition:
    - phase: PreScan
      status: InProgress
      timestamp: "2026-01-22T10:00:00Z"
      reason: "Starting pre-scan validation"
    
    - phase: PreScan
      status: Completed
      timestamp: "2026-01-22T10:05:23Z"
      reason: "Pre-scan validation completed successfully"
```

### Failed PreScan - Job Creation Error

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
      reason: "Failed to create pre-scan job: Job.batch \"threat-scan-prescan-scaninstance-sample\" is invalid: spec.template.spec.containers[0].image: Required value"
```

### Failed PreScan - Validation Error

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
      timestamp: "2026-01-22T10:05:43Z"
      reason: "Pre-scan validation failed"
```

**Note:** The actual failure details would be in the PreScan job logs. The condition reason provides high-level status.

### Failed PreScan - Timeout

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
      timestamp: "2026-01-22T10:15:00Z"
      reason: "Pre-scan job pending deadline exceeded"
```

## Implementation Details

### Adding Conditions with Reasons

From `controller_helper.go`:

```go
func (r *Reconciler) updateScanInstanceCondition(ctx context.Context, 
    scanInstance, originalScanInstance *v1.ScanInstance,
    phase v1.ScanPhase, 
    status v1.Status, 
    reason string) error {  // ← Reason parameter

    condition := v1.ScanInstanceCondition{
        Phase:     phase,
        Status:    status,
        Timestamp: &metav1.Time{Time: metav1.Now().Time},
        Reason:    reason,  // ← Stored in condition
    }

    scanInstance.Status.Condition = append(scanInstance.Status.Condition, condition)

    if err := r.Client.Status().Patch(ctx, scanInstance, client.MergeFrom(originalScanInstance)); err != nil {
        return err
    }
    scanInstance.DeepCopyInto(originalScanInstance)
    return nil
}
```

### Usage Examples in Controller

#### 1. Success - PreScan Started

```go
r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
    v1.PreScan, 
    v1.InProgress,
    "Starting pre-scan validation")  // ← Success message
```

#### 2. Success - PreScan Completed

```go
r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
    v1.PreScan, 
    v1.Completed,
    "Pre-scan validation completed successfully")  // ← Success message
```

#### 3. Failure - Job Creation Error

```go
newPreScanJob, err := r.createPreScanJob(ctx, scanInstance)
if err != nil {
    r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
        v1.PreScan, 
        v1.Failed,
        fmt.Sprintf("Failed to create pre-scan job: %v", err))  // ← Dynamic error
}
```

#### 4. Failure - Validation Failed

```go
if jobStatus == v1.Failed {
    r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
        v1.PreScan, 
        v1.Failed,
        "Pre-scan validation failed")  // ← Generic failure
}
```

#### 5. Failure - Timeout

```go
if helpers.IsJobPendingDeadlineExceeded(preScanJob) {
    r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
        v1.PreScan, 
        v1.Failed,
        "Pre-scan job pending deadline exceeded")  // ← Timeout reason
}
```

## Querying Conditions for Reasons

### Get Last Condition for a Phase

```go
// Get the most recent condition for PreScan phase
lastCondition := scanInstance.GetLastConditionForPhase(v1.PreScan)
if lastCondition != nil {
    fmt.Printf("Phase: %s\n", lastCondition.Phase)
    fmt.Printf("Status: %s\n", lastCondition.Status)
    fmt.Printf("Reason: %s\n", lastCondition.Reason)  // ← Access reason
    fmt.Printf("Time: %s\n", lastCondition.Timestamp)
}
```

### Check for Specific Failure

```go
// Check if PreScan failed and get reason
if scanInstance.HasCondition(v1.PreScan, v1.Failed) {
    condition := scanInstance.GetLastConditionForPhase(v1.PreScan)
    if condition != nil && condition.Status == v1.Failed {
        fmt.Printf("PreScan failed: %s\n", condition.Reason)
    }
}
```

### Using kubectl

```bash
# Get all conditions with reasons
kubectl get scaninstance scaninstance-sample -o jsonpath='{.status.condition[*]}'

# Get just the reasons
kubectl get scaninstance scaninstance-sample -o jsonpath='{range .status.condition[*]}{.phase}{"\t"}{.status}{"\t"}{.reason}{"\n"}{end}'

# Example output:
# PreScan    InProgress    Starting pre-scan validation
# PreScan    Failed        Pre-scan validation failed
```

## Future Phases

When implementing the Scanning phase, similar reasons should be captured:

### Scanning Phase - Example Reasons

**Success:**
- `"Starting backup scanning"`
- `"Backup scanning completed successfully"`
- `"No threats detected"`

**Failures:**
- `"Failed to create scan job: <error>"`
- `"Backup scanning failed"`
- `"Scan job pending deadline exceeded"`
- `"Threats detected: <count> vulnerabilities found"`

### Example Implementation

```go
// Scanning phase - success
r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
    v1.Scanning, 
    v1.Completed,
    "No threats detected")

// Scanning phase - threats found
r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
    v1.Scanning, 
    v1.Completed,
    fmt.Sprintf("Threats detected: %d vulnerabilities found", threatCount))

// Scanning phase - error
r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
    v1.Scanning, 
    v1.Failed,
    fmt.Sprintf("Failed to create scan job: %v", err))
```

## Best Practices for Reason Messages

### ✅ Good Reasons

1. **Be Specific:**
   - ✅ `"Failed to create pre-scan job: Job.batch is invalid: spec.template.spec.containers[0].image: Required value"`
   - ❌ `"Error"`

2. **Include Context:**
   - ✅ `"Pre-scan job pending deadline exceeded"`
   - ❌ `"Timeout"`

3. **Dynamic Errors:**
   - ✅ `fmt.Sprintf("Failed to create pre-scan job: %v", err)`
   - ❌ Hard-coded generic message

4. **User-Friendly:**
   - ✅ `"Pre-scan validation completed successfully"`
   - ❌ `"prescan.ok"`

### ❌ What NOT to Include

- **Sensitive Data:** Don't include credentials, tokens, or secrets
- **Very Long Errors:** Summarize or truncate (keep under 256 chars)
- **Stack Traces:** Log those separately, condition reason is high-level

## Monitoring and Alerting

### Prometheus Metrics (Future)

```prometheus
# Count failures by reason
scan_instance_failures_total{phase="PreScan",reason="validation_failed"} 5
scan_instance_failures_total{phase="PreScan",reason="timeout"} 2
scan_instance_failures_total{phase="PreScan",reason="job_creation_failed"} 1
```

### Log Aggregation

```bash
# Find all failures with reasons
kubectl get scaninstances -o json | jq '.items[].status.condition[] | select(.status=="Failed") | {phase, reason}'
```

### Kubernetes Events

The controller also emits events that complement the condition reasons:

```go
// On failure
r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanFailed",
    "Pre-scan failed for ScanInstance: %s", scanInstance.Name)

// On success
r.Recorder.Eventf(scanInstance, corev1.EventTypeNormal, "PreScanCompleted",
    "Pre-scan completed successfully for ScanInstance: %s", scanInstance.Name)
```

View events:
```bash
kubectl describe scaninstance scaninstance-sample
# Events:
#   Type    Reason              Message
#   ----    ------              -------
#   Normal  PreScanJobCreated   Pre-scan job threat-scan-prescan-scaninstance-sample created
#   Normal  PreScanCompleted    Pre-scan completed successfully
```

## Summary

**Yes, failure reasons are captured in `status.condition[].reason`:**

| Component | Purpose |
|-----------|---------|
| **`condition.reason`** | Detailed failure/success message for each phase transition |
| **`condition.timestamp`** | When the condition occurred |
| **Kubernetes Events** | Additional context and notifications |
| **Job Logs** | Full error details and stack traces |

Together, these provide a complete picture of what happened during ScanInstance processing.

---

**Condition reasons provide essential debugging information for users and operators!** 🎯

