# Path Validation Error Annotation Implementation

## Overview

Implemented a simplified error annotation mechanism for the prescan job, focusing **only on path validation errors** for now. When the backup path validation fails, the error is stored in a job annotation that the controller can read and display to users.

## Implementation Summary

### 1. New File: `prescan/error_handler.py`

**Purpose:** Handles error annotation updates on the prescan job

**Key Functions:**
- `truncate_error_string(err_str, max_size=256KB)` - Truncates errors to annotation size limit
- `update_job_error_annotation(job_name, job_namespace, error_msg)` - Updates job annotation
- `get_path_validation_error_message(exception)` - Formats path validation errors

**Annotation Used:**
```python
PRESCAN_ERROR_ANNOTATION = "threatscanning.trilio.io/prescan-error"
```

### 2. Updated: `prescan/cli.py`

**Changes:**
- Added import of error handler functions
- Get `JOB_NAME` and `JOB_NAMESPACE` from environment variables
- Separate exception handling for path validation vs generic errors
- Update job annotation when path validation fails

**Error Handling:**
```python
try:
    # ... prescan logic ...
    
except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
    # Path validation errors - set specific error message
    error_msg = get_path_validation_error_message(e)
    # error_msg = "Backup path is inaccessible: <details>"
    
    if job_name and job_namespace:
        update_job_error_annotation(job_name, job_namespace, error_msg)
    
    sys.exit(1)
    
except Exception as e:
    # Generic errors - keep original message
    error_msg = f"Prescan validation failed: {str(e)}"
    
    if job_name and job_namespace:
        update_job_error_annotation(job_name, job_namespace, error_msg)
    
    sys.exit(1)
```

### 3. Updated: `pkg/helpers/job_helper.go`

**Changes:**
Added environment variables to prescan container to expose job metadata:

```go
Env: []corev1.EnvVar{
    {
        Name: "JOB_NAME",
        ValueFrom: &corev1.EnvVarSource{
            FieldRef: &corev1.ObjectFieldSelector{
                FieldPath: "metadata.labels['job-name']",
            },
        },
    },
    {
        Name: "JOB_NAMESPACE",
        ValueFrom: &corev1.EnvVarSource{
            FieldRef: &corev1.ObjectFieldSelector{
                FieldPath: "metadata.namespace",
            },
        },
    },
},
```

## Error Message Format

### Path Validation Errors

All three path validation exceptions are mapped to the same user-friendly message:

| Exception Type | Error Message Format |
|---------------|---------------------|
| `FileNotFoundError` | `Backup path is inaccessible: Backup path does not exist: {path}` |
| `NotADirectoryError` | `Backup path is inaccessible: Backup path is not a directory: {path}` |
| `PermissionError` | `Backup path is inaccessible: Backup path is not readable: {path}` |

**Example:**
```
Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123
```

### Generic Errors

All other errors maintain their original message:
```
Prescan validation failed: tvk-meta.json not found at /triliodata/plan1/backup123/tvk-meta.json
```

## Controller Integration (Next Step)

The controller needs to be updated to:

1. **Read the annotation** when prescan job fails
2. **Update ScanInstance condition** with the error
3. **Generate Kubernetes event** for visibility

**Example controller code:**
```go
func (r *ScanInstanceReconciler) handlePrescanJobStatus(
    ctx context.Context,
    scanInstance *threatv1.ScanInstance,
    job *batchv1.Job,
) error {
    
    if isJobFailed(job) {
        // Read error from annotation
        errorMsg := "Prescan job failed"
        if job.Annotations != nil {
            if errAnnotation, ok := job.Annotations["threatscanning.trilio.io/prescan-error"]; ok {
                errorMsg = errAnnotation
            }
        }
        
        // Update condition
        updateCondition(scanInstance, threatv1.ScanInstanceCondition{
            Phase:     threatv1.PrescanPhase,
            Status:    threatv1.FailedStatus,
            Reason:    errorMsg,
            Timestamp: metav1.Now(),
        })
        
        // Generate event
        r.Recorder.Event(
            scanInstance,
            corev1.EventTypeWarning,
            "PrescanFailed",
            errorMsg,
        )
        
        // Update overall status
        scanInstance.Status.Status = threatv1.FailedStatus
    }
    
    return r.Status().Update(ctx, scanInstance)
}
```

## Testing

### Test Case 1: Path Not Found

**Setup:**
```bash
# Create ScanInstance with non-existent backup path
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-path-not-found
spec:
  backupTarget:
    name: my-target
  backupRef:
    path: non-existent-path
    uid: fake-uid-123
EOF
```

**Expected Results:**
1. Prescan job fails
2. Job annotation contains: `Backup path is inaccessible: Backup path does not exist: /triliodata/non-existent-path`
3. ScanInstance condition shows the error
4. Kubernetes event is generated

**Verification:**
```bash
# Check job annotation
kubectl get job prescan-test-path-not-found -n <namespace> -o jsonpath='{.metadata.annotations.threatscanning\.trilio\.io/prescan-error}'

# Check prescan logs
kubectl logs job/prescan-test-path-not-found -n <namespace>

# Check ScanInstance status (after controller integration)
kubectl get scaninstance test-path-not-found -o yaml

# Check events (after controller integration)
kubectl describe scaninstance test-path-not-found
```

### Test Case 2: Permission Denied

**Setup:**
Create a backup directory with restricted permissions:
```bash
# On the target storage
mkdir -p /triliodata/restricted-backup
chmod 000 /triliodata/restricted-backup
```

**Expected Results:**
Job annotation contains: `Backup path is inaccessible: Backup path is not readable: /triliodata/restricted-backup`

## Files Modified

1. ✅ **New:** `datastore-attacher/prescan/error_handler.py` - Error handling utilities
2. ✅ **Updated:** `datastore-attacher/prescan/cli.py` - Added error annotation logic
3. ✅ **Updated:** `pkg/helpers/job_helper.go` - Added JOB_NAME and JOB_NAMESPACE env vars
4. ⏳ **TODO:** `controllers/scaninstance/controller.go` or `controller_helper.go` - Read annotation and update ScanInstance

## Syntax Verification

✅ Python syntax verified:
```bash
python3 -m py_compile prescan/cli.py prescan/error_handler.py
# Exit code: 0 (success)
```

## Benefits

1. **Clear Error Messages**: Users see "Backup path is inaccessible" instead of generic "Job failed"
2. **No Pod Logs Required**: Error is in annotation, visible in CR status and events
3. **Persistent**: Annotation survives pod deletion
4. **Extensible**: Easy to add more error categories later
5. **Follows Best Practices**: Consistent with k8s-triliovault datamover pattern

## Next Steps

1. ✅ Implement basic error annotation (Done)
2. ⏳ Update controller to read annotation and update ScanInstance
3. ⏳ Test with real path validation failures
4. ⏳ Add more error categories as needed (metadata errors, etc.)
5. ⏳ Rebuild and deploy datastore-attacher image

## Example Output

### Prescan Log (Failure)
```
INFO: Validating backup path: /triliodata/plan1/backup123
ERROR: Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123
Traceback (most recent call last):
  File "/opt/threat-scanning/datastore-attacher/prescan/cli.py", line 47, in main
    validate_backup_path(full_backup_path)
  File "/opt/threat-scanning/datastore-attacher/prescan/validator.py", line 21, in validate_backup_path
    raise FileNotFoundError(f"Backup path does not exist: {backup_path}")
FileNotFoundError: Backup path does not exist: /triliodata/plan1/backup123
INFO: Updated job prescan-test-scan with error annotation
```

### Job Annotation
```yaml
metadata:
  annotations:
    threatscanning.trilio.io/prescan-error: "Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123"
```

### ScanInstance Status (After Controller Integration)
```yaml
status:
  status: Failed
  condition:
  - phase: PreScan
    status: Failed
    reason: "Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123"
    timestamp: "2026-02-16T12:00:00Z"
```

### Kubernetes Event (After Controller Integration)
```bash
$ kubectl describe scaninstance test-scan
...
Events:
  Type     Reason          Message
  ----     ------          -------
  Warning  PrescanFailed   Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123
```

## Notes

- Currently implements **only path validation errors**
- Other errors (metadata parsing, K8s API, etc.) still get generic "Prescan validation failed" message
- Can be extended later to categorize more error types
- Error message format is user-friendly and actionable
