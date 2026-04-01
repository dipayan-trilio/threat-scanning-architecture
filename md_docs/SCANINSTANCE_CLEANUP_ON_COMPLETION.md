# ScanInstance Cleanup on Completion

## Problem

After a ScanInstance completes successfully, the jobs (prescan, scan) and configmap were not being cleaned up properly. Resources were left behind even though they were no longer needed.

### Before

```bash
# ScanInstance completes
kubectl get scaninstance test
# STATUS: Completed

# But resources still exist
kubectl get jobs -l trilio.io/scaninstance-name=test
# prescan job - still exists ❌
# scan job - still exists ❌

kubectl get configmap scan-config-test
# configmap - still exists ❌
```

## Solution

Use **Kubernetes conditions** to track cleanup completion (not annotations):
1. **Scan job completes** → Controller reconciles
2. **Check `Scanning/Completed` condition** → If exists, cleanup already done
3. **If not exists** → Run cleanup and add condition
4. **Idempotency via condition** → Subsequent reconciliations skip cleanup

### Why Conditions (Not Annotations)?

**Conditions are the Kubernetes-native way to track state:**
- ✅ Part of the status (semantic meaning)
- ✅ Visible in `kubectl describe`
- ✅ Queryable for wait conditions
- ✅ Follows Kubernetes conventions

**Annotations are for metadata:**
- ❌ Not semantic (just key-value pairs)
- ❌ Less discoverable
- ❌ Not the idiomatic way to track completion

### Implementation

#### Controller Logic

**File**: `controllers/scaninstance/controller.go`

```go
// Cleanup jobs if ScanInstance has completed successfully
if scanInstance.Status.Status == v1.ScanCompleted {
    // Check if Scanning/Completed condition exists (idempotency) ✅
    if scanInstance.HasCondition(v1.Scanning, v1.Completed) {
        log.Debug("Scanning phase already marked as completed, cleanup already done")
        return ctrl.Result{}, nil
    }

    log.Info("ScanInstance completed, cleaning up jobs and configmap")
    r.cleanupScanInstanceJobs(ctx, scanInstance)

    // Add Scanning/Completed condition to mark cleanup done ✅
    r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, 
        v1.Scanning, v1.Completed,
        "All scan phases completed, resources cleaned up")

    return ctrl.Result{}, nil
}
```

**Key insight**: The `Scanning/Completed` condition serves dual purpose:
1. **Tracks that scan phase finished**
2. **Indicates cleanup was performed**

## Cleanup Flow

### Successful Scan

```
1. PreScan job completes
   └─ Condition: PreScan/Completed ✓
   
2. Scan job completes (or no VMs to scan)
   └─ Status: ScanCompleted ✓
   
3. Controller reconciles (status changed)
   └─ Check: HasCondition(Scanning, Completed)? NO
   └─ Run cleanup:
      ├─ Delete PreScan job ✓
      ├─ Delete Scan job ✓
      └─ Delete ConfigMap ✓
   └─ Add condition: Scanning/Completed ✓
   
4. Controller reconciles again (condition added)
   └─ Check: HasCondition(Scanning, Completed)? YES
   └─ Skip cleanup (already done) ✓
   └─ Done
```

### Failed Scan

```
1. PreScan/Scan job fails
   └─ Condition: PreScan/Failed OR Scanning/Failed
   └─ Status: ScanFailed ✗
   
2. Controller reconciles
   └─ Status != ScanCompleted
   └─ Skip cleanup section
   └─ Jobs remain for debugging ✓
   
3. User deletes ScanInstance
   └─ Finalizer runs
   └─ Clean up all resources
```

## Condition Structure

```yaml
# After successful scan and cleanup
status:
  status: Completed
  condition:
    - phase: PreScan
      status: Completed
      reason: "Pre-scan validation completed successfully"
      timestamp: "2024-01-15T10:00:00Z"
    
    - phase: Scanning
      status: Completed
      reason: "All scan phases completed, resources cleaned up"  # ← Cleanup marker
      timestamp: "2024-01-15T10:05:00Z"
```

## Testing

### Verify Cleanup Works

```bash
# Create and wait for completion
kubectl apply -f scaninstance.yaml
kubectl wait --for=jsonpath='{.status.status}'=Completed scaninstance/test --timeout=300s

# Check Scanning/Completed condition exists
kubectl get scaninstance test -o jsonpath='{.status.condition[?(@.phase=="Scanning")].status}'
# Expected: "Completed"

kubectl get scaninstance test -o jsonpath='{.status.condition[?(@.phase=="Scanning")].reason}'
# Expected: "All scan phases completed, resources cleaned up"

# Verify jobs deleted
kubectl get jobs -l trilio.io/scaninstance-name=test
# Expected: No resources found ✓

# Verify configmap deleted
kubectl get configmap scan-config-test
# Expected: NotFound ✓

# Use kubectl describe to see conditions
kubectl describe scaninstance test
# Expected:
# Conditions:
#   Phase:   PreScan
#   Status:  Completed
#   Phase:   Scanning
#   Status:  Completed
#   Reason:  All scan phases completed, resources cleaned up
```

### Verify Failed Scan Keeps Resources

```bash
# Create failing scan
kubectl apply -f broken-scaninstance.yaml

# Check status
kubectl get scaninstance broken-test -o jsonpath='{.status.status}'
# Expected: Failed

# Check conditions (should NOT have Scanning/Completed)
kubectl get scaninstance broken-test -o jsonpath='{.status.condition[?(@.phase=="Scanning")].status}'
# Expected: Failed (or empty if PreScan failed)

# Verify jobs still exist
kubectl get jobs -l trilio.io/scaninstance-name=broken-test
# Expected: Jobs still present ✓
```

## Comparison: Annotation vs Condition

| Aspect | Annotation Approach | Condition Approach (✅ Better) |
|--------|---------------------|-------------------------------|
| **Semantic** | No (just metadata) | Yes (status tracking) |
| **Discoverable** | Hard to find | `kubectl describe` shows it |
| **Queryable** | Limited | `kubectl wait --for=condition=...` |
| **Kubernetes idiom** | Non-standard | Standard pattern |
| **Status tracking** | Separate from status | Part of status |
| **Cleanup marker** | `cleanup-completed=true` | `Scanning/Completed` condition |

## Why This is Better

### 1. Kubernetes-Native

Conditions are the standard way to track state in Kubernetes:
- Pods have conditions (Ready, Initialized, etc.)
- Nodes have conditions (Ready, MemoryPressure, etc.)
- Deployments have conditions (Available, Progressing, etc.)

We follow the same pattern!

### 2. Single Source of Truth

Status already has conditions for phases:
```yaml
- PreScan/InProgress
- PreScan/Completed
- Scanning/InProgress
- Scanning/Completed  # ← Also means cleanup done!
```

No need for separate annotation.

### 3. Better Observability

```bash
# Easy to see all phases and cleanup status
kubectl describe scaninstance test
# Shows all conditions in one place

# Can wait for specific condition
kubectl wait --for=condition=Scanning=Completed scaninstance/test
```

## k8s-triliovault Pattern

TVK uses similar status-based tracking:

```go
// k8s-triliovault/controllers/restore/controller.go
if restore.Status.Status == v1.Completed {
    CleanupJobs(...)  // Cleanup when status is terminal
}
```

We enhance this by also tracking it in conditions for better observability.

## Files Modified

1. **`controllers/scaninstance/controller.go`** (lines 75-98)
   - Use `HasCondition(Scanning, Completed)` for idempotency
   - Add `Scanning/Completed` condition after cleanup
   - No annotation logic needed

2. **`controllers/scaninstance/controller_helper.go`**
   - Cleanup function unchanged
   - Removed `markCleanupCompleted()` (not needed)

3. **`internal/constants.go`**
   - Removed `CleanupCompletedAnnotation` (not needed)

## Summary

| Aspect | Annotation Approach (Old) | Condition Approach (New) ✅ |
|--------|---------------------------|----------------------------|
| **Cleanup tracking** | Custom annotation | Standard condition |
| **Idempotency check** | `cleanup-completed` annotation | `Scanning/Completed` condition |
| **Discoverability** | Hidden in annotations | Visible in `kubectl describe` |
| **Kubernetes idiom** | Non-standard | Standard pattern |
| **Code complexity** | Extra function + constant | Uses existing condition system |
| **Observability** | Limited | Full condition tracking |
| **Semantic meaning** | None | Part of phase tracking |

Using conditions is the proper Kubernetes-native way to track completion and cleanup!
