# Cleanup Behavior and Janitor Pattern

## Overview

When a ScanInstance completes successfully, the controller attempts to clean up jobs and configmaps. However, **cleanup failure doesn't prevent marking the scan as complete**. Instead, the cleanup status is tracked in the condition reason, and orphaned resources will be handled by a future janitor service.

## Design Decision: Scan Completion vs Cleanup

### Key Principle

**Scan completion is independent of cleanup success**

- ✅ Scan finished successfully → Mark as `Completed`
- ✅ Cleanup succeeded → Great! Reason: "resources cleaned up successfully"
- ✅ Cleanup failed → Still mark complete, Reason: "cleanup failed, janitor will handle"

### Why This Approach?

1. **Scan is the primary operation** - users care if scan completed, not if cleanup worked
2. **Cleanup is housekeeping** - it's important but shouldn't block scan completion
3. **Eventual consistency** - janitor will clean up orphaned resources later
4. **Prevents stuck states** - temporary API issues won't leave scan in limbo

## Implementation

### Controller Logic

**File**: `controllers/scaninstance/controller.go`

```go
if scanInstance.Status.Status == v1.ScanCompleted {
    // Check if already completed (idempotency)
    if scanInstance.HasCondition(v1.Scanning, v1.Completed) {
        return ctrl.Result{}, nil
    }

    // Attempt cleanup
    cleanupErr := r.cleanupScanInstanceJobs(ctx, scanInstance)
    
    var conditionReason string
    if cleanupErr != nil {
        // Cleanup failed - log warning
        r.Log.Warn("cleanup failed, orphaned resources will be handled by janitor")
        conditionReason = "Scan completed successfully, but cleanup failed: <error>. Orphaned resources will be cleaned by janitor."
    } else {
        // Cleanup succeeded
        log.Info("Successfully cleaned up all resources")
        conditionReason = "All scan phases completed, resources cleaned up successfully"
    }

    // Always mark as completed (regardless of cleanup status)
    r.updateScanInstanceCondition(..., v1.Scanning, v1.Completed, conditionReason)
    
    return ctrl.Result{}, nil
}
```

### Cleanup Status in Condition

#### Success Case

```yaml
status:
  status: Completed
  condition:
    - phase: Scanning
      status: Completed
      reason: "All scan phases completed, resources cleaned up successfully"
      timestamp: "2024-01-15T10:05:00Z"
```

#### Failure Case

```yaml
status:
  status: Completed
  condition:
    - phase: Scanning
      status: Completed
      reason: "Scan completed successfully, but cleanup failed: error deleting scan job: Internal Server Error. Orphaned resources will be cleaned by janitor."
      timestamp: "2024-01-15T10:05:00Z"
```

## Logging Strategy

### Success

```go
log.Info("Successfully cleaned up all resources for completed ScanInstance")
```

**Log Level**: `INFO`  
**Message**: Cleanup succeeded

### Failure

```go
r.Log.WithError(cleanupErr).Warn("cleanup failed for completed ScanInstance, orphaned resources will be handled by janitor")
```

**Log Level**: `WARN` (not ERROR!)  
**Why**: Cleanup failure is not critical - janitor will handle it  
**Message**: Includes error details and mentions janitor

## Scenarios

### 1. Normal Success Flow

```
1. Scan completes
2. Status → Completed
3. Controller reconciles
4. Cleanup runs → Success ✅
5. Add condition: "resources cleaned up successfully"
6. Log: INFO "Successfully cleaned up..."
```

### 2. Cleanup Fails (Transient API Error)

```
1. Scan completes
2. Status → Completed
3. Controller reconciles
4. Cleanup runs → Fails (API timeout) ❌
5. Add condition: "cleanup failed: ... janitor will handle"
6. Log: WARN "cleanup failed, janitor will handle"
7. Janitor runs (later) → Cleans up orphaned resources ✅
```

### 3. Cleanup Partially Succeeds

```
1. Scan completes
2. Status → Completed
3. Controller reconciles
4. Cleanup runs:
   - Delete prescan job → Success ✅
   - Delete scan job → Fails ❌
   - Delete configmap → Success ✅
5. Returns error: "error deleting scan job: ..."
6. Add condition: "cleanup failed: error deleting scan job..."
7. Log: WARN "cleanup failed, janitor will handle"
8. Janitor runs → Finds and deletes orphaned scan job ✅
```

### 4. Resources Already Deleted

```
1. Scan completes
2. Status → Completed
3. Controller reconciles
4. Cleanup runs:
   - Get prescan job → NotFound (already deleted)
   - Get scan job → NotFound (already deleted)
   - Get configmap → NotFound (already deleted)
5. No errors (NotFound is ignored)
6. Add condition: "resources cleaned up successfully"
7. Log: INFO "Successfully cleaned up 0 resources"
```

## Future: Janitor Service

The janitor will be a periodic cleanup service that:

### Responsibilities

1. **Find orphaned jobs** - jobs without corresponding ScanInstance
2. **Find orphaned configmaps** - configmaps without corresponding ScanInstance
3. **Check ScanInstance conditions** - look for "cleanup failed" in reason
4. **Delete orphaned resources** - clean up what the controller couldn't

### Implementation Plan

```go
// Janitor logic (future)
func (j *Janitor) CleanupOrphanedResources() {
    // 1. Find all jobs with label: trilio.io/scaninstance-name
    jobs := j.listJobsWithLabel("trilio.io/scaninstance-name")
    
    for _, job := range jobs {
        scanInstanceName := job.Labels["trilio.io/scaninstance-name"]
        
        // 2. Check if ScanInstance exists
        si := j.getScanInstance(scanInstanceName)
        
        if si == nil {
            // ScanInstance deleted - job is orphaned
            j.deleteJob(job)
            continue
        }
        
        // 3. Check if ScanInstance completed with cleanup failure
        if si.HasCondition(Scanning, Completed) {
            condition := si.GetLastConditionForPhase(Scanning)
            if strings.Contains(condition.Reason, "cleanup failed") {
                // Cleanup failed - delete the job
                j.deleteJob(job)
            }
        }
    }
    
    // Similar logic for configmaps
}
```

### Janitor Configuration

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: threat-scanning-janitor
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: janitor
            image: threat-scanning-janitor:latest
            command: ["/janitor"]
            args:
            - --cleanup-age=24h  # Only clean resources older than 24h
            - --dry-run=false
```

## Testing

### Test Cleanup Success

```bash
# Create and complete scan
kubectl apply -f scaninstance.yaml
kubectl wait --for=jsonpath='{.status.status}'=Completed scaninstance/test --timeout=300s

# Check condition reason
kubectl get scaninstance test -o jsonpath='{.status.condition[?(@.phase=="Scanning")].reason}'
# Expected: "All scan phases completed, resources cleaned up successfully"

# Verify resources deleted
kubectl get jobs,configmap -l trilio.io/scaninstance-name=test
# Expected: No resources found
```

### Test Cleanup Failure (Simulate)

```bash
# Create scan
kubectl apply -f scaninstance.yaml

# Before scan completes, patch RBAC to deny job deletion (simulate permission error)
kubectl patch clusterrole threat-scanning-controller --type=json -p='[{"op":"remove","path":"/rules/0/verbs/2"}]'  # Remove 'delete' verb

# Wait for completion
kubectl wait --for=jsonpath='{.status.status}'=Completed scaninstance/test --timeout=300s

# Check condition reason (should mention cleanup failed)
kubectl get scaninstance test -o jsonpath='{.status.condition[?(@.phase=="Scanning")].reason}'
# Expected: "Scan completed successfully, but cleanup failed: ... Orphaned resources will be cleaned by janitor."

# Check logs (should have WARN level)
kubectl logs -n threat-scanning-system deployment/threat-scanning-controller | grep -i cleanup
# Expected: WARN ... cleanup failed for completed ScanInstance, orphaned resources will be handled by janitor

# Restore RBAC
kubectl patch clusterrole threat-scanning-controller --type=json -p='[{"op":"add","path":"/rules/0/verbs/-","value":"delete"}]'

# Verify resources still exist (cleanup failed)
kubectl get jobs,configmap -l trilio.io/scaninstance-name=test
# Expected: Resources still present (orphaned)
```

## Benefits

### 1. Scan Always Completes

Temporary API issues or permission problems don't leave scan in incomplete state.

### 2. Eventual Consistency

Janitor provides eventual cleanup even if controller fails.

### 3. Clear Tracking

Condition reason explicitly states cleanup status.

### 4. Proper Severity

- Success → INFO (normal)
- Failure → WARN (concern but not critical)
- Not ERROR (doesn't block operation)

### 5. Observable

Easy to query for scans with cleanup issues:

```bash
# Find scans with cleanup failures
kubectl get scaninstance -o json | jq '.items[] | select(.status.condition[]? | select(.phase=="Scanning" and .reason | contains("cleanup failed")))'
```

## Comparison: With vs Without This Pattern

| Scenario | Without Janitor Pattern | With Janitor Pattern ✅ |
|----------|------------------------|-------------------------|
| **Cleanup succeeds** | Scan complete, resources gone ✓ | Scan complete, resources gone ✓ |
| **Cleanup fails** | Scan stuck OR marked failed ❌ | Scan complete, janitor cleans ✓ |
| **API unavailable** | Reconciliation fails ❌ | Scan completes, janitor cleans ✓ |
| **Permission issue** | Scan stuck ❌ | Scan completes, janitor cleans ✓ |
| **Observability** | Hard to track | Condition reason shows status ✓ |

## k8s-triliovault Comparison

TVK doesn't have explicit janitor, but uses similar pattern:

```go
// TVK allows cleanup to fail without blocking
cleanCount, err := CleanupJobs(...)
if err != nil {
    log.Warn("cleanup failed")  // Warning, not error
}
// Status still updated to Available/Completed
```

We enhance this by:
1. Tracking cleanup status in condition reason
2. Planning janitor for eventual consistency
3. Better observability

## Summary

| Aspect | Implementation |
|--------|----------------|
| **Scan completion** | Always marked complete if scan finished |
| **Cleanup success** | Reason: "resources cleaned up successfully" |
| **Cleanup failure** | Reason: "cleanup failed: ..., janitor will handle" |
| **Success logging** | INFO level |
| **Failure logging** | WARN level (not ERROR) |
| **Orphaned resources** | Handled by janitor (future) |
| **Idempotency** | Condition prevents re-attempts |
| **Observability** | Condition reason shows exact status |

This pattern ensures scans always complete while maintaining clean resource management through eventual consistency.
