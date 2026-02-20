# Prescan Job Failure Points and Error Annotations

## Overview

This document maps all prescan job failure scenarios to specific error reasons that will be stored in job annotations and reflected in ScanInstance conditions and events.

## Error Categories and Annotations

### 1. Path Validation Failures

**Location:** `prescan/validator.py` - `validate_backup_path()`

| Error Type | Python Exception | Error Reason | Annotation Value | User-Friendly Message |
|------------|-----------------|--------------|------------------|----------------------|
| Path doesn't exist | `FileNotFoundError` | `BackupPathNotFound` | `Backup path does not exist: {path}` | "The backup path could not be found on the target storage" |
| Path is not a directory | `NotADirectoryError` | `BackupPathInvalid` | `Backup path is not a directory: {path}` | "The backup path exists but is not a valid directory" |
| Path not readable | `PermissionError` | `BackupPathInaccessible` | `Backup path is not readable: {path}` | "Permission denied when accessing the backup path" |

**Example:**
```python
# Exception raised
raise FileNotFoundError(f"Backup path does not exist: /triliodata/plan1/backup123")

# Annotation set
job.annotations['threatscanning.trilio.io/prescan-error-reason'] = 'BackupPathNotFound'
job.annotations['threatscanning.trilio.io/prescan-error'] = 'Backup path does not exist: /triliodata/plan1/backup123'
```

### 2. Target/K8s API Failures

**Location:** `prescan/cli.py` - Steps 2 & 5

| Error Type | Scenario | Error Reason | Annotation Value | User-Friendly Message |
|------------|----------|--------------|------------------|----------------------|
| Target CR not found | `get_target()` returns None | `TargetNotFound` | `Target {name} not found` | "The target storage configuration was not found" |
| Failed to update ScanInstance | `patch_scan_instance()` fails | `ScanInstanceUpdateFailed` | `Failed to update ScanInstance CR` | "Could not update the scan instance status" |
| K8s API connection error | Any K8s client exception | `KubernetesAPIError` | `Kubernetes API error: {error}` | "Failed to communicate with Kubernetes API" |

**Example:**
```python
if not target_cr:
    raise RuntimeError(f"Target {args.target_name} not found")

# Annotation
# Reason: TargetNotFound
# Error: "Target my-target not found"
```

### 3. Backup Type Detection Failures

**Location:** `prescan/cli.py` - Step 3

| Error Type | Scenario | Error Reason | Annotation Value | User-Friendly Message |
|------------|----------|--------------|------------------|----------------------|
| Unknown backup type | `backup_type == 'UNKNOWN'` | `BackupTypeUnknown` | `Could not determine backup type (TVK/TVO)` | "Unable to identify if backup is from TrilioVault for Kubernetes or OpenStack" |
| Missing detection markers | No tvk-meta.json or tvo files | `BackupMarkersNotFound` | `Backup identification files not found` | "The backup does not contain required metadata files" |

**Example:**
```python
if backup_type == 'UNKNOWN':
    raise RuntimeError("Could not determine backup type (TVK/TVO)")

# Annotation
# Reason: BackupTypeUnknown
# Error: "Could not determine backup type (TVK/TVO)"
```

### 4. Metadata Extraction Failures (TVK)

**Location:** `shared/backup_detection/tvk_detector.py` - `extract_metadata()`

| Error Type | Python Exception | Error Reason | Annotation Value | User-Friendly Message |
|------------|-----------------|--------------|------------------|----------------------|
| tvk-meta.json not found | `RuntimeError` | `TVKMetaNotFound` | `tvk-meta.json not found at {path}` | "TVK metadata file is missing from the backup" |
| Invalid tvk-meta.json | `ValueError` (JSON decode) | `TVKMetaInvalid` | `Invalid JSON in tvk-meta.json: {error}` | "TVK metadata file contains invalid JSON" |
| Missing TVK instance UID | `RuntimeError` | `TVKInstanceUIDMissing` | `tvkInstanceUID not found in tvk-meta.json` | "TVK instance identifier is missing from metadata" |
| backup.json not found | `RuntimeError` | `BackupMetaNotFound` | `backup.json not found at {path}` | "Backup metadata file is missing" |
| Invalid backup.json | `ValueError` (JSON decode) | `BackupMetaInvalid` | `Invalid JSON in backup.json: {error}` | "Backup metadata file contains invalid JSON" |
| cluster-backup.json not found | `RuntimeError` | `ClusterBackupMetaNotFound` | `cluster-backup.json not found at {path}` | "Cluster backup metadata file is missing" |
| Invalid cluster-backup.json | `ValueError` (JSON decode) | `ClusterBackupMetaInvalid` | `Invalid JSON in cluster-backup.json: {error}` | "Cluster backup metadata file contains invalid JSON" |
| Invalid backup path structure | `RuntimeError` | `BackupPathStructureInvalid` | `Invalid backup path structure: {path}` | "Backup directory structure does not match expected format" |

**Example:**
```python
if not os.path.exists(tvk_meta_path):
    raise RuntimeError(f"tvk-meta.json not found at {tvk_meta_path}")

# Annotation
# Reason: TVKMetaNotFound
# Error: "tvk-meta.json not found at /triliodata/plan1/backup123/tvk-meta.json"
```

### 5. No VM Workload (Non-Error Case)

**Location:** `prescan/cli.py` - Already handled via annotation

| Scenario | Current Annotation | Should Update? | Error Reason | Event Type |
|----------|-------------------|----------------|--------------|------------|
| No VM workloads found | `trilio.io/vm-workload: "false"` | ✅ Yes | `NoVMWorkloadFound` | **Info** (not Warning) |
| hasKubevirtResources=false | Same as above | ✅ Yes | `NoVMWorkloadFound` | **Info** |
| Empty dataSnapshots | Same as above | ✅ Yes | `NoVMWorkloadFound` | **Info** |
| Only container workloads | Same as above | ✅ Yes | `NoVMWorkloadFound` | **Info** |

**Important:** This is **NOT a failure** but should still be communicated to the user clearly.

**Handling:**
```python
# When is_vm_workload == False
annotations = {
    'trilio.io/vm-workload': 'false',
    'trilio.io/cluster-backup': str(is_cluster_backup).lower(),
    'threatscanning.trilio.io/prescan-info-reason': 'NoVMWorkloadFound',  # Info reason
    'threatscanning.trilio.io/prescan-info': 'Backup does not contain any VM workloads'
}

# Controller generates Info event (not Warning/Error)
r.Recorder.Event(
    scanInstance,
    corev1.EventTypeNormal,  // Normal, not Warning
    "NoVMWorkloadFound",
    "Backup validated successfully but does not contain any VM workloads. Only container workloads present.",
)

# ScanInstance status
status.Status = "Completed"  // Not Failed!
condition.Reason = "NoVMWorkloadFound - Backup does not contain VM workloads"
```

### 6. Mount-Related Failures (If mounting in prescan)

**Location:** If prescan handles mounting (currently controller does it)

| Error Type | Scenario | Error Reason | Annotation Value |
|------------|----------|--------------|------------------|
| Mount failed | NFS/S3 mount error | `TargetMountFailed` | `Failed to mount target: {error}` |
| Target credentials invalid | Auth failure | `TargetAuthenticationFailed` | `Target authentication failed: {error}` |

**Note:** Currently, mounting is handled by the controller before prescan runs, so these errors would appear as Job creation failures, not prescan failures.

## Error Annotation Schema

We'll use **two annotations** for better categorization:

### Primary Annotations

```yaml
# For actual errors/failures
threatscanning.trilio.io/prescan-error-reason: "BackupPathNotFound"
threatscanning.trilio.io/prescan-error: "Backup path does not exist: /triliodata/plan1/backup123"

# For informational messages (non-failures)
threatscanning.trilio.io/prescan-info-reason: "NoVMWorkloadFound"
threatscanning.trilio.io/prescan-info: "Backup does not contain any VM workloads"
```

### Why Two Annotation Sets?

1. **Errors** → Job actually failed → ScanInstance status = `Failed`
2. **Info** → Job succeeded but user should know → ScanInstance status = `Completed`

## Controller Behavior Matrix

| Annotation Present | Job Status | ScanInstance Status | Condition Status | Event Type | Event Reason |
|-------------------|------------|---------------------|------------------|------------|--------------|
| `prescan-error` | Failed | `Failed` | `Failed` | Warning | Error reason from annotation |
| `prescan-info` | Completed | `Completed` | `Completed` | Normal | Info reason from annotation |
| None | Completed | `Completed` | `Completed` | Normal | "PrescanCompleted" |

## Implementation: Error Reason Mapping Function

```python
# prescan/error_reasons.py

class PrescanErrorReason:
    """Prescan error reason constants."""
    
    # Path validation errors
    BACKUP_PATH_NOT_FOUND = "BackupPathNotFound"
    BACKUP_PATH_INVALID = "BackupPathInvalid"
    BACKUP_PATH_INACCESSIBLE = "BackupPathInaccessible"
    
    # Target/K8s API errors
    TARGET_NOT_FOUND = "TargetNotFound"
    SCAN_INSTANCE_UPDATE_FAILED = "ScanInstanceUpdateFailed"
    KUBERNETES_API_ERROR = "KubernetesAPIError"
    
    # Backup type detection errors
    BACKUP_TYPE_UNKNOWN = "BackupTypeUnknown"
    BACKUP_MARKERS_NOT_FOUND = "BackupMarkersNotFound"
    
    # TVK metadata errors
    TVK_META_NOT_FOUND = "TVKMetaNotFound"
    TVK_META_INVALID = "TVKMetaInvalid"
    TVK_INSTANCE_UID_MISSING = "TVKInstanceUIDMissing"
    BACKUP_META_NOT_FOUND = "BackupMetaNotFound"
    BACKUP_META_INVALID = "BackupMetaInvalid"
    CLUSTER_BACKUP_META_NOT_FOUND = "ClusterBackupMetaNotFound"
    CLUSTER_BACKUP_META_INVALID = "ClusterBackupMetaInvalid"
    BACKUP_PATH_STRUCTURE_INVALID = "BackupPathStructureInvalid"
    
    # Informational (non-errors)
    NO_VM_WORKLOAD_FOUND = "NoVMWorkloadFound"


def categorize_error(exception: Exception) -> tuple[str, str]:
    """
    Categorize exception into error reason and annotation type.
    
    Returns:
        (error_reason, annotation_type)
        annotation_type is either 'error' or 'info'
    """
    error_msg = str(exception)
    
    # Path validation
    if isinstance(exception, FileNotFoundError):
        if "Backup path does not exist" in error_msg:
            return (PrescanErrorReason.BACKUP_PATH_NOT_FOUND, 'error')
    
    if isinstance(exception, NotADirectoryError):
        if "Backup path is not a directory" in error_msg:
            return (PrescanErrorReason.BACKUP_PATH_INVALID, 'error')
    
    if isinstance(exception, PermissionError):
        if "Backup path is not readable" in error_msg:
            return (PrescanErrorReason.BACKUP_PATH_INACCESSIBLE, 'error')
    
    # Target errors
    if "Target" in error_msg and "not found" in error_msg:
        return (PrescanErrorReason.TARGET_NOT_FOUND, 'error')
    
    if "Failed to update ScanInstance" in error_msg:
        return (PrescanErrorReason.SCAN_INSTANCE_UPDATE_FAILED, 'error')
    
    # Backup type detection
    if "Could not determine backup type" in error_msg:
        return (PrescanErrorReason.BACKUP_TYPE_UNKNOWN, 'error')
    
    # TVK metadata errors
    if "tvk-meta.json not found" in error_msg:
        return (PrescanErrorReason.TVK_META_NOT_FOUND, 'error')
    
    if "Invalid JSON in tvk-meta.json" in error_msg:
        return (PrescanErrorReason.TVK_META_INVALID, 'error')
    
    if "tvkInstanceUID not found" in error_msg:
        return (PrescanErrorReason.TVK_INSTANCE_UID_MISSING, 'error')
    
    if "backup.json not found" in error_msg:
        return (PrescanErrorReason.BACKUP_META_NOT_FOUND, 'error')
    
    if "Invalid JSON in backup.json" in error_msg:
        return (PrescanErrorReason.BACKUP_META_INVALID, 'error')
    
    if "cluster-backup.json not found" in error_msg:
        return (PrescanErrorReason.CLUSTER_BACKUP_META_NOT_FOUND, 'error')
    
    if "Invalid JSON in cluster-backup.json" in error_msg:
        return (PrescanErrorReason.CLUSTER_BACKUP_META_INVALID, 'error')
    
    if "Invalid backup path structure" in error_msg:
        return (PrescanErrorReason.BACKUP_PATH_STRUCTURE_INVALID, 'error')
    
    # Default: generic error
    return ("PrescanFailed", 'error')
```

## Updated Prescan CLI with Error Categorization

```python
def main():
    try:
        # ... existing prescan logic ...
        
        # Special case: No VM workload (not an error!)
        if not is_vm_workload:
            # Set info annotation (not error)
            annotations['threatscanning.trilio.io/prescan-info-reason'] = 'NoVMWorkloadFound'
            annotations['threatscanning.trilio.io/prescan-info'] = 'Backup does not contain any VM workloads'
            
            # Still update job annotation for consistency
            if job_name and job_namespace:
                update_job_info_annotation(
                    job_name, 
                    job_namespace, 
                    'NoVMWorkloadFound',
                    'Backup does not contain any VM workloads'
                )
        
        sys.exit(0)
        
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Prescan validation failed: {error_msg}", exc_info=True)
        
        # Categorize error
        from prescan.error_reasons import categorize_error
        error_reason, annotation_type = categorize_error(e)
        
        # Update job annotation with categorized error
        job_name = os.getenv('JOB_NAME')
        job_namespace = os.getenv('JOB_NAMESPACE')
        
        if job_name and job_namespace:
            update_job_error_annotation(
                job_name, 
                job_namespace, 
                error_reason,  # Categorized reason
                error_msg      # Full error message
            )
        
        sys.exit(1)
```

## Controller Integration

```go
func (r *ScanInstanceReconciler) handlePrescanJobStatus(...) error {
    
    if isJobFailed(job) {
        // Read error reason and message from annotations
        errorReason := "PrescanFailed"
        errorMsg := "Prescan job failed"
        
        if job.Annotations != nil {
            if reason, ok := job.Annotations["threatscanning.trilio.io/prescan-error-reason"]; ok {
                errorReason = reason
            }
            if msg, ok := job.Annotations["threatscanning.trilio.io/prescan-error"]; ok {
                errorMsg = msg
            }
        }
        
        // Update condition
        updateCondition(scanInstance, threatv1.ScanInstanceCondition{
            Phase:     threatv1.PrescanPhase,
            Status:    threatv1.FailedStatus,
            Reason:    fmt.Sprintf("%s - %s", errorReason, errorMsg),
            Timestamp: metav1.Now(),
        })
        
        // Generate event with categorized reason
        r.Recorder.Event(
            scanInstance,
            corev1.EventTypeWarning,
            errorReason,  // Use categorized reason as event reason
            errorMsg,     // Full error as message
        )
        
    } else if isJobComplete(job) {
        // Check for info annotations (e.g., no VM workload)
        if job.Annotations != nil {
            if infoReason, ok := job.Annotations["threatscanning.trilio.io/prescan-info-reason"]; ok {
                if infoMsg, ok := job.Annotations["threatscanning.trilio.io/prescan-info"]; ok {
                    // Generate Info event
                    r.Recorder.Event(
                        scanInstance,
                        corev1.EventTypeNormal,  // Normal, not Warning
                        infoReason,
                        infoMsg,
                    )
                }
            }
        }
        
        // Update condition (Completed, not Failed)
        updateCondition(scanInstance, threatv1.ScanInstanceCondition{
            Phase:     threatv1.PrescanPhase,
            Status:    threatv1.CompletedStatus,
            Reason:    "PrescanCompleted",
            Timestamp: metav1.Now(),
        })
    }
    
    return nil
}
```

## User Experience Examples

### Example 1: Backup Path Not Found

**Prescan logs:**
```
ERROR: Prescan validation failed: Backup path does not exist: /triliodata/plan1/backup123
```

**ScanInstance status:**
```yaml
status:
  status: Failed
  condition:
  - phase: PreScan
    status: Failed
    reason: "BackupPathNotFound - Backup path does not exist: /triliodata/plan1/backup123"
    timestamp: "2026-02-16T10:53:12Z"
```

**Kubernetes event:**
```bash
$ kubectl describe scaninstance my-scan
Events:
  Type     Reason                  Message
  ----     ------                  -------
  Warning  BackupPathNotFound      Backup path does not exist: /triliodata/plan1/backup123
```

### Example 2: No VM Workload (Info, not Error)

**Prescan logs:**
```
INFO: ✓ No VM workloads to scan
INFO: ✓ Prescan validation completed successfully
```

**ScanInstance status:**
```yaml
status:
  status: Completed  # Not Failed!
  condition:
  - phase: PreScan
    status: Completed
    reason: "PrescanCompleted"
    timestamp: "2026-02-16T10:53:12Z"
annotations:
  trilio.io/vm-workload: "false"
  threatscanning.trilio.io/prescan-info-reason: "NoVMWorkloadFound"
  threatscanning.trilio.io/prescan-info: "Backup does not contain any VM workloads"
```

**Kubernetes event:**
```bash
$ kubectl describe scaninstance my-scan
Events:
  Type    Reason                Message
  ----    ------                -------
  Normal  NoVMWorkloadFound     Backup does not contain any VM workloads
  Normal  PrescanCompleted      Prescan validation completed successfully
```

## Summary

- **14 distinct error reasons** covering all failure points
- **1 info reason** for non-error cases (no VM workload)
- **Two annotation sets** to distinguish errors from informational messages
- **Categorized errors** make debugging easier for users and support
- **Consistent with datamover** pattern from k8s-triliovault
