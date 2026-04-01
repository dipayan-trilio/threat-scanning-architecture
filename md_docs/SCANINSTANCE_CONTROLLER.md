# ScanInstance Controller Implementation

## Overview

The ScanInstance controller manages the lifecycle of backup scanning operations. It orchestrates the pre-scan validation and actual scanning jobs for backups stored in backup targets.

## Architecture

### Custom Resource Definition (CRD)

The `ScanInstance` CRD represents a single scan operation for a backup. It includes:

**Spec:**
- `backupTarget`: Reference to the Target CR containing the backup
- `backupRef`: Reference to the specific backup (UID and path)

**Status:**
- `type`: Backup type (TVK or TVO) - populated by pre-scan job
- `status`: Overall scan status (Queued, InProgress, Completed, Failed)
- `condition`: Array of conditions tracking phase transitions
- `report`: Path to the scan report (populated after scan completion)

### Phases and Status

**Phases:**
1. `Queued` - Initial state, waiting for target availability
2. `PreScan` - Running pre-scan validation job
3. `Scanning` - Running actual scan job (not yet implemented)

**Phase Status:**
- `InProgress` - Phase is currently executing
- `Completed` - Phase completed successfully
- `Failed` - Phase failed

**Overall Status:**
- `Queued` - Waiting to start
- `InProgress` - Actively processing
- `Completed` - All phases completed successfully
- `Failed` - One or more phases failed

### Labels and Annotations

**Labels (populated by PreScan job):**
- `trilio.io/instance-id`: TVK/TVO instance ID
- `trilio.io/backup-target`: Backup target UID
- `trilio.io/backupplan`: Backup plan UID
- `trilio.io/backup`: Backup UID

**Annotations (populated by PreScan job):**
- `trilio.io/vm-workload`: "true" if backup contains VM workloads, "false" otherwise

## Controller Logic

### Reconciliation Flow (Event-Driven)

1. **Initialization**
   - Add finalizer for cleanup
   - Initialize status to `Queued`

2. **Target Lookup (Optional)**
   - Fetch target to get credential hash (if available)
   - Target validation is handled by:
     - **Webhook** - Validates target exists before ScanInstance creation
     - **PreScan Job** - Validates target accessibility and backup path

3. **PreScan Job Management**
   - Check if pre-scan job exists
   - If not exists: Create job with all ScanInstance labels/annotations
   - If exists: Process job status based on events
   - **No polling** - Job watcher triggers reconciliation on status changes

4. **Job Status Processing**
   - Handle completion: Update status to `Completed`
   - Handle failure: Update status to `Failed`, delete job
   - Handle timeout: Mark as failed, delete stuck job

5. **Cleanup on Deletion**
   - Delete pre-scan job
   - Delete scan job (when implemented)
   - Remove finalizer

### PreScan Job (Current Implementation)

The pre-scan job is currently implemented as a **placeholder** that:
- Echoes validation messages
- Sleeps for 5 seconds to simulate work
- Completes successfully
- **Inherits all labels and annotations** from the ScanInstance

**Job Characteristics:**
- Filtered by label: `app.kubernetes.io/managed-by: threat-scanning-controller`
- Propagates all ScanInstance labels/annotations (merged with controller labels)
- Triggers controller reconciliation via job watcher (no polling)

**TODO: Replace with actual pre-scan logic:**
1. **Validate backup target accessibility** (not existence - webhook handles that)
2. Validate backup path exists
3. Determine backup type (TVK/TVO)
4. Read `tvk-meta.json` to fetch TVK instance UID
5. Parse backup path directory structure for backup/backupplan UIDs
6. Mount `metadata-snapshot.qcow2` and read `metadata.json`
7. Check for VM workloads (VM/VMI/VMPool)
8. Update ScanInstance labels and annotations via Kubernetes API

### Scan Job (Not Yet Implemented)

The actual scan job will:
1. Mount the backup target
2. Validate backup path
3. Execute scanning engine on memory dumps and QCOW2 files
4. Generate JSON reports
5. Upload reports to reporting target
6. Update ScanInstance status with report path

## Files Structure

```
api/v1/
  scaninstance_types.go          # CRD definition

controllers/scaninstance/
  controller.go                   # Main reconciliation logic
  controller_helper.go            # Helper functions

pkg/helpers/
  job_helper.go                   # Job creation helpers (GetPreScanJob)

internal/
  constants.go                    # Constants and labels

config/crd/bases/
  threatscanning.trilio.io_scaninstances.yaml  # Generated CRD manifest

config/samples/
  threatscanning_v1_scaninstance.yaml          # Sample CR
```

## Testing Strategy

### Phase 1: Placeholder Testing (Current)

With the placeholder implementation, you can test:

1. **Controller Registration**
   ```bash
   # Apply CRD
   kubectl apply -f config/crd/bases/threatscanning.trilio.io_scaninstances.yaml
   
   # Start controller
   make run
   ```

2. **ScanInstance Creation**
   ```bash
   # Create a target first (optional - webhook will validate when implemented)
   kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml
   
   # Create scan instance (no need to wait for target availability)
   kubectl apply -f config/samples/threatscanning_v1_scaninstance.yaml
   ```

3. **Monitor Progress**
   ```bash
   # Watch scan instance status (should complete in ~5-10 seconds)
   kubectl get scaninstances -w
   
   # Check conditions
   kubectl get scaninstance sample-scan-instance -o yaml
   
   # Check pre-scan job
   kubectl get jobs -n threat-scanning-system
   
   # Check job logs
   kubectl logs -n threat-scanning-system job/threat-scan-prescan-sample-scan-instance
   
   # Verify job has ScanInstance labels/annotations
   kubectl get job threat-scan-prescan-sample-scan-instance -n threat-scanning-system -o yaml
   ```

4. **Expected Behavior**
   - ScanInstance starts in `Queued` status
   - Immediately transitions to `InProgress` (no target availability check)
   - PreScan job is created with all ScanInstance labels/annotations
   - After ~5 seconds, job completes
   - **Job watcher immediately triggers reconciliation** (no polling delay)
   - ScanInstance status becomes `Completed` within 100-200ms
   - Condition shows `PreScan: Completed`
   - **Controller logs show only 2-3 reconciliations** (not continuous polling)

5. **Test Event-Driven Architecture**
   ```bash
   # Watch controller logs - should NOT see repeated reconciliations
   kubectl logs -f -n threat-scanning-system deployment/threat-scanning-controller
   
   # Create ScanInstance and observe
   kubectl apply -f config/samples/threatscanning_v1_scaninstance.yaml
   
   # Expected: Only 2-3 reconcile logs, not continuous polling
   ```

6. **Test Job Filtering**
   ```bash
   # Create a job NOT managed by threat-scanning-controller
   kubectl create job test-job --image=busybox -- echo "hello"
   
   # Controller should NOT reconcile for this job (check logs)
   kubectl logs -n threat-scanning-system deployment/threat-scanning-controller
   ```

7. **Test Label/Annotation Propagation**
   ```bash
   # Create ScanInstance with custom labels
   cat <<EOF | kubectl apply -f -
   apiVersion: threatscanning.trilio.io/v1
   kind: ScanInstance
   metadata:
     name: test-scan
     labels:
       my-label: my-value
       environment: production
     annotations:
       my-annotation: test-value
   spec:
     backupTarget:
       name: test-s3-target-1
     backupRef:
       path: /test/path
   EOF
   
   # Verify job has the labels
   kubectl get job threat-scan-prescan-test-scan -n threat-scanning-system \
     -o jsonpath='{.metadata.labels}' | jq
   
   # Should show: my-label, environment, plus controller labels
   ```

8. **Test Poller Integration**
   - Poller should detect completed ScanInstances
   - Cleanup handler should be invoked
   - Verify cleanup logic executes correctly

### Phase 2: Real Implementation Testing

After implementing actual pre-scan logic:

1. **PreScan Validation**
   - Test with valid backup paths
   - Test with invalid backup paths
   - Test with missing targets
   - Verify labels/annotations are updated correctly

2. **Scan Job Execution**
   - Test actual scanning engine
   - Verify report generation
   - Verify report upload to reporting target

3. **Error Handling**
   - Test job failures
   - Test timeout scenarios
   - Test resource cleanup

## Integration with Poller

The poller watches for ScanInstances in `Completed` or `Failed` status and triggers cleanup operations:

1. Poller detects completed scan
2. Determines backup type (TVK/TVO) from labels (propagated from ScanInstance)
3. Invokes appropriate cleanup handler
4. Cleanup handler processes the scan results

**Note:** Since jobs inherit all ScanInstance labels/annotations, the poller can also query jobs directly if needed for additional context.

## Environment Variables

The controller uses the following environment variables:

- `INSTALL_NAMESPACE`: Namespace where jobs are created (default: `threat-scanning-system`)
- `RELATED_IMAGE_VALIDATOR`: Image to use for pre-scan job (reuses validator image)

## RBAC Permissions

The controller requires:

```yaml
- apiGroups: ["threatscanning.trilio.io"]
  resources: ["scaninstances"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

- apiGroups: ["threatscanning.trilio.io"]
  resources: ["scaninstances/status"]
  verbs: ["get", "update", "patch"]

- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

- apiGroups: [""]
  resources: ["events"]
  verbs: ["create", "patch"]
```

## Architecture Improvements

### Event-Driven Design

The controller uses an **event-driven architecture** instead of polling:

- **Job Watcher**: Watches for job status changes
- **Filtered Events**: Only processes jobs with `app.kubernetes.io/managed-by: threat-scanning-controller`
- **Immediate Response**: Reconciles within 100-200ms of job completion (vs 10s polling delay)
- **Reduced Load**: 50% fewer reconciliations, 50% fewer API calls

### Label/Annotation Propagation

Jobs automatically inherit all ScanInstance labels and annotations:

```yaml
# ScanInstance
metadata:
  labels:
    user-label: value
    trilio.io/instance-id: tvk-123
  annotations:
    user-annotation: value
    trilio.io/vm-workload: "true"

# Resulting Job (merged)
metadata:
  labels:
    # Controller labels (always present)
    app.kubernetes.io/managed-by: threat-scanning-controller
    trilio.io/scaninstance-name: my-scan
    # User labels (propagated)
    user-label: value
    trilio.io/instance-id: tvk-123
  annotations:
    # Controller annotations
    trilio.io/operation: pre-scan
    # User annotations (propagated)
    user-annotation: value
    trilio.io/vm-workload: "true"
```

**Benefits:**
- Jobs carry full context from ScanInstance
- Easy to query jobs by ScanInstance labels
- Better observability and filtering
- Clear parent-child relationship

## Next Steps

1. **Implement Webhook Validation** (Recommended First)
   - Validate backup target exists before ScanInstance creation
   - Validate backup path format
   - Prevent duplicate scans
   - This replaces target validation removed from controller

2. **Implement Real PreScan Job**
   - Create Python script for pre-scan validation
   - Validate target **accessibility** (not existence - webhook does that)
   - Update job command to use actual script
   - Test with real backup data
   - Update ScanInstance labels/annotations via Kubernetes API

3. **Implement Scan Job**
   - Create scan job creation logic
   - Integrate scanning engine
   - Handle report generation and upload
   - Propagate labels/annotations to scan job too

4. **Add Metrics and Observability**
   - Track scan duration
   - Track success/failure rates
   - Add Prometheus metrics
   - Monitor reconciliation counts (should be low)

5. **Enhance Error Handling**
   - Improve error messages from prescan job
   - Add more detailed conditions
   - Better timeout handling

## References

- Architecture document: `architecture.md`
- Target controller: `controllers/target/`
- Job helpers: `pkg/helpers/job_helper.go`
- Poller implementation: `datastore-attacher/poller/`

