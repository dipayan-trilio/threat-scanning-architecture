# Prescan Job Failure Annotation Pattern (Following DataMover Pattern)

## Overview

The datamover in k8s-triliovault uses a pattern to report job failures through annotations. This allows the controller to:
1. Read the failure reason from the job annotation
2. Update the CR status with the error
3. Generate events for visibility

We can adopt this same pattern for the prescan job.

## DataMover Pattern Analysis

### 1. Job Updates Error Annotation (Inside Container)

**File:** `k8s-triliovault/pkg/datamover/datamover.go`

```go
const (
    // MaxErrorAnnotationSize is the maximum size in bytes for error annotation strings
    MaxErrorAnnotationSize = 256 * 1024 // 256KB
)

func updateJobAnnotations(kubeAccessor *kube.Accessor, jobName, jobNamespace string,
    backupType v1.BackupType, opErr error, imageInfo *helpers.ImageInfo) error {

    job, err := kubeAccessor.GetJob(jobNamespace, jobName)
    if err != nil {
        return fmt.Errorf("failed to fetch job %s/%s: %v", jobNamespace, jobName, err)
    }

    if job.Annotations == nil {
        job.Annotations = make(map[string]string)
    }

    // Set backup type annotation
    job.Annotations[internal.TrilioDataUploadBackupTypeAnnotation] = string(backupType)

    if opErr != nil {
        // Truncate error message to fit annotation size limit
        truncatedError := truncateErrorString(opErr.Error())
        job.Annotations[internal.TrilioDataUploadErrorAnnotation] = truncatedError
        log.Warnf("Backup operation failed for job %s: %s", jobName, truncatedError)
    } else {
        // Success case
        backupSize, _ := resource.ParseQuantity(imageInfo.Size)
        job.Annotations[internal.TrilioDataUploadSizeAnnotation] = backupSize.String()
    }

    err = kubeAccessor.Update(job)
    // With retry on conflict...
    return err
}
```

**Key Points:**
- Job updates its **own** annotation from within the container
- Uses retry mechanism with `retry.RetryOnConflict(retry.DefaultRetry, ...)`
- Truncates error to 256KB max
- Only updates on actual failure (`opErr != nil`)

### 2. Annotation Constant

**File:** `k8s-triliovault/internal/constants.go`

```go
TrilioDataUploadErrorAnnotation = TrilioVaultGroup + "/" + "data-upload-error"
// Results in: "triliovault.trilio.io/data-upload-error"
```

### 3. Controller Reads Annotation

**File:** `k8s-triliovault/controllers/backup/controller_helper.go`

```go
func syncDataUploadJobStatus(...) {
    // Get job
    job, err := r.GetJob(job.Namespace, job.Name)
    
    annotations := job.Annotations
    if annotations == nil {
        annotations = make(map[string]string)
    }

    if jobStatus.Completed {
        dataSnapshot.Uploaded = true
        dataSnapshot.Error = ""
    } else if jobStatus.Failed {
        dataSnapshot.Uploaded = false
        // Read error from annotation!
        dataSnapshot.Error = annotations[internal.TrilioDataUploadErrorAnnotation]
    }
    
    // Update CR status with error
    // Generate events...
}
```

**Key Points:**
- Controller checks `jobStatus.Failed`
- Reads error from annotation
- Updates CR's status field
- Can generate K8s events for user visibility

## Applying Pattern to Prescan Job

### 1. Add Annotation Constant

**File:** `threat-scanning-architecture/pkg/constants/constants.go` (or similar)

```go
package constants

const (
    // ThreatScanningGroup is the API group
    ThreatScanningGroup = "threatscanning.trilio.io"
    
    // PrescanErrorAnnotation stores prescan job failure reason
    PrescanErrorAnnotation = ThreatScanningGroup + "/prescan-error"
    
    // MaxErrorAnnotationSize is the maximum size for error annotations
    MaxErrorAnnotationSize = 256 * 1024 // 256KB
)
```

### 2. Update Prescan CLI to Set Annotation on Failure

**File:** `datastore-attacher/prescan/cli.py`

```python
import os
from kubernetes import client, config

def truncate_error_string(err_str: str, max_size: int = 256 * 1024) -> str:
    """Truncate error string to max annotation size."""
    if len(err_str) <= max_size:
        return err_str
    suffix = f"... [truncated, original size: {len(err_str)} bytes]"
    return err_str[:max_size - len(suffix)] + suffix

def update_job_error_annotation(job_name: str, job_namespace: str, error: str):
    """Update job annotation with error message."""
    try:
        config.load_incluster_config()
        batch_api = client.BatchV1Api()
        
        # Get job
        job = batch_api.read_namespaced_job(job_name, job_namespace)
        
        if job.metadata.annotations is None:
            job.metadata.annotations = {}
        
        # Truncate and set error annotation
        truncated_error = truncate_error_string(str(error))
        job.metadata.annotations['threatscanning.trilio.io/prescan-error'] = truncated_error
        
        # Update job
        batch_api.patch_namespaced_job(
            name=job_name,
            namespace=job_namespace,
            body=job
        )
        
        logging.info(f"Updated job {job_name} with error annotation")
        return True
    except Exception as e:
        logging.error(f"Failed to update job annotation: {e}")
        return False

def main():
    try:
        # Get job info from environment
        job_name = os.getenv('JOB_NAME')
        job_namespace = os.getenv('JOB_NAMESPACE')
        
        # ... existing prescan logic ...
        
        # Step 1-4: mount, detect, extract metadata, etc.
        
        # Step 5: Update ScanInstance
        success = k8s_client.patch_scan_instance(...)
        
        if not success:
            raise RuntimeError("Failed to update ScanInstance CR")
        
        logging.info("✓ Prescan validation completed successfully")
        sys.exit(0)
        
    except Exception as e:
        error_msg = f"Prescan validation failed: {str(e)}"
        logging.error(error_msg, exc_info=True)
        
        # Update job annotation with failure reason
        if job_name and job_namespace:
            update_job_error_annotation(job_name, job_namespace, str(e))
        
        sys.exit(1)
```

### 3. Pass Job Info to Prescan Container

**File:** `controllers/scaninstance/controller_helper.go` or `pkg/helpers/job_helper.go`

When creating prescan job, add environment variables:

```go
func createPrescanJob(...) (*batchv1.Job, error) {
    // ... existing job creation ...
    
    job := &batchv1.Job{
        ObjectMeta: metav1.ObjectMeta{
            Name:      jobName,
            Namespace: namespace,
            // ... labels, owner refs ...
        },
        Spec: batchv1.JobSpec{
            Template: corev1.PodTemplateSpec{
                Spec: corev1.PodSpec{
                    Containers: []corev1.Container{
                        {
                            Name:  "prescan",
                            Image: prescanImage,
                            Env: []corev1.EnvVar{
                                // Existing env vars...
                                {
                                    Name:  "JOB_NAME",
                                    ValueFrom: &corev1.EnvVarSource{
                                        FieldRef: &corev1.ObjectFieldSelector{
                                            FieldPath: "metadata.labels['job-name']",
                                        },
                                    },
                                },
                                {
                                    Name:  "JOB_NAMESPACE",
                                    ValueFrom: &corev1.EnvVarSource{
                                        FieldRef: &corev1.ObjectFieldSelector{
                                            FieldPath: "metadata.namespace",
                                        },
                                    },
                                },
                            },
                            // ... rest of container spec ...
                        },
                    },
                },
            },
        },
    }
    
    return job, nil
}
```

### 4. Controller Reads Annotation and Updates ScanInstance

**File:** `controllers/scaninstance/controller.go` or `controller_helper.go`

```go
import (
    "github.com/trilioData/threat-scanning-architecture/pkg/constants"
)

func (r *ScanInstanceReconciler) handlePrescanJobStatus(
    ctx context.Context,
    scanInstance *threatv1.ScanInstance,
    job *batchv1.Job,
) error {
    
    // Check job status
    if isJobComplete(job) {
        // Job succeeded
        r.Log.Info("Prescan job completed successfully")
        
        // Update condition
        updateCondition(scanInstance, threatv1.ScanInstanceCondition{
            Phase:     threatv1.PrescanPhase,
            Status:    threatv1.CompletedStatus,
            Reason:    "PrescanCompleted",
            Timestamp: metav1.Now(),
        })
        
    } else if isJobFailed(job) {
        // Job failed - read error from annotation
        r.Log.Info("Prescan job failed, reading error annotation")
        
        errorMsg := "Prescan job failed"
        if job.Annotations != nil {
            if errAnnotation, ok := job.Annotations[constants.PrescanErrorAnnotation]; ok {
                errorMsg = errAnnotation
            }
        }
        
        // Update condition with error
        updateCondition(scanInstance, threatv1.ScanInstanceCondition{
            Phase:     threatv1.PrescanPhase,
            Status:    threatv1.FailedStatus,
            Reason:    errorMsg, // Error from annotation!
            Timestamp: metav1.Now(),
        })
        
        // Generate event for visibility
        r.Recorder.Event(
            scanInstance,
            corev1.EventTypeWarning,
            "PrescanFailed",
            errorMsg,
        )
        
        // Update overall status
        scanInstance.Status.Status = threatv1.FailedStatus
    }
    
    // Update ScanInstance
    return r.Status().Update(ctx, scanInstance)
}
```

## Benefits

### 1. **Detailed Error Reporting**
- Exact Python traceback/error message available in CR
- No need to check pod logs for debugging

### 2. **Event Generation**
- Controller can generate K8s events
- Visible in `kubectl describe scaninstance`
- UI/backend can display events

### 3. **Consistent Pattern**
- Follows existing TVK pattern (datamover)
- Maintainable and familiar to team

### 4. **Retry-Safe**
- Job annotation persists even if pod is deleted
- Controller can read error even after pod cleanup

### 5. **Size-Limited**
- Truncation prevents annotation size issues
- Still captures meaningful error context

## Example Flow

### Scenario: Backup Path Not Found

1. **Prescan Job Fails:**
   ```python
   raise RuntimeError(f"Backup path not found: {backup_path}")
   ```

2. **Job Updates Its Annotation:**
   ```python
   job.annotations['threatscanning.trilio.io/prescan-error'] = 
       'Prescan validation failed: Backup path not found: /triliodata/plan1/backup123'
   ```

3. **Controller Reads Annotation:**
   ```go
   errorMsg := job.Annotations["threatscanning.trilio.io/prescan-error"]
   // "Prescan validation failed: Backup path not found: /triliodata/plan1/backup123"
   ```

4. **Controller Updates ScanInstance:**
   ```yaml
   status:
     status: Failed
     condition:
     - phase: PreScan
       status: Failed
       reason: "Prescan validation failed: Backup path not found: /triliodata/plan1/backup123"
       timestamp: "2026-02-16T10:53:12Z"
   ```

5. **Controller Generates Event:**
   ```bash
   $ kubectl describe scaninstance my-scan
   Events:
     Type     Reason          Message
     ----     ------          -------
     Warning  PrescanFailed   Prescan validation failed: Backup path not found: /triliodata/plan1/backup123
   ```

6. **User Sees Error:**
   - In ScanInstance status
   - In Kubernetes events
   - In UI (if backend reads status)

## Implementation Checklist

- [ ] Add `PrescanErrorAnnotation` constant
- [ ] Update prescan CLI with `update_job_error_annotation()`
- [ ] Add error annotation update in prescan `except` block
- [ ] Pass `JOB_NAME` and `JOB_NAMESPACE` env vars to prescan container
- [ ] Update controller to read annotation on job failure
- [ ] Update controller to set condition reason from annotation
- [ ] Generate K8s events for prescan failures
- [ ] Test with various failure scenarios
- [ ] Document error handling in user docs

## Testing Scenarios

1. **Backup path not found** - Error should contain path
2. **Invalid JSON in metadata** - Error should contain JSON parse details
3. **Mount failure** - Error should contain mount error details
4. **K8s API failure** - Error should contain API error
5. **Long error message** - Should be truncated to 256KB

## Notes

- The annotation is **written by the job itself** (from inside the container)
- The annotation **persists** even if the pod is deleted
- The controller **reads** the annotation when the job fails
- This pattern is **battle-tested** in k8s-triliovault datamover
- Error size is **limited to 256KB** to avoid annotation size issues
