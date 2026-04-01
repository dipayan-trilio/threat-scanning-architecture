# Scan Job Implementation Summary

## Overview

Implemented full scan job lifecycle management for ScanInstance CRs after prescan completion. The scan job reads VM disk image information from a ConfigMap and performs scanning operations.

## Implementation Details

### 1. Constants and Environment Variables

**File: `internal/constants.go`**

Added constants for scan job and configmap resources:
```go
// Scan job prefix
ScanInstanceScanJobPrefix = "threat-scan-scanjob"

// Scan configmap prefix  
ScanInstanceScanConfigPrefix = "scan-config"

// Scan error annotation
ScanErrorAnnotation = "threatscanning.trilio.io/scan-error"

// Scanner image environment variable
RelatedImageScanner = "RELATED_IMAGE_SCANNER"
DefaultScannerImage = "threat-scan-scanner:latest"
```

### 2. Helper Functions

**File: `pkg/helpers/job_helper.go`**

#### a. `GetScanConfigMapData(scanLocations []v1.ScanLocation) (map[string]string, error)`

Generates ConfigMap data from `ScanInstance.status.scanLocations` in the format:

```json
{
  "vm_artifacts": {
    "<vm-1-name>": {
      "disk_image": [
        "<pvc-path-1>",
        "<pvc-path-2>"
      ],
      "collection_time": "2026-02-16T10:30:00Z",
      "priority": "high",
      "suspected_compromise": true
    },
    "<vm-2-name>": {
      "disk_image": [
        "<pvc-path-1>"
      ],
      "collection_time": "2026-02-16T10:30:00Z",
      "priority": "high",
      "suspected_compromise": true
    }
  }
}
```

**Key Points:**
- Each VM name becomes a key in `vm_artifacts`
- `disk_image` array contains all PVC paths for that VM
- `collection_time` is set to current UTC time
- `priority` is hardcoded to "high"
- `suspected_compromise` is hardcoded to true

#### b. `GetScanConfigMap(scanInstance *v1.ScanInstance) (*corev1.ConfigMap, error)`

Creates a ConfigMap with:
- Name: `scan-config-<scaninstance-name>`
- Namespace: `threat-scanning-system` (install namespace)
- Labels: Standard labels with component="scan-config"
- Data: Single file `config.json` with VM artifacts JSON

#### c. `GetScanJob(ctx, cl, scanInstance) (*batchv1.Job, error)`

Creates a scan job with:
- Name: `threat-scan-scanjob-<scaninstance-name>`
- Image: From env var `RELATED_IMAGE_SCANNER` (default: `threat-scan-scanner:latest`)
- Command: `bash -c "cat /config/config.json && echo 'Scan job started' && sleep 300"`
- ConfigMap mount: `/config/config.json` (read-only)
- Environment variables: `JOB_NAME`, `JOB_NAMESPACE` (for future error annotation)
- Resources:
  - Requests: 500m CPU, 512Mi memory
  - Limits: 2000m CPU, 2Gi memory
- BackoffLimit: 0 (no retries)
- ServiceAccount: `trilio-threat-scanning`

### 3. Controller Logic

**File: `controllers/scaninstance/controller.go`**

#### RBAC Permissions Added
```go
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
```

#### Workflow After PreScan Completes

```
PreScan Completed
      ↓
Check if VM workloads exist (scanLocations not empty)
      ↓
   YES ←─────────────────→ NO
      ↓                        ↓
Create scan configmap    Mark as Completed
(scan-config-<name>)     (no scanning needed)
      ↓
Set owner reference
      ↓
Update condition:
Scanning/InProgress
      ↓
Create scan job
(threat-scan-scanjob-<name>)
      ↓
Generate event:
ScanJobCreated
      ↓
Wait for job completion
```

#### Scan Job Status Processing

**File: `controllers/scaninstance/controller_helper.go` - `processScanJobStatus()`**

Handles three states:

1. **Completed (Success)**:
   - Update condition: `Scanning/Completed`
   - Update status: `ScanCompleted`
   - Generate event: `ScanCompleted`
   - Trigger cleanup (delete jobs and configmap)

2. **Failed (Error)**:
   - Read error from job annotation `threatscanning.trilio.io/scan-error`
   - Update condition: `Scanning/Failed` with error reason
   - Update status: `ScanFailed`
   - Generate event: `ScanFailed` with error details
   - **Keep jobs and configmap for debugging**

3. **InProgress (Running)**:
   - Check for timeout using `IsJobPendingDeadlineExceeded()`
   - If timeout: mark as failed
   - Otherwise: wait for job watcher to trigger reconciliation

### 4. Cleanup Logic

#### On Success (ScanInstance Completed)

**Function: `cleanupScanInstanceJobs()`**

Deletes in order:
1. PreScan job (with pods)
2. Scan job (with pods)
3. Scan configmap

Uses `DeletePropagationForeground` to ensure pods are deleted before jobs.

#### On Failure (ScanInstance Failed)

**Resources are kept for debugging:**
- PreScan job
- Scan job
- Scan configmap

All cleaned up when ScanInstance CR is deleted (finalizer handles this).

#### On CR Deletion

**Function: `cleanupScanInstanceResources()`**

Deletes all resources regardless of status:
1. PreScan job
2. Scan job
3. Scan configmap

Uses `DeletePropagationBackground` for faster cleanup.

### 5. Idempotency

Controller ensures idempotency at each step:

1. **Configmap Creation**: Checks if already exists using `IsAlreadyExists()`
2. **Job Creation**: Checks if job exists before creating
3. **Condition Updates**: Uses `HasCondition()` to avoid duplicate updates
4. **Cleanup**: Handles `IsNotFound()` errors gracefully

### 6. Events Generated

| Event Type | Reason | Description |
|------------|--------|-------------|
| Normal | ScanConfigMapCreated | Scan configmap created |
| Normal | ScanJobCreated | Scan job created |
| Normal | ScanCompleted | Scan completed successfully |
| Warning | ScanFailed | Scan job failed (with error reason) |
| Warning | ScanTimeout | Scan job exceeded pending deadline |

### 7. Scan Job Command (Current Implementation)

```bash
cat /config/config.json && echo 'Scan job started' && sleep 300
```

**Purpose:** Placeholder for actual scanning logic

**Actions:**
1. Print configmap contents (for verification)
2. Echo message
3. Sleep for 5 minutes (300 seconds)
4. Exit successfully

**Future:** Replace with actual scanning command that:
- Reads VM artifacts from `/config/config.json`
- Mounts and scans disk images
- Generates scan reports
- Updates error annotation on failure

### 8. ConfigMap Mount

The scan job mounts the configmap at `/config/`:

```yaml
volumeMounts:
  - name: scan-config
    mountPath: /config
    readOnly: true

volumes:
  - name: scan-config
    configMap:
      name: scan-config-<scaninstance-name>
```

File available at: `/config/config.json`

### 9. Error Handling

#### Scan Job Failures

The scan job can update its error annotation (similar to prescan):

```yaml
metadata:
  annotations:
    threatscanning.trilio.io/scan-error: "Scan failed: disk image corrupted"
```

Controller reads this annotation and:
1. Updates ScanInstance condition reason
2. Generates Kubernetes event
3. Updates ScanInstance status to `ScanFailed`

#### Error Propagation Flow

```
Scan Job Fails
      ↓
Update job annotation
(threatscanning.trilio.io/scan-error)
      ↓
Job status changes to Failed
      ↓
Controller reconciles
      ↓
Read error from annotation
      ↓
Update ScanInstance:
  - condition: Scanning/Failed
  - reason: <error from annotation>
  - status: ScanFailed
      ↓
Generate event with error
      ↓
Keep resources for debugging
```

## Testing Checklist

### 1. Successful Flow
- [ ] PreScan completes successfully
- [ ] Scan configmap is created
- [ ] Scan job is created
- [ ] Scan job completes successfully (after 5 minutes)
- [ ] ScanInstance marked as Completed
- [ ] All jobs and configmap are deleted

### 2. No VM Workloads
- [ ] PreScan completes with empty scanLocations
- [ ] ScanInstance marked as Completed immediately
- [ ] No scan job or configmap created

### 3. Scan Job Failure
- [ ] Scan job fails (simulate by making it exit with code 1)
- [ ] Controller reads error annotation
- [ ] ScanInstance marked as Failed with error reason
- [ ] Jobs and configmap are kept for debugging
- [ ] Event generated with error details

### 4. Cleanup on CR Deletion
- [ ] Delete ScanInstance CR
- [ ] Finalizer triggers cleanup
- [ ] All jobs and configmap deleted
- [ ] Finalizer removed

### 5. Idempotency
- [ ] Restart controller during scan job execution
- [ ] Controller recovers and continues from current state
- [ ] No duplicate jobs or configmaps created

## Environment Variables Required

Add to controller deployment:

```yaml
env:
  - name: RELATED_IMAGE_SCANNER
    value: "gcr.io/your-registry/threat-scanner:latest"
```

## ConfigMap Example

For a cluster backup with 2 VMs:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scan-config-dc7462fa-aa76-4b9b-9791-1e7dc81a32ba
  namespace: threat-scanning-system
  labels:
    app.kubernetes.io/component: scan-config
    app.kubernetes.io/managed-by: threat-scanning-controller
    app.kubernetes.io/part-of: threat-scanning
    trilio.io/creator-kind: ScanInstance
    trilio.io/scaninstance-name: dc7462fa-aa76-4b9b-9791-1e7dc81a32ba
data:
  config.json: |
    {
      "vm_artifacts": {
        "ubuntu-vm": {
          "disk_image": [
            "dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1.tar.gz"
          ],
          "collection_time": "2026-02-16T10:53:12Z",
          "priority": "high",
          "suspected_compromise": true
        },
        "fedora-vm": {
          "disk_image": [
            "dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/fedora-vm-disk-1.tar.gz",
            "dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/fedora-vm-disk-2.tar.gz"
          ],
          "collection_time": "2026-02-16T10:53:12Z",
          "priority": "high",
          "suspected_compromise": true
        }
      }
    }
```

## Job Example

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: threat-scan-scanjob-dc7462fa-aa76-4b9b-9791-1e7dc81a32ba
  namespace: threat-scanning-system
  labels:
    app.kubernetes.io/component: scan
    app.kubernetes.io/managed-by: threat-scanning-controller
    app.kubernetes.io/part-of: threat-scanning
    trilio.io/creator-kind: ScanInstance
    trilio.io/scaninstance-name: dc7462fa-aa76-4b9b-9791-1e7dc81a32ba
  annotations:
    trilio.io/operation: scan
    trilio.io/scaninstance-name: dc7462fa-aa76-4b9b-9791-1e7dc81a32ba
spec:
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: trilio-threat-scanning
      containers:
      - name: scanner
        image: threat-scan-scanner:latest
        imagePullPolicy: Always
        command: ["/bin/bash", "-c"]
        args:
        - "cat /config/config.json && echo 'Scan job started' && sleep 300"
        env:
        - name: JOB_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['job-name']
        - name: JOB_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        volumeMounts:
        - name: scan-config
          mountPath: /config
          readOnly: true
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2000m"
            memory: "2Gi"
      volumes:
      - name: scan-config
        configMap:
          name: scan-config-dc7462fa-aa76-4b9b-9791-1e7dc81a32ba
      restartPolicy: Never
```

## ScanInstance Status Example

```yaml
status:
  type: TVK
  status: InProgress
  condition:
  - phase: PreScan
    status: InProgress
    timestamp: "2026-02-16T10:53:00Z"
    reason: "Starting pre-scan validation"
  - phase: PreScan
    status: Completed
    timestamp: "2026-02-16T10:53:30Z"
    reason: "Pre-scan validation completed successfully"
  - phase: Scanning
    status: InProgress
    timestamp: "2026-02-16T10:53:35Z"
    reason: "Starting scan job"
  scanLocations:
  - namespace: namespace1
    backupUID: bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d
    backupPath: dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d
    vms:
    - vmName: ubuntu-vm
      pvcPaths:
      - dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1.tar.gz
    - vmName: fedora-vm
      pvcPaths:
      - dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/fedora-vm-disk-1.tar.gz
      - dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/fedora-vm-disk-2.tar.gz
```

## Files Modified

| File | Changes |
|------|---------|
| `internal/constants.go` | Added scan job constants and env vars |
| `pkg/helpers/job_helper.go` | Added `GetScanConfigMapData()`, `GetScanConfigMap()`, `GetScanJob()`, `getScannerImage()` |
| `controllers/scaninstance/controller.go` | Added scan job creation logic after prescan, RBAC for configmaps |
| `controllers/scaninstance/controller_helper.go` | Added `createScanJob()`, `getScanJob()`, `processScanJobStatus()`, updated cleanup functions |

## Summary

The scan job implementation is complete and follows the same patterns as the prescan job:

✅ **ConfigMap created** with VM artifacts from `scanLocations`
✅ **Scan job created** with configmap mounted at `/config/config.json`
✅ **Status tracked** through conditions (Scanning/InProgress → Completed/Failed)
✅ **Events generated** for each state transition
✅ **Cleanup on success** deletes all jobs and configmap
✅ **Keep on failure** resources retained for debugging
✅ **Idempotent** controller recovers gracefully from restarts
✅ **Error handling** via job annotations (future use)

**Ready for deployment and testing!**
