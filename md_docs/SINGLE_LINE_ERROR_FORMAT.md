# Clean Error Message Pattern

## Problem

Error messages need to be concise and readable in Kubernetes events and conditions, while full debugging details (like tracebacks) should be available in logs.

### Anti-pattern: Everything in Annotation

```python
# ❌ BAD: Putting traceback in annotation
full_error = f"{error_msg}\n\nTraceback:\n{error_details}"
update_job_error_annotation(job_name, job_namespace, full_error)
```

**Problems:**
- Annotation becomes huge and hard to read
- Events and conditions show messy multi-line text
- Kubernetes UI displays are cluttered
- Traceback isn't needed for user-facing display

## Solution: Logs for Details, Annotation for Summary

### Pattern

1. **Log full traceback** for debugging
2. **Set concise error** in annotation for display

```python
except Exception as e:
    error_msg = f"Prescan validation failed: {str(e)}"
    error_details = traceback.format_exc()
    
    # Full traceback in logs ✅
    logging.error(error_msg)
    logging.error(f"Full traceback:\n{error_details}")
    
    # Concise error in annotation ✅
    update_job_error_annotation(job_name, job_namespace, error_msg)
```

## Implementation

### Python CLI - Clean Error Messages

**File**: `datastore-attacher/prescan/cli.py`

```python
except Exception as e:
    error_msg = f"Prescan validation failed: {str(e)}"
    error_details = traceback.format_exc()
    
    # Log error with full traceback for debugging
    logging.error(error_msg)
    logging.error(f"Full traceback:\n{error_details}")
    
    # Set ONLY the error message in annotation (no traceback)
    # Traceback is in logs for debugging - annotation is for user-facing display
    if job_name and job_namespace:
        update_job_error_annotation(job_name, job_namespace, error_msg)
```

**Benefits:**
- ✅ Concise, readable error message
- ✅ Full traceback in logs for debugging
- ✅ Clean display in events/conditions
- ✅ No multi-line formatting issues

### Controller - Simple Display

**File**: `controllers/scaninstance/controller.go`

```go
// Read error message from job annotation if available
// Prescan sets concise error message (traceback is in job logs)
errorReason := "Pre-scan validation failed"
if latestJob.Annotations != nil {
    if errMsg, ok := latestJob.Annotations[internal.PrescanErrorAnnotation]; ok && errMsg != "" {
        errorReason = errMsg  // Already clean, single-line
    }
}

// Update condition and event with clean error
r.updateScanInstanceCondition(..., errorReason)
r.Recorder.Eventf(..., errorReason)
```

No need for string manipulation or multi-line handling!

## Example Error Messages

### Path Not Found

```yaml
# Annotation (clean)
threatscanning.trilio.io/prescan-error: "Prescan validation failed: Backup path does not exist: /triliodata/90f59617-4101-4492-9bca-1dd621050c10/3a7056c2-9356-4fe2-b571-dbc31cd2ddc61"

# Job logs (detailed)
ERROR: Prescan validation failed: Backup path does not exist: /triliodata/90f59617-4101-4492-9bca-1dd621050c10/3a7056c2-9356-4fe2-b571-dbc31cd2ddc61
ERROR: Full traceback:
Traceback (most recent call last):
  File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 52, in main
    validate_backup_path(full_backup_path)
  File "/opt/threat-scanning/datastore-attacher/prescan/validator.py", line 21, in validate_backup_path
    raise FileNotFoundError(f"Backup path does not exist: {backup_path}")
FileNotFoundError: Backup path does not exist: /triliodata/90f59617-4101-4492-9bca-1dd621050c10/3a7056c2-9356-4fe2-b571-dbc31cd2ddc61

# Event (clean)
Warning  PreScanFailed  2m  threat-scanning-controller  Pre-scan failed for ScanInstance test: Prescan validation failed: Backup path does not exist: /triliodata/90f59617.../3a7056c2...

# Condition (clean)
- phase: PreScan
  status: Failed
  reason: "Prescan validation failed: Backup path does not exist: /triliodata/90f59617.../3a7056c2..."
```

### Invalid JSON

```yaml
# Annotation (clean)
threatscanning.trilio.io/prescan-error: "Prescan validation failed: Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)"

# Job logs (detailed)
ERROR: Prescan validation failed: Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)
ERROR: Full traceback:
Traceback (most recent call last):
  File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 76, in main
    metadata = detector.extract_metadata(full_backup_path, args.backup_uid)
  File ".../tvk_detector.py", line 89, in extract_metadata
    meta = json.load(f)
json.JSONDecodeError: Expecting value: line 5 column 1 (char 123)
```

### Target Not Found

```yaml
# Annotation (clean)
threatscanning.trilio.io/prescan-error: "Prescan validation failed: Target demo-target not found"

# Job logs (detailed)
ERROR: Prescan validation failed: Target demo-target not found
ERROR: Full traceback:
Traceback (most recent call last):
  File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 57, in main
    target_cr = k8s_client.get_target(args.target_name)
RuntimeError: Target demo-target not found
```

## Benefits

### 1. Clean Display

**Annotation:**
```
Prescan validation failed: Backup path does not exist: /triliodata/abc/def
```

**Event:**
```
Pre-scan failed: Prescan validation failed: Backup path does not exist: /triliodata/abc/def
```

**Condition:**
```yaml
reason: "Prescan validation failed: Backup path does not exist: /triliodata/abc/def"
```

All clean, single-line, readable! ✅

### 2. Full Details Available

```bash
# For debugging, check job logs
kubectl logs job/threat-scan-prescan-test
# Shows full traceback
```

### 3. Matches k8s-triliovault Pattern

```go
// TVK datamover sets concise error
if opErr != nil {
    job.Annotations[TrilioDataUploadErrorAnnotation] = opErr.Error()
}
```

TVK doesn't put tracebacks in annotations either!

## Testing

### Verify Clean Display

```bash
# Create ScanInstance with invalid path
kubectl apply -f broken-scaninstance.yaml

# Check annotation (clean, no traceback)
kubectl get job threat-scan-prescan-test -o jsonpath='{.metadata.annotations.threatscanning\.trilio\.io/prescan-error}'
# Expected: "Prescan validation failed: Backup path does not exist: /triliodata/..."

# Check event (clean)
kubectl get events --field-selector involvedObject.name=test
# Expected: Single-line error without traceback

# Check condition (clean)
kubectl get scaninstance test -o jsonpath='{.status.condition[?(@.phase=="PreScan")].reason}'
# Expected: Clean error message

# Check logs for full traceback
kubectl logs job/threat-scan-prescan-test
# Expected:
# ERROR: Prescan validation failed: ...
# ERROR: Full traceback:
# Traceback (most recent call last):
#   ...
```

## Comparison

### Before (Messy)

```yaml
# Annotation with traceback
prescan-error: |
  Prescan validation failed: Backup path does not exist: /triliodata/abc
  
  Traceback:
  Traceback (most recent call last):
    File "/opt/cli.py", line 52, in main
      validate_backup_path(path)
    File "/opt/validator.py", line 21, in validate
      raise FileNotFoundError(...)
  FileNotFoundError: Backup path does not exist: /triliodata/abc

# Event (messy multi-line)
Message: |
  Pre-scan failed: Prescan validation failed: Backup path...
  
  Traceback:
  Traceback (most recent call last):
  ...
```

### After (Clean)

```yaml
# Annotation without traceback
prescan-error: "Prescan validation failed: Backup path does not exist: /triliodata/abc"

# Event (clean single-line)
Message: "Pre-scan failed: Prescan validation failed: Backup path does not exist: /triliodata/abc"

# Full traceback in logs
$ kubectl logs job/prescan-test
ERROR: Full traceback:
Traceback (most recent call last):
  ...
```

## Files Modified

1. **`datastore-attacher/prescan/cli.py`** (lines 177-195)
   - Removed traceback from annotation
   - Keep full traceback in logs only
   - Set only concise error message in annotation

2. **`controllers/scaninstance/controller.go`** (lines 187-191)
   - Simplified comment
   - No need for multi-line handling
   - Direct use of error message

3. **`internal/utils.go`** (deleted)
   - No longer needed
   - No string manipulation required

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Annotation** | Multi-line with traceback | Single-line concise error |
| **Logs** | Same as annotation | Full traceback for debugging |
| **Events** | Messy multi-line | Clean single-line |
| **Conditions** | Messy multi-line | Clean single-line |
| **UI Display** | Broken/cluttered | Correct/clean |
| **Debugging** | Limited to annotation | Full details in logs |
| **TVK alignment** | Different | Matches ✅ |

The error handling is now cleaner, more maintainable, and matches the k8s-triliovault pattern!

## Implementation

### 1. Python CLI - Format Error on Creation

**File**: `datastore-attacher/prescan/cli.py`

```python
except Exception as e:
    error_msg = f"Prescan validation failed: {str(e)}"
    error_details = traceback.format_exc()
    
    # Format error for annotation: single-line with condensed traceback
    # Replace newlines with pipe separator for better readability
    traceback_lines = [line.strip() for line in error_details.split('\n') if line.strip()]
    condensed_traceback = ' | '.join(traceback_lines[:5])  # First 5 lines
    
    # Create single-line error message
    if len(traceback_lines) > 5:
        full_error = f"{error_msg} | {condensed_traceback} | ... (see job logs for full traceback)"
    else:
        full_error = f"{error_msg} | {condensed_traceback}"
    
    update_job_error_annotation(job_name, job_namespace, full_error)
```

**Benefits:**
- ✅ First 5 lines of traceback (most relevant)
- ✅ Single-line format with `|` separator
- ✅ Ellipsis for truncated tracebacks
- ✅ Reference to job logs for full details

### 2. Controller - Additional Safety Layer

**File**: `controllers/scaninstance/controller.go`

```go
// Read error message from job annotation
errorReason := "Pre-scan validation failed"
if latestJob.Annotations != nil {
    if errMsg, ok := latestJob.Annotations[internal.PrescanErrorAnnotation]; ok && errMsg != "" {
        errorReason = errMsg
        // Ensure single-line for better event/condition readability
        // If prescan sends multi-line (shouldn't happen), condense it
        errorReason = internal.ConvertToSingleLine(errorReason)
    }
}
```

**File**: `internal/utils.go`

```go
// ConvertToSingleLine converts multi-line error messages to single line
// by replacing newlines with " | " separator
func ConvertToSingleLine(multiLineStr string) string {
    if multiLineStr == "" {
        return multiLineStr
    }

    // Split by newlines and filter out empty lines
    lines := strings.Split(multiLineStr, "\n")
    var nonEmptyLines []string
    for _, line := range lines {
        trimmed := strings.TrimSpace(line)
        if trimmed != "" {
            nonEmptyLines = append(nonEmptyLines, trimmed)
        }
    }

    // Join with " | " separator
    return strings.Join(nonEmptyLines, " | ")
}
```

**Benefits:**
- ✅ Safety layer if prescan still sends multi-line
- ✅ Consistent formatting across all errors
- ✅ Reusable for other error scenarios

## Example Error Messages

### Path Not Found

```
Prescan validation failed: Backup path does not exist: /triliodata/90f59617-4101-4492-9bca-1dd621050c10/3a7056c2-9356-4fe2-b571-dbc31cd2ddc61 | Traceback (most recent call last): | File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 52, in main | validate_backup_path(full_backup_path) | File "/opt/threat-scanning/datastore-attacher/prescan/validator.py", line 21, in validate_backup_path | ... (see job logs for full traceback)
```

### Invalid JSON

```
Prescan validation failed: Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123) | Traceback (most recent call last): | File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 76, in main | metadata = detector.extract_metadata(full_backup_path, args.backup_uid) | File ".../tvk_detector.py", line 89, in extract_metadata | ... (see job logs for full traceback)
```

### Kubernetes API Error

```
Prescan validation failed: Failed to update ScanInstance CR: (403) Forbidden | Traceback (most recent call last): | File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 147, in main | success = k8s_client.patch_scan_instance(...) | File ".../k8s/client.py", line 234, in patch_scan_instance | ... (see job logs for full traceback)
```

## Benefits

### 1. Better Readability

**Before:**
```bash
$ kubectl get events
LAST SEEN   TYPE      REASON          OBJECT               MESSAGE
2m          Warning   PreScanFailed   scaninstance/test    Pre-scan failed:
                                                            Prescan validation failed: Backup path...
                                                            
                                                            Traceback:
                                                            Traceback (most recent call last):
                                                            ...
```

**After:**
```bash
$ kubectl get events
LAST SEEN   TYPE      REASON          OBJECT               MESSAGE
2m          Warning   PreScanFailed   scaninstance/test    Pre-scan failed: Prescan validation failed: Backup path does not exist: /triliodata/90f59617.../3a7056c2... | Traceback: ... | validate_backup_path() | ... (see job logs for full traceback)
```

### 2. Better Display in UIs

Single-line errors display correctly in:
- ✅ Kubernetes Dashboard
- ✅ kubectl get events
- ✅ Monitoring/alerting systems
- ✅ Log aggregation tools

### 3. Full Details Still Available

```bash
# For full traceback, check job logs
kubectl logs job/threat-scan-prescan-test
```

## Testing

### Test Error Formatting

```bash
# Create ScanInstance with invalid path
kubectl apply -f broken-scaninstance.yaml

# Wait for failure
kubectl wait --for=condition=failed job/threat-scan-prescan-test --timeout=120s

# Check job annotation (single-line)
kubectl get job threat-scan-prescan-test -o jsonpath='{.metadata.annotations.threatscanning\.trilio\.io/prescan-error}'
# Expected: Single line with | separators

# Check event (single-line)
kubectl get events --field-selector involvedObject.name=test
# Expected: Readable single-line error

# Check full logs if needed
kubectl logs job/threat-scan-prescan-test
# Expected: Full multi-line traceback for debugging
```

### Verify Different Error Types

```bash
# 1. Path not found
kubectl apply -f scaninstance-bad-path.yaml
# Error: "... | Backup path does not exist: ... | Traceback | ..."

# 2. Invalid JSON
kubectl apply -f scaninstance-corrupt-metadata.yaml
# Error: "... | Invalid JSON in tvk-meta.json | Traceback | ..."

# 3. K8s API error
kubectl apply -f scaninstance-no-permissions.yaml
# Error: "... | Failed to update ScanInstance | (403) Forbidden | ..."
```

## Format Specification

### Structure

```
<error_msg> | <traceback_line_1> | <traceback_line_2> | ... | <traceback_line_5> | ... (see job logs for full traceback)
```

### Rules

1. **Separator**: Use ` | ` (space-pipe-space) between components
2. **Traceback limit**: First 5 lines only
3. **Truncation indicator**: ` | ... (see job logs for full traceback)` if truncated
4. **Empty lines**: Stripped out
5. **Whitespace**: Trimmed from each line

### Example Breakdown

```
Input (multi-line):
---
Prescan validation failed: Backup path does not exist: /triliodata/abc/def

Traceback:
Traceback (most recent call last):
  File "/opt/cli.py", line 52, in main
    validate_backup_path(path)
  File "/opt/validator.py", line 21, in validate_backup_path
    raise FileNotFoundError(f"Backup path does not exist: {path}")
FileNotFoundError: Backup path does not exist: /triliodata/abc/def
---

Output (single-line):
---
Prescan validation failed: Backup path does not exist: /triliodata/abc/def | Traceback: | Traceback (most recent call last): | File "/opt/cli.py", line 52, in main | validate_backup_path(path) | ... (see job logs for full traceback)
---
```

## k8s-triliovault Comparison

TVK also uses single-line error messages in annotations:

```go
// k8s-triliovault/pkg/datamover/datamover.go
if opErr != nil {
    // Error is already single-line string
    truncatedError := truncateErrorString(opErr.Error())
    job.Annotations[TrilioDataUploadErrorAnnotation] = truncatedError
}
```

TVK errors are naturally single-line because Go's `error.Error()` returns strings without newlines.

We follow the same pattern but with additional traceback information for Python errors.

## Files Modified

1. **`datastore-attacher/prescan/cli.py`** (lines 177-200)
   - Format errors as single-line with condensed traceback
   - Limit to first 5 traceback lines
   - Add truncation indicator

2. **`controllers/scaninstance/controller.go`** (lines 187-194)
   - Add `ConvertToSingleLine()` call as safety layer
   - Ensure all errors are single-line before display

3. **`internal/utils.go`** (new file)
   - Added `ConvertToSingleLine()` helper function
   - Reusable for other controllers

## Migration

### For Existing Errors

Old multi-line errors in existing job annotations will be automatically converted when the controller reads them due to the safety layer.

### For New Deployments

All new errors will be single-line from the start.

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Format** | Multi-line with newlines | Single-line with `\|` |
| **Traceback** | Full (100+ lines) | First 5 lines + ellipsis |
| **Events** | Hard to read | Clean and readable |
| **UI display** | Broken formatting | Correct display |
| **Full details** | In annotation | In job logs |
| **K8s friendly** | No | Yes ✅ |
