# Final Implementation: Universal Prescan Error Annotation

## Summary

Implemented a **universal error annotation mechanism** that catches **ALL exceptions** in the prescan job, truncates them to 128KB, and stores them in the job annotation before the job fails.

## Key Changes

### 1. Simplified Error Handler (`prescan/error_handler.py`)

**Changes:**
- ✅ Set `MAX_ERROR_SIZE = 128KB` (Kubernetes annotation limit)
- ✅ Removed `get_path_validation_error_message()` function (not needed)
- ✅ Simplified to handle all errors uniformly
- ✅ Added byte size logging for truncation visibility

**Key Function:**
```python
def update_job_error_annotation(job_name, job_namespace, error_msg):
    """
    Update job annotation with error message.
    Automatically truncates to 128KB.
    """
    truncated_error = truncate_error_string(error_msg)
    job.metadata.annotations[PRESCAN_ERROR_ANNOTATION] = truncated_error
    # ...
```

### 2. Universal Exception Handler (`prescan/cli.py`)

**Before:** Two separate exception handlers (path validation vs generic)

**After:** Single exception handler for ALL errors

```python
try:
    # All prescan logic...
    sys.exit(0)
    
except Exception as e:
    # Catch ALL exceptions - no special cases
    import traceback
    
    error_msg = f"Prescan validation failed: {str(e)}"
    error_details = traceback.format_exc()
    
    # Log with full traceback
    logging.error(error_msg)
    logging.error(f"Full traceback:\n{error_details}")
    
    # Update job annotation with error + traceback (auto-truncated to 128KB)
    full_error = f"{error_msg}\n\nTraceback:\n{error_details}"
    
    if job_name and job_namespace:
        update_job_error_annotation(job_name, job_namespace, full_error)
    else:
        logging.warning("JOB_NAME or JOB_NAMESPACE not set, cannot update job annotation")
    
    sys.exit(1)
```

### 3. Controller Reads Annotation (Already Implemented)

No changes needed - controller already reads the annotation correctly:

```go
case v1.Failed:
    errorReason := "Pre-scan validation failed"
    if preScanJob.Annotations != nil {
        if errMsg, ok := preScanJob.Annotations[internal.PrescanErrorAnnotation]; ok && errMsg != "" {
            errorReason = errMsg  // Uses annotation value
        }
    }
    // Update condition and generate event
```

### 4. Watch Configuration (Already Optimal)

**Question:** Does annotation update trigger reconciliation?
**Answer:** No, and that's perfect!

The watch filters are already optimal:
- **ScanInstance**: Only reconcile on spec changes (generation change)
- **Job**: Only reconcile on **status** changes (Active/Succeeded/Failed)
- **Job annotations**: Not watched, no reconciliation triggered

**This is ideal because:**
1. Prescan job updates annotation (no reconciliation)
2. Prescan job exits with code 1 (status changes to Failed)
3. Status change triggers reconciliation (controller reads annotation)
4. Single reconciliation with annotation already present

## Benefits of Universal Handler

### 1. Catches Everything
```python
# Path validation errors
raise FileNotFoundError("Backup path does not exist: /triliodata/...")

# Metadata parsing errors
raise ValueError("Invalid JSON in tvk-meta.json: ...")

# K8s API errors
raise RuntimeError("Failed to update ScanInstance CR")

# Python runtime errors
KeyError, AttributeError, TypeError, etc.
```

**All caught by single `except Exception` handler!**

### 2. Includes Traceback
```
Prescan validation failed: Backup path does not exist: /triliodata/plan1/backup123

Traceback:
  File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 55, in main
    validate_backup_path(full_backup_path)
  File "/opt/threat-scanning/datastore-attacher/prescan/validator.py", line 21, in validate_backup_path
    raise FileNotFoundError(f"Backup path does not exist: {backup_path}")
FileNotFoundError: Backup path does not exist: /triliodata/plan1/backup123
```

### 3. Auto-Truncated
- Errors longer than 128KB are automatically truncated
- Suffix indicates truncation with original size
- Prevents annotation size limit issues

### 4. No Special Cases
- No need to categorize errors
- No need to format different error types
- Simple, maintainable code

## Error Annotation Examples

### Example 1: Path Not Found (Full Error + Traceback)

```yaml
metadata:
  annotations:
    threatscanning.trilio.io/prescan-error: |
      Prescan validation failed: Backup path does not exist: /triliodata/plan1/backup123
      
      Traceback:
        File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 55, in main
          validate_backup_path(full_backup_path)
        File "/opt/threat-scanning/datastore-attacher/prescan/validator.py", line 21, in validate_backup_path
          raise FileNotFoundError(f"Backup path does not exist: {backup_path}")
      FileNotFoundError: Backup path does not exist: /triliodata/plan1/backup123
```

### Example 2: Invalid JSON (Full Error + Traceback)

```yaml
metadata:
  annotations:
    threatscanning.trilio.io/prescan-error: |
      Prescan validation failed: Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)
      
      Traceback:
        File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 80, in main
          metadata = detector.extract_metadata(full_backup_path, args.backup_uid)
        File "/opt/threat-scanning/datastore-attacher/shared/backup_detection/tvk_detector.py", line 168, in _extract_namespace_backup_metadata
          raise ValueError(f"Invalid JSON in tvk-meta.json: {str(e)}")
      ValueError: Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)
```

### Example 3: Truncated Error (>128KB)

```yaml
metadata:
  annotations:
    threatscanning.trilio.io/prescan-error: |
      Prescan validation failed: Some very long error...
      
      Traceback:
        File ...
        (many lines of traceback)
      
      ... [truncated, original size: 256000 bytes]
```

## Watch Configuration Analysis

### Current Predicates (Already Correct!)

**ScanInstance Updates:**
```go
if _, ok := e.ObjectNew.DeepCopyObject().(*v1.ScanInstance); ok {
    return e.ObjectNew.GetGeneration() != e.ObjectOld.GetGeneration()
}
```
✅ Only triggers on **spec changes** (generation change)
✅ Status/annotation updates DON'T trigger reconciliation

**Job Updates:**
```go
if currentJobObj, ok := e.ObjectNew.DeepCopyObject().(*batchv1.Job); ok {
    previousJobObj := e.ObjectOld.DeepCopyObject().(*batchv1.Job)
    
    // Only reconcile if job status changed
    if previousJobObj.Status.Active != currentJobObj.Status.Active ||
        previousJobObj.Status.Succeeded != currentJobObj.Status.Succeeded ||
        previousJobObj.Status.Failed != currentJobObj.Status.Failed {
        return true
    }
    return false
}
```
✅ Only triggers on **status field changes** (Active/Succeeded/Failed)
✅ Annotation updates DON'T trigger reconciliation

### Why This Is Perfect

**Timing Sequence:**
```
1. Prescan job running (status.active=1)
   ↓
2. Exception occurs
   ↓
3. update_job_error_annotation() called
   ↓ [Annotation updated - NO reconciliation triggered]
4. Job annotation set: "threatscanning.trilio.io/prescan-error: ..."
   ↓
5. sys.exit(1) called
   ↓ [Status change - YES reconciliation triggered]
6. K8s marks job as failed (status.failed=1)
   ↓
7. Job status change triggers reconciliation
   ↓
8. Controller reads annotation (already set in step 4)
   ↓
9. ScanInstance updated with error from annotation
```

**Result:**
- ✅ Single reconciliation per job failure
- ✅ Annotation always present when controller reconciles
- ✅ No race conditions
- ✅ No unnecessary reconciliations

## Files Modified

| File | Status | Changes |
|------|--------|---------|
| `prescan/error_handler.py` | ✅ Updated | Changed MAX_ERROR_SIZE to 128KB, simplified |
| `prescan/cli.py` | ✅ Updated | Single universal exception handler |
| `pkg/helpers/job_helper.go` | ✅ Updated | Added JOB_NAME/JOB_NAMESPACE env vars |
| `controllers/scaninstance/controller.go` | ✅ Updated | Reads annotation on failure |
| `internal/constants.go` | ✅ Updated | Added PrescanErrorAnnotation constant |

## Syntax Verification

✅ **Python:** Compiled successfully
```bash
python3 -m py_compile prescan/cli.py prescan/error_handler.py
# Exit code: 0
```

✅ **Go:** Built successfully
```bash
go build ./controllers/scaninstance/... ./internal/...
# Exit code: 0
```

## Error Annotation Size Limit

**Kubernetes Annotation Limit:** ~256KB total for all annotations combined
**Our Limit:** 128KB per error annotation (safe margin)
**Truncation:** Automatic with size indicator

**Example truncation:**
```
Prescan validation failed: ...
Traceback:
  File ...
  (first 128KB of content)

... [truncated, original size: 300000 bytes]
```

## Benefits

### 1. Universal Coverage
- ✅ Path validation errors
- ✅ JSON parsing errors
- ✅ K8s API errors
- ✅ Python runtime errors
- ✅ ANY exception type

### 2. Full Debug Info
- Error message
- Full Python traceback
- File names and line numbers
- Exception type and details

### 3. Size-Safe
- Auto-truncation to 128KB
- Prevents annotation size errors
- Indicates when truncated

### 4. Efficient Reconciliation
- Annotation update doesn't trigger reconciliation
- Status change triggers single reconciliation
- No race conditions

### 5. Simple Code
- Single exception handler
- No error categorization needed
- Easy to maintain

## User Experience

### Check ScanInstance Status
```bash
kubectl get scaninstance test-scan -o jsonpath='{.status.condition[?(@.phase=="PreScan")].reason}'
```

**Output (path error):**
```
Prescan validation failed: Backup path does not exist: /triliodata/plan1/backup123

Traceback:
  File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 55, in main
    validate_backup_path(full_backup_path)
  File "/opt/threat-scanning/datastore-attacher/prescan/validator.py", line 21, in validate_backup_path
    raise FileNotFoundError(f"Backup path does not exist: {backup_path}")
FileNotFoundError: Backup path does not exist: /triliodata/plan1/backup123
```

**Output (metadata error):**
```
Prescan validation failed: Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)

Traceback:
  File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 80, in main
    metadata = detector.extract_metadata(full_backup_path, args.backup_uid)
  File ".../tvk_detector.py", line 168, in _extract_namespace_backup_metadata
    raise ValueError(f"Invalid JSON in tvk-meta.json: {str(e)}")
ValueError: Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)
```

### Check Kubernetes Event
```bash
kubectl describe scaninstance test-scan
```

**Output:**
```
Events:
  Type     Reason          Message
  ----     ------          -------
  Warning  PreScanFailed   Pre-scan failed for ScanInstance test-scan: Prescan validation failed: Backup path does not exist: /triliodata/plan1/backup123
                           
                           Traceback:
                             File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 55, in main
                               validate_backup_path(full_backup_path)
                             ...
```

## Implementation Complete

✅ **Simplified**: Single exception handler for all errors
✅ **Complete**: Includes error message + full traceback
✅ **Size-Safe**: Auto-truncated to 128KB
✅ **Efficient**: No unnecessary reconciliations
✅ **Debuggable**: Full Python traceback available
✅ **Syntax-Verified**: All code compiles successfully

**Ready for deployment and testing!**

## Next Steps

1. Rebuild datastore-attacher image
2. Deploy updated controller
3. Test with various failure scenarios:
   - Path not found
   - Invalid JSON
   - K8s API failures
   - Python runtime errors
4. Verify annotation truncation works for large errors
