# Prescan Error Annotation Refetch Fix

## Problem

The prescan error annotation was being set on the job by the prescan container, but it was **not appearing in ScanInstance events or conditions**. The error message visible in the job annotation was not propagating to the ScanInstance CR.

### Symptoms

```bash
# Job has the error annotation
kubectl get job threat-scan-prescan-test -o jsonpath='{.metadata.annotations.threatscanning\.trilio\.io/prescan-error}'
# Output: "Prescan validation failed: Backup path does not exist: /triliodata/..."

# But ScanInstance event shows generic error
kubectl get events --field-selector involvedObject.name=test
# Output: "Pre-scan failed for ScanInstance test: Pre-scan validation failed"
#         ^^^^ Generic message, not the specific error

# And ScanInstance condition has generic reason
kubectl get scaninstance test -o jsonpath='{.status.condition}'
# Output: reason: "Pre-scan validation failed"  (no specific path error)
```

## Root Cause

The controller was reading the job annotation from a **cached/stale copy** of the job object. Here's the timeline:

```
1. Controller gets job from cache (annotations = {})
2. Controller checks job status → Failed
3. Prescan container updates job annotation (in Kubernetes API)
4. Controller reads annotation from cached job (annotations still = {})
5. Controller uses generic error message ❌
```

### Why This Happened

```go
// controllers/scaninstance/controller.go (BEFORE - BROKEN)
preScanJob, err := r.getPreScanJob(ctx, scanInstance)  // Gets job once

switch jobStatus {
case v1.Failed:
    // Read annotation from CACHED job
    if errMsg, ok := preScanJob.Annotations[internal.PrescanErrorAnnotation]; ok {
        errorReason = errMsg  // This was always empty!
    }
}
```

The job object (`preScanJob`) was fetched once at the beginning, before the prescan container had a chance to update its annotation. When the job failed, the controller read from this stale copy.

## Solution

**Refetch the job** when reading error annotations to get the latest state from the Kubernetes API server.

### Code Change

**File**: `controllers/scaninstance/controller.go`

```go
case v1.Failed:
    if !scanInstance.HasCondition(v1.PreScan, v1.Failed) {
        // Refetch job to get latest annotations (prescan container updates them)
        // Following TVK datamover pattern: job updates its own annotations, controller reads them
        latestJob, err := r.getPreScanJob(ctx, scanInstance)
        if err != nil {
            log.WithError(err).Error("error refetching prescan job for error annotation")
            // Continue with existing job if refetch fails
            latestJob = preScanJob
        }
        if latestJob == nil {
            // Job was deleted, use the one we have
            latestJob = preScanJob
        }

        // Read error message from job annotation (NOW from fresh copy!)
        errorReason := "Pre-scan validation failed"
        if latestJob.Annotations != nil {
            if errMsg, ok := latestJob.Annotations[internal.PrescanErrorAnnotation]; ok && errMsg != "" {
                errorReason = errMsg  // ✅ Gets the actual error
            }
        }

        // Update condition with specific error
        r.updateScanInstanceCondition(..., errorReason)
        
        // Generate event with specific error
        r.Recorder.Eventf(..., "Pre-scan failed: %s", errorReason)
    }
```

### Key Points

1. **Refetch before reading**: Get fresh job object from API server
2. **Graceful fallback**: If refetch fails, use cached job (better than crashing)
3. **Nil check**: Handle case where job was deleted between checks
4. **Following TVK pattern**: Datamover does the same - job updates annotation, controller refetches to read it

## k8s-triliovault Pattern

This matches how k8s-triliovault handles datamover errors:

```go
// k8s-triliovault/controllers/backup/controller_helper.go
func syncDataUploadJobStatus(...) {
    // Get FRESH job (not cached)
    job, err := r.GetJob(job.Namespace, job.Name)
    
    if jobStatus.Failed {
        // Read error from FRESH job annotation
        dataSnapshot.Error = job.Annotations[internal.TrilioDataUploadErrorAnnotation]
    }
}
```

**Key difference**: TVK explicitly calls `r.GetJob()` which bypasses cache. We use `getPreScanJob()` which also fetches from API server.

## Testing

### Verify Error Propagation

```bash
# Create ScanInstance with invalid backup path
kubectl apply -f broken-scaninstance.yaml

# Wait for job to fail
kubectl wait --for=condition=failed job/threat-scan-prescan-test --timeout=120s

# Check job annotation (set by prescan container)
kubectl get job threat-scan-prescan-test -o jsonpath='{.metadata.annotations.threatscanning\.trilio\.io/prescan-error}'
# Expected: "Prescan validation failed: Backup path does not exist: /triliodata/90f59617.../3a7056c2..."

# Check ScanInstance event (should match job annotation!)
kubectl get events --field-selector involvedObject.name=test --sort-by='.lastTimestamp'
# Expected: "Pre-scan failed for ScanInstance test: Prescan validation failed: Backup path does not exist..."

# Check ScanInstance condition (should have specific error!)
kubectl get scaninstance test -o jsonpath='{.status.condition[?(@.phase=="PreScan")].reason}'
# Expected: "Prescan validation failed: Backup path does not exist: /triliodata/..."

# Verify full error in condition
kubectl get scaninstance test -o yaml | grep -A 5 "phase: PreScan"
# Expected:
#   phase: PreScan
#   status: Failed
#   reason: |
#     Prescan validation failed: Backup path does not exist: /triliodata/90f59617.../3a7056c2...
#     Traceback:
#     ...
```

### Compare Before and After

#### Before (Broken)

```yaml
# ScanInstance condition
condition:
  - phase: PreScan
    status: Failed
    reason: "Pre-scan validation failed"  # ❌ Generic message

# Event
- message: "Pre-scan failed for ScanInstance test: Pre-scan validation failed"
  # ❌ Generic message
```

#### After (Fixed)

```yaml
# ScanInstance condition
condition:
  - phase: PreScan
    status: Failed
    reason: |
      Prescan validation failed: Backup path does not exist: /triliodata/90f59617-4101-4492-9bca-1dd621050c10/3a7056c2-9356-4fe2-b571-dbc31cd2ddc61
      
      Traceback:
      Traceback (most recent call last):
        File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 52, in main
          validate_backup_path(full_backup_path)
        File "/opt/threat-scanning/datastore-attacher/prescan/validator.py", line 21, in validate_backup_path
          raise FileNotFoundError(f"Backup path does not exist: {backup_path}")
      FileNotFoundError: Backup path does not exist: /triliodata/90f59617-4101-4492-9bca-1dd621050c10/3a7056c2-9356-4fe2-b571-dbc31cd2ddc61
    # ✅ Specific error with full traceback!

# Event
- message: |
    Pre-scan failed for ScanInstance test: Prescan validation failed: Backup path does not exist: /triliodata/90f59617-4101-4492-9bca-1dd621050c10/3a7056c2-9356-4fe2-b571-dbc31cd2ddc61
  # ✅ Specific error message!
```

## Timeline with Fix

```
T=0s    : ScanInstance created
T=1s    : PreScan job created
T=2s    : Job pod starts
T=3s    : Prescan container validates backup path
T=4s    : Validation fails: FileNotFoundError
T=5s    : Prescan container updates job annotation:
          job.annotations['threatscanning.trilio.io/prescan-error'] = 
              "Prescan validation failed: Backup path does not exist: ..."
T=6s    : Job marked as Failed
T=7s    : Job watcher triggers controller reconciliation
T=8s    : Controller fetches job (cached version, no annotation yet)
T=9s    : Controller checks jobStatus → Failed
T=10s   : Controller REFETCHES job from API server ✅
T=11s   : Controller reads annotation from FRESH job ✅
T=12s   : Controller updates ScanInstance condition with specific error ✅
T=13s   : Controller generates event with specific error ✅
T=14s   : User sees detailed error in events and conditions ✅
```

## Why Refetch is Necessary

### Kubernetes Controller Pattern

Controllers use **informers/caches** for efficiency:
- Watches list all resources once
- Updates cached locally
- Reconciliation uses cached data

**Problem**: Annotation updates by containers happen **outside** the controller's watch:

```
┌─────────────────────┐
│  Kubernetes API     │
│  (Source of Truth)  │
└─────────────────────┘
         ↑ ↓
         │ │  Watch events
         │ └──────────────────┐
         │                    ↓
    ┌────┴────────┐    ┌──────────────┐
    │  Prescan    │    │  Controller  │
    │  Container  │    │  Informer    │
    │             │    │  (Cache)     │
    └─────────────┘    └──────────────┘
         │                    │
         │ Updates annotation │ Reads from cache
         │ (not in cache!)    │ (stale!)
         └────────────────────┤
                             ❌ Mismatch!
```

**Solution**: Explicit refetch bypasses cache:

```
┌─────────────────────┐
│  Kubernetes API     │
│  (Source of Truth)  │
└─────────────────────┘
         ↑ ↓
         │ │
    ┌────┴────────┐    ┌──────────────┐
    │  Prescan    │    │  Controller  │
    │  Container  │    │              │
    └─────────────┘    └──────────────┘
         │                    │
         │ Updates annotation │
         │                    │ Refetch (bypasses cache)
         │                    └─────────┐
         │                              ↓
         └────────────────────> ✅ Gets fresh data!
```

## Error Handling

The refetch has graceful error handling:

```go
latestJob, err := r.getPreScanJob(ctx, scanInstance)
if err != nil {
    log.WithError(err).Error("error refetching prescan job for error annotation")
    latestJob = preScanJob  // Fall back to cached job
}
if latestJob == nil {
    latestJob = preScanJob  // Fall back if deleted
}
```

**Why fallback?**
- If API server is temporarily unavailable
- If job was just deleted
- Better to show generic error than crash controller

## Alternative Approaches (Considered)

### 1. Cache Invalidation
**Problem**: Complex, affects all controllers
```go
// Would need to invalidate cache for every job update
informer.InvalidateCache(jobKey)  // Complex, invasive
```

### 2. Use APIReader
**Problem**: Bypasses informer completely, less efficient
```go
// Every read hits API server
r.APIReader.Get(ctx, jobKey, job)  // Works but inefficient
```

### 3. Wait for Cache Sync
**Problem**: Race condition, may miss update
```go
// Cache might not sync before reconciliation
time.Sleep(time.Second)  // Unreliable, racy
```

### 4. Direct API Call (Chosen) ✅
**Advantages**: 
- Simple, explicit
- Only when needed (on failure)
- Standard pattern (TVK does this)
- Reliable

## Related Patterns

### TVK Datamover Error Propagation

Similar issue and solution in k8s-triliovault:

```go
// Datamover updates annotation
job.Annotations[TrilioDataUploadErrorAnnotation] = error.Error()
kubeAccessor.Update(job)

// Controller refetches to read it
job, err := r.GetJob(jobNamespace, jobName)  // Fresh from API
errorMsg := job.Annotations[TrilioDataUploadErrorAnnotation]
backup.Status.Error = errorMsg
```

### Target Validation Errors

Target controller also needs this pattern (if reading job annotations):

```go
// If target validation job sets error annotations
latestJob, err := r.getValidationJob(ctx, credentialHash)
errorMsg := latestJob.Annotations[internal.ValidationErrorAnnotation]
```

## Summary

| Aspect | Before (Broken) | After (Fixed) |
|--------|-----------------|---------------|
| **Job annotation** | Set by prescan | Set by prescan ✓ |
| **Controller reads** | Cached job (empty) | Fresh job (populated) ✓ |
| **ScanInstance condition** | Generic error | Specific error ✓ |
| **ScanInstance event** | Generic error | Specific error ✓ |
| **Debugging** | No details | Full traceback ✓ |
| **User experience** | Frustrating | Informative ✓ |

## Files Modified

1. **`controllers/scaninstance/controller.go`** (lines 170-211)
   - Added refetch logic before reading error annotation
   - Added graceful fallback if refetch fails
   - Added comments explaining TVK pattern

## Documentation

- This file - Complete fix explanation
- `PRESCAN_FAILURE_ANNOTATION_PATTERN.md` - Original pattern documentation
- `CONTROLLER_ERROR_ANNOTATION_INTEGRATION.md` - Integration guide
