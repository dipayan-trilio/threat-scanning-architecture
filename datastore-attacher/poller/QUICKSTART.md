# Poller Quick Start Guide

## Prerequisites

1. Python 3.9+
2. Kubernetes cluster with threat-scanning CRDs installed
3. BackupTarget CR in 'Available' state
   - Note: The poller CronJob is only created/run when the BackupTarget is available
4. ReportingTarget CR in 'Available' state

## Installation

### 1. Install Dependencies

```bash
cd datastore-attacher
pip install -r requirements.txt
pip install -r poller/requirements.txt
```

### 2. Configure Environment

```bash
# Required: Name of the BackupTarget CR to process
export BACKUP_TARGET_NAME=my-backup-target

# Optional: Logging level (DEBUG, INFO, WARN, ERROR)
export LOG_LEVEL=INFO

# Optional: For local development (loads kubeconfig instead of in-cluster config)
export VM_MOUNT=true
```

## Running the Poller

### Local Development

```bash
cd datastore-attacher/poller
python3 main.py
```

### Expected Output

```
======================================================================
               THREAT SCANNING POLLER
======================================================================
Target: my-backup-target

Checking ReportingTarget availability...
✓ ReportingTarget 'reporting-target' is available

Fetching BackupTarget 'my-backup-target'...
✓ BackupTarget 'my-backup-target' fetched successfully

======================================================================
                    CLEANUP PHASE
======================================================================
Created TVK handler
Starting cleanup for target: my-backup-target
Listed 150 backup directories from S3 bucket my-bucket
Found 10 backupplans with total 150 backups
Found 145 total ScanInstances for target
STALE: ScanInstance si-abc-123 references backup backup-xyz which no longer exists
AGGRESSIVE: Backupplan bp-old-456 deleted from target, cleaning up 3 ScanInstances
Cleanup completed: deleted 8 stale ScanInstances

----------------------------------------------------------------------
✓ CLEANUP COMPLETED SUCCESSFULLY
  - Backupplans processed: 10
  - Total backups found: 150
  - Stale ScanInstances deleted: 8
  - Failed deletions: 0
----------------------------------------------------------------------

======================================================================
                    DISCOVERY PHASE
======================================================================
TODO: Discovery phase not yet implemented
======================================================================

======================================================================
                         SUMMARY
======================================================================
  Cleanup Phase:    ✓ SUCCESS
  Discovery Phase:  ✓ SUCCESS
======================================================================
Poller completed successfully
```

## Running Tests

```bash
cd datastore-attacher/poller
python3 test_cleanup_simple.py
```

## Kubernetes Deployment

### 1. Create ServiceAccount and RBAC

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: threat-scanning-poller
  namespace: threat-scanning-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: threat-scanning-poller
rules:
- apiGroups: ["threatscanning.trilio.io"]
  resources: ["targets", "scaninstances"]
  verbs: ["get", "list", "delete"]
- apiGroups: [""]
  resources: ["secrets", "configmaps"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: threat-scanning-poller
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: threat-scanning-poller
subjects:
- kind: ServiceAccount
  name: threat-scanning-poller
  namespace: threat-scanning-system
```

### 2. Create CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: threat-scanning-poller
  namespace: threat-scanning-system
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: threat-scanning-poller
          restartPolicy: OnFailure
          containers:
          - name: poller
            image: your-registry/threat-scanning-poller:latest
            imagePullPolicy: Always
            env:
            - name: BACKUP_TARGET_NAME
              value: "my-backup-target"
            - name: LOG_LEVEL
              value: "INFO"
            resources:
              requests:
                memory: "256Mi"
                cpu: "100m"
              limits:
                memory: "512Mi"
                cpu: "500m"
```

### 3. Build Docker Image

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Copy datastore-attacher code
COPY datastore-attacher/mount_utility /app/mount_utility
COPY datastore-attacher/poller /app/poller

# Install dependencies
RUN pip install --no-cache-dir \
    kubernetes>=28.1.0 \
    boto3>=1.26.0 \
    botocore>=1.29.0

# Run poller
CMD ["python3", "/app/poller/main.py"]
```

```bash
docker build -t your-registry/threat-scanning-poller:latest .
docker push your-registry/threat-scanning-poller:latest
```

## Troubleshooting

### Issue: "BACKUP_TARGET_NAME environment variable not set"

**Solution**: Set the environment variable:
```bash
export BACKUP_TARGET_NAME=my-backup-target
```

### Issue: "ReportingTarget not found"

**Solution**: Ensure ReportingTarget CR exists with annotation:
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"
spec:
  # ... target configuration
```

### Issue: "Target not found"

**Solution**: Verify the target name and ensure it exists:
```bash
kubectl get targets -A
```

### Issue: "Failed to mount NFS"

**Solution**: 
- Check NFS server is accessible
- Verify mount options in Target CR
- Ensure pod has necessary permissions (may need privileged mode for NFS)

### Issue: "Failed to list S3 structure"

**Solution**:
- Verify S3 credentials in secret
- Check S3 endpoint URL
- Verify bucket name and region
- Check SSL certificate configuration

## Monitoring

### Check CronJob Status

```bash
# List CronJobs
kubectl get cronjobs -n threat-scanning-system

# List Jobs created by CronJob
kubectl get jobs -n threat-scanning-system

# Check last job logs
kubectl logs -n threat-scanning-system \
  $(kubectl get pods -n threat-scanning-system \
    -l job-name=threat-scanning-poller-<timestamp> \
    -o jsonpath='{.items[0].metadata.name}')
```

### Manual Trigger

```bash
# Create a one-time job from the CronJob
kubectl create job --from=cronjob/threat-scanning-poller \
  manual-run-$(date +%s) \
  -n threat-scanning-system
```

## Next Steps

1. ✅ Cleanup phase is implemented and working
2. ⏳ Implement discovery phase (see architecture.md for requirements)
3. ⏳ Add Prometheus metrics
4. ⏳ Implement monitoring phase

## Support

For issues or questions:
1. Check logs: `kubectl logs -n threat-scanning-system <pod-name>`
2. Verify CRDs: `kubectl get crds | grep threatscanning`
3. Check Target status: `kubectl get targets -A`
4. Review architecture.md for design details

