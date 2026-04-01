# Controller Integration for Prescan Error Annotations

## Overview

Updated the ScanInstance controller to read error messages from prescan job annotations and reflect them in the ScanInstance status and Kubernetes events.

## Changes Made

### 1. Added Constant: `internal/constants.go`

```go
// PrescanErrorAnnotation is the annotation key for prescan job error messages
PrescanErrorAnnotation = "threatscanning.trilio.io/prescan-error"
```

### 2. Updated Controller: `controllers/scaninstance/controller.go`

**Modified the `Failed` case in prescan job status handling:**

**Before:**
```go
case v1.Failed:
    if !scanInstance.HasCondition(v1.PreScan, v1.Failed) {
        if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Failed,
            "Pre-scan validation failed"); uErr != nil {
            return ctrl.Result{}, uErr
        }

        r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanFailed",
            "Pre-scan failed for ScanInstance: %s", scanInstance.Name)
        
        // ...
    }
```

**After:**
```go
case v1.Failed:
    if !scanInstance.HasCondition(v1.PreScan, v1.Failed) {
        // Read error message from job annotation if available
        errorReason := "Pre-scan validation failed"
        if preScanJob.Annotations != nil {
            if errMsg, ok := preScanJob.Annotations[internal.PrescanErrorAnnotation]; ok && errMsg != "" {
                errorReason = errMsg
            }
        }

        if uErr := r.updateScanInstanceCondition(ctx, scanInstance, originalScanInstance, v1.PreScan, v1.Failed,
            errorReason); uErr != nil {
            return ctrl.Result{}, uErr
        }

        // Generate event with the error message
        r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "PreScanFailed",
            "Pre-scan failed for ScanInstance %s: %s", scanInstance.Name, errorReason)
        
        // ...
    }
```

## How It Works

### Flow:

1. **Prescan Job Fails** → Python code catches exception (e.g., path validation error)
2. **Job Annotation Updated** → Python updates job's annotation with error message
3. **Controller Watches Job** → Job status change triggers reconciliation
4. **Controller Reads Annotation** → Extracts error message from `threatscanning.trilio.io/prescan-error`
5. **ScanInstance Updated** → Condition reason set to error message
6. **Event Generated** → Kubernetes event created with detailed error

### Data Flow:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Prescan Job (Python)                                                    │
│                                                                          │
│ try:                                                                     │
│     validate_backup_path()  # Raises FileNotFoundError                  │
│ except FileNotFoundError as e:                                          │
│     error_msg = "Backup path is inaccessible: ..."                      │
│     update_job_error_annotation(job_name, job_namespace, error_msg)     │
│     sys.exit(1)                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Job Annotation                                                           │
│                                                                          │
│ metadata:                                                                │
│   annotations:                                                           │
│     threatscanning.trilio.io/prescan-error: "Backup path is             │
│       inaccessible: Backup path does not exist: /triliodata/..."        │
│ status:                                                                  │
│   failed: 1                                                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Controller (Go)                                                          │
│                                                                          │
│ jobStatus := GetJobStatus(preScanJob)                                   │
│ if jobStatus == Failed {                                                │
│     errorReason := "Pre-scan validation failed"  // default             │
│     if errMsg, ok := preScanJob.Annotations[PrescanErrorAnnotation] {   │
│         errorReason = errMsg  // use annotation if available            │
│     }                                                                    │
│     updateScanInstanceCondition(..., errorReason)                       │
│     recorder.Event(..., "PreScanFailed", errorReason)                   │
│ }                                                                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ScanInstance Status                                                      │
│                                                                          │
│ status:                                                                  │
│   status: Failed                                                         │
│   condition:                                                             │
│   - phase: PreScan                                                       │
│     status: Failed                                                       │
│     reason: "Backup path is inaccessible: Backup path does not exist:   │
│               /triliodata/plan1/backup123"                               │
│     timestamp: "2026-02-16T12:00:00Z"                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Kubernetes Event                                                         │
│                                                                          │
│ Type:    Warning                                                         │
│ Reason:  PreScanFailed                                                   │
│ Message: Pre-scan failed for ScanInstance test-scan: Backup path is     │
│          inaccessible: Backup path does not exist: /triliodata/...      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Example Scenarios

### Scenario 1: Path Validation Failure

**Prescan Job:**
```yaml
metadata:
  annotations:
    threatscanning.trilio.io/prescan-error: "Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123"
status:
  failed: 1
```

**ScanInstance Status:**
```yaml
status:
  status: Failed
  condition:
  - phase: PreScan
    status: Failed
    reason: "Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123"
    timestamp: "2026-02-16T12:00:00Z"
```

**Kubernetes Event:**
```bash
$ kubectl describe scaninstance test-scan
...
Events:
  Type     Reason          Message
  ----     ------          -------
  Warning  PreScanFailed   Pre-scan failed for ScanInstance test-scan: Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123
```

### Scenario 2: Generic Prescan Failure (No Annotation)

**Prescan Job:**
```yaml
metadata:
  annotations: {}  # No error annotation set
status:
  failed: 1
```

**ScanInstance Status:**
```yaml
status:
  status: Failed
  condition:
  - phase: PreScan
    status: Failed
    reason: "Pre-scan validation failed"  # Default message
    timestamp: "2026-02-16T12:00:00Z"
```

**Kubernetes Event:**
```bash
Events:
  Type     Reason          Message
  ----     ------          -------
  Warning  PreScanFailed   Pre-scan failed for ScanInstance test-scan: Pre-scan validation failed
```

### Scenario 3: Metadata Parsing Error (Future Enhancement)

When we add more error categorization:

**Prescan Job:**
```yaml
metadata:
  annotations:
    threatscanning.trilio.io/prescan-error: "Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)"
status:
  failed: 1
```

**ScanInstance Status:**
```yaml
status:
  status: Failed
  condition:
  - phase: PreScan
    status: Failed
    reason: "Invalid JSON in tvk-meta.json: Expecting value: line 5 column 1 (char 123)"
    timestamp: "2026-02-16T12:00:00Z"
```

## Benefits

### 1. User-Visible Error Messages
Users can see detailed error messages without checking pod logs:
```bash
kubectl get scaninstance test-scan -o jsonpath='{.status.condition[?(@.phase=="PreScan")].reason}'
# Output: Backup path is inaccessible: Backup path does not exist: /triliodata/plan1/backup123
```

### 2. Events for Observability
```bash
kubectl describe scaninstance test-scan
# Shows warning event with detailed error message
```

### 3. No Pod Log Inspection Needed
Error is persisted in annotation and reflected in CR, even if pod is deleted:
```bash
# Traditional approach (without annotation):
kubectl logs job/prescan-test-scan  # May fail if pod deleted

# New approach (with annotation):
kubectl get scaninstance test-scan -o yaml  # Always works
```

### 4. Consistent with TVK Pattern
Follows the same pattern used in k8s-triliovault datamover:
- Job updates its own annotation
- Controller reads and propagates to CR
- Events generated for user visibility

### 5. Actionable Error Messages
Users immediately know what went wrong:
- **"Backup path is inaccessible"** → Check target storage and backup path
- **"Invalid JSON in tvk-meta.json"** → Backup may be corrupted
- **"Target not found"** → Check target CR exists

## Testing

### Test Case 1: Path Not Found Error

**Setup:**
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-path-error
spec:
  backupTarget:
    name: my-target
  backupRef:
    path: non-existent-path
    uid: fake-uid
EOF
```

**Wait for prescan job to fail:**
```bash
kubectl wait --for=condition=failed job/prescan-test-path-error --timeout=60s
```

**Verify annotation:**
```bash
kubectl get job prescan-test-path-error -o jsonpath='{.metadata.annotations.threatscanning\.trilio\.io/prescan-error}'
# Expected: Backup path is inaccessible: Backup path does not exist: /triliodata/non-existent-path
```

**Verify ScanInstance condition:**
```bash
kubectl get scaninstance test-path-error -o jsonpath='{.status.condition[?(@.phase=="PreScan")].reason}'
# Expected: Backup path is inaccessible: Backup path does not exist: /triliodata/non-existent-path
```

**Verify event:**
```bash
kubectl describe scaninstance test-path-error | grep -A 3 Events
# Expected: Warning event with detailed error message
```

### Test Case 2: Job Fails Without Annotation

**Simulate by killing prescan job pod before it can update annotation:**
```bash
kubectl delete pod -l job-name=prescan-test-scan
```

**Verify fallback behavior:**
```bash
kubectl get scaninstance test-scan -o jsonpath='{.status.condition[?(@.phase=="PreScan")].reason}'
# Expected: Pre-scan validation failed (default message)
```

## Compatibility

- ✅ **Backward compatible**: If annotation is not present, falls back to default message
- ✅ **Forward compatible**: Easy to add more error categories later
- ✅ **Idempotent**: Condition update only happens once (checked with `HasCondition`)
- ✅ **Persistent**: Annotation survives pod deletion

## Implementation Checklist

- [x] Add `PrescanErrorAnnotation` constant to `internal/constants.go`
- [x] Update controller to read annotation on job failure
- [x] Update condition reason with annotation value
- [x] Update event message with annotation value
- [x] Add fallback to default message if annotation not present
- [x] Test with path validation errors
- [ ] Test with other error types (when implemented)
- [ ] Document in user-facing docs

## Code Review Notes

**Safety:**
- Annotation read is safe with nil checks
- Empty string check ensures we don't use blank errors
- Default message ensures users always get some error info

**Idempotency:**
- Condition update only happens if `!scanInstance.HasCondition(v1.PreScan, v1.Failed)`
- This prevents duplicate events and condition updates

**Error Truncation:**
- Prescan CLI truncates errors to 256KB before setting annotation
- This prevents annotation size limit issues

**Event Generation:**
- Event includes both ScanInstance name and error message
- Event type is `Warning` (appropriate for failures)
- Event reason is `PreScanFailed` (consistent naming)

## Summary

The controller now seamlessly integrates with prescan error annotations:
1. Reads error messages from failed job annotations
2. Updates ScanInstance condition with detailed error
3. Generates Kubernetes events with error details
4. Provides fallback for backward compatibility
5. Follows TVK datamover pattern for consistency

Users can now see actionable error messages without checking pod logs!
