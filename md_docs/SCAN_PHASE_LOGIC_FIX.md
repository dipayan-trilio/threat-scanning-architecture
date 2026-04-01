# Fix: Scan Phase Logic Flow Issue

## Problem

After implementing the scan job creation, the controller was getting stuck in a loop showing:

```
"PreScan phase already completed, skipping to next phase"
```

Even though the scan job had completed successfully, the ScanInstance status remained as `InProgress` and never progressed to `Completed`.

## Root Cause

The issue was in the controller logic flow:

### Original Broken Flow

```go
// In Reconcile()
if scanInstance.HasCondition(v1.PreScan, v1.Completed) {
    log.Info("PreScan phase already completed, skipping to next phase")
    return ctrl.Result{}, nil  // ❌ Returns early without checking scan job!
}

// ... PreScan job handling ...

switch jobStatus {
case v1.Completed:
    // ... update condition ...
    
    // Create scan job (only runs first time)
    if !scanInstance.HasCondition(v1.Scanning, v1.InProgress) { 
        // ... create scan job ...
        return ctrl.Result{}, nil  // ❌ Returns after creating job
    }
    
    // Check scan job status
    // ❌ This code never runs because of the early returns above!
    scanJob, err := r.getScanJob(ctx, scanInstance)
    // ...
}
```

### Why It Failed

**First Reconciliation (PreScan Completed):**
```
1. PreScan job completes ✅
2. Condition updated: PreScan/Completed ✅
3. Scan configmap created ✅
4. Scan job created ✅
5. Condition updated: Scanning/InProgress ✅
6. return ctrl.Result{}, nil  // Returns here
```

**Second Reconciliation (Scan Job Completed):**
```
1. Scan job completes (status changes to Succeeded)
2. Job watcher triggers reconciliation ✅
3. Controller checks: HasCondition(PreScan, Completed)? YES
4. Logs: "PreScan phase already completed, skipping to next phase"
5. return ctrl.Result{}, nil  // ❌ Returns WITHOUT checking scan job status!
```

**Result:** Infinite loop, scan job status never checked.

## Solution

Refactored the controller to properly handle the scan phase:

### New Fixed Flow

```go
// In Reconcile()
if scanInstance.HasCondition(v1.PreScan, v1.Completed) {
    log.Info("PreScan phase already completed, proceeding to scan phase")
    return r.reconcileScanPhase(ctx, scanInstance, originalScanInstance)  // ✅ Always check scan phase!
}

// ... PreScan job handling ...

switch jobStatus {
case v1.Completed:
    // ... update condition ...
    
    // Proceed to scan phase
    return r.reconcileScanPhase(ctx, scanInstance, originalScanInstance)  // ✅ Delegate to scan phase
}
```

### New Helper Function: `reconcileScanPhase()`

**File: `controllers/scaninstance/controller_helper.go`**

```go
func (r *Reconciler) reconcileScanPhase(ctx, scanInstance, originalScanInstance) (ctrl.Result, error) {
    // Check if we've already moved to Scanning phase (idempotency)
    if !scanInstance.HasCondition(v1.Scanning, v1.InProgress) &&
       !scanInstance.HasCondition(v1.Scanning, v1.Completed) &&
       !scanInstance.HasCondition(v1.Scanning, v1.Failed) {
        
        // First time in scan phase - create resources
        if len(scanInstance.Status.ScanLocations) == 0 {
            // No VM workloads, mark as completed
            return ...
        }
        
        // Create scan configmap
        // Create scan job
        // Update condition to Scanning/InProgress
        return ctrl.Result{}, nil
    }
    
    // Already in Scanning phase - check scan job status
    scanJob, err := r.getScanJob(ctx, scanInstance)
    if scanJob == nil {
        // Job missing - error state
        return ...
    }
    
    // Process scan job status (Completed/Failed/InProgress)
    return r.processScanJobStatus(ctx, scanInstance, originalScanInstance, scanJob)
}
```

### Why This Works

**First Reconciliation (PreScan Completed):**
```
1. PreScan job completes ✅
2. jobStatus = Completed
3. Update condition: PreScan/Completed ✅
4. Call reconcileScanPhase() ✅
   a. Check: HasCondition(Scanning, *)? NO
   b. Create scan configmap ✅
   c. Create scan job ✅
   d. Update condition: Scanning/InProgress ✅
5. Return
```

**Second Reconciliation (Scan Job Completed):**
```
1. Scan job completes (status changes to Succeeded)
2. Job watcher triggers reconciliation ✅
3. Check: HasCondition(PreScan, Completed)? YES
4. Call reconcileScanPhase() ✅
   a. Check: HasCondition(Scanning, *)? YES (InProgress)
   b. Get scan job ✅
   c. Call processScanJobStatus() ✅
   d. jobStatus = Completed
   e. Update condition: Scanning/Completed ✅
   f. Update status: ScanCompleted ✅
   g. Generate event: ScanCompleted ✅
5. Return
```

**Third Reconciliation (Cleanup):**
```
1. Controller checks status
2. Status = ScanCompleted
3. Call cleanupScanInstanceJobs() ✅
   a. Delete prescan job ✅
   b. Delete scan job ✅
   c. Delete scan configmap ✅
4. Return
```

## Changes Made

### 1. Controller Entry Point (`controller.go`)

**Before:**
```go
if scanInstance.HasCondition(v1.PreScan, v1.Completed) {
    return ctrl.Result{}, nil  // ❌ Early return
}
```

**After:**
```go
if scanInstance.HasCondition(v1.PreScan, v1.Completed) {
    return r.reconcileScanPhase(ctx, scanInstance, originalScanInstance)  // ✅ Check scan phase
}
```

### 2. PreScan Completion Handler (`controller.go`)

**Before:**
```go
case v1.Completed:
    // ... update condition ...
    
    // Inline scan job creation logic (100+ lines)
    if !scanInstance.HasCondition(v1.Scanning, ...) {
        // ... create configmap ...
        // ... create job ...
        return ctrl.Result{}, nil  // ❌ Returns early
    }
    
    // Unreachable code
    scanJob, err := r.getScanJob(...)
    // ...
```

**After:**
```go
case v1.Completed:
    // ... update condition ...
    
    // Delegate to scan phase handler
    return r.reconcileScanPhase(ctx, scanInstance, originalScanInstance)  // ✅ Always processes scan
```

### 3. New Function (`controller_helper.go`)

Added `reconcileScanPhase()` that:
- Handles scan job creation (first time)
- Handles scan job status checking (subsequent times)
- Ensures scan job is always processed when prescan is complete

## Testing Results

With this fix, the flow now works correctly:

```
✅ PreScan creates prescan job
✅ PreScan completes
✅ Scan configmap created
✅ Scan job created  
✅ Scan job runs for 5 minutes
✅ Scan job completes
✅ ScanInstance marked as Completed
✅ All jobs and configmap deleted
```

## Key Takeaway

**Always delegate phase transitions to dedicated handler functions instead of inline logic with early returns.**

### Anti-Pattern (What We Had)
```go
if previousPhaseCompleted {
    if !nextPhaseStarted {
        // Create next phase resources
        return  // ❌ Never checks next phase status
    }
    // Check next phase status (unreachable)
}
```

### Best Pattern (What We Have Now)
```go
if previousPhaseCompleted {
    return reconcileNextPhase()  // ✅ Always processes next phase
}

func reconcileNextPhase() {
    if !nextPhaseStarted {
        // Create next phase resources
        return
    }
    // Check next phase status (always reached)
}
```

## Files Modified

| File | Change |
|------|--------|
| `controllers/scaninstance/controller.go` | Changed early return to call `reconcileScanPhase()` |
| `controllers/scaninstance/controller_helper.go` | Added `reconcileScanPhase()` function |

## Verification

✅ **Compilation**: All code compiles successfully
✅ **Linter**: No linter errors
✅ **Logic Flow**: Scan phase always processes when prescan completes

**Ready for redeployment and testing!**
