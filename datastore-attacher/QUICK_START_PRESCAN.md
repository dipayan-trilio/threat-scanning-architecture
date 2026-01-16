# Quick Start: Prescan CLI

## Overview

The prescan CLI validates backup targets and enriches ScanInstance CRs with metadata before the actual scan job runs.

## Installation

The prescan CLI is part of the `datastore-attacher` package and uses the shared utilities.

### Dependencies

```bash
# Install Python dependencies (if not already installed)
pip install kubernetes boto3 botocore
```

## Usage

### Basic Command

```bash
python3 prescan/cli.py \
  --target-name=backup-target \
  --backup-path=backupplan-uid/backup-uid \
  --backup-uid=backup-uid \
  --scaninstance-name=scan-instance-123
```

### Example with Real Values

```bash
python3 prescan/cli.py \
  --target-name=minio-target \
  --backup-path=5b0df775-8f42-46d4-b97f-e8cbc6fbd2ac/95b052ea-f689-4ae4-97ea-795012c84e6d \
  --backup-uid=95b052ea-f689-4ae4-97ea-795012c84e6d \
  --scaninstance-name=abc-123-def-456
```

## What It Does

### Step-by-Step Process

1. **Validates Target**
   - Checks if Target CR exists
   - Verifies target is in "Available" status

2. **Mounts Target**
   - Uses `mount_utility` to mount target to `/triliodata`
   - Supports both NFS and S3 (via s3fuse)

3. **Validates Backup Path**
   - Checks if backup directory exists
   - Verifies read permissions

4. **Detects Backup Type**
   - Uses shared detection logic
   - Identifies TVK or TVO backup

5. **Reads Metadata**
   - For TVK: Reads `tvk-meta.json`
   - Extracts instance ID
   - Parses backupplan UID and backup UID from path

6. **Detects VM Workload**
   - Looks for `metadata-snapshot.qcow2`
   - Mounts it using `qemu-nbd`
   - Reads `metadata.json`
   - Checks for VM/VMI/DV/VMPool resources

7. **Updates ScanInstance CR**
   - Adds labels:
     - `trilio.io/instance-id`
     - `trilio.io/backup-target`
     - `trilio.io/backupplan`
     - `trilio.io/backup`
   - Adds annotation:
     - `trilio.io/vm-workload: true|false`
   - Updates status:
     - `type: TVK|TVO`

## Expected Output

### Success

```
INFO: Validating target minio-target...
INFO: ✓ Target minio-target is available
INFO: Mounting target minio-target...
INFO: ✓ Successfully mounted minio-target at /triliodata
INFO: Validating backup path: /triliodata/5b0df775.../95b052ea...
INFO: ✓ Backup path exists
INFO: Detecting TVK backup type...
INFO: Found TVK marker: /triliodata/.../tvk-meta.json
INFO: ✓ Detected backup type: TVK
INFO: ✓ Extracted metadata: instance_id=66bbddbd-a774-4535-b9b2-b66d70be3e3c, backupplan_uid=5b0df775-8f42-46d4-b97f-e8cbc6fbd2ac
INFO: ✓ VM workload detection: True
INFO: Updating ScanInstance abc-123-def-456...
INFO: ✓ Successfully updated ScanInstance abc-123-def-456
INFO: ✓ Prescan validation completed successfully
```

### Failure Examples

**Target Not Found:**
```
ERROR: Target minio-target not found
ERROR: Prescan validation failed: Target minio-target not found
```

**Target Not Available:**
```
ERROR: Target minio-target is not available (status: unavailable)
ERROR: Prescan validation failed: Target minio-target is not available
```

**Backup Path Not Found:**
```
ERROR: Backup path does not exist: /triliodata/invalid/path
ERROR: Prescan validation failed: Backup path does not exist
```

**Unknown Backup Type:**
```
WARNING: No TVK markers found in NFS mount
WARNING: TVO detection is not yet implemented
ERROR: Could not determine backup type (TVK/TVO)
ERROR: Prescan validation failed: Could not determine backup type
```

## Integration with Kubernetes

### As a Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: prescan-abc-123
spec:
  template:
    spec:
      serviceAccountName: threat-scanning-controller
      containers:
      - name: prescan
        image: prescan:latest
        command:
        - python3
        - /prescan/cli.py
        - --target-name=minio-target
        - --backup-path=5b0df775.../95b052ea...
        - --backup-uid=95b052ea-f689-4ae4-97ea-795012c84e6d
        - --scaninstance-name=abc-123-def-456
        securityContext:
          privileged: true  # Required for qemu-nbd
        volumeMounts:
        - name: dev
          mountPath: /dev
      volumes:
      - name: dev
        hostPath:
          path: /dev
      restartPolicy: Never
```

### Required Permissions

The service account needs:
- Read access to Target CRs
- Read/Write access to ScanInstance CRs
- Ability to mount filesystems (privileged)

## Troubleshooting

### Issue: "No free NBD device available"

**Cause**: All NBD devices are in use

**Solution**:
```bash
# Check NBD devices
ls -la /dev/nbd*

# Disconnect unused devices
sudo qemu-nbd -d /dev/nbd0
sudo qemu-nbd -d /dev/nbd1
# ... etc
```

### Issue: "Mount command timed out"

**Cause**: Network issues or slow S3 endpoint

**Solution**:
- Check network connectivity
- Verify S3 endpoint is accessible
- Check target credentials

### Issue: "Failed to mount metadata snapshot"

**Cause**: qemu-nbd not installed or insufficient permissions

**Solution**:
```bash
# Install qemu-utils
sudo apt-get install qemu-utils

# Run with sudo or privileged container
```

### Issue: "Failed to update ScanInstance CR"

**Cause**: Insufficient RBAC permissions

**Solution**:
- Verify service account has patch permissions on ScanInstance CRs
- Check RBAC roles and bindings

## Testing Locally

### Prerequisites

1. Kubernetes cluster with threat scanning CRDs
2. Target CR created and available
3. Backup data accessible
4. qemu-utils installed

### Test Command

```bash
# Set KUBECONFIG
export KUBECONFIG=/path/to/kubeconfig

# Run prescan
python3 prescan/cli.py \
  --target-name=test-target \
  --backup-path=test-backupplan/test-backup \
  --backup-uid=test-backup-uid \
  --scaninstance-name=test-scaninstance
```

### Verify Results

```bash
# Check ScanInstance CR
kubectl get scaninstance test-scaninstance -o yaml

# Verify labels
kubectl get scaninstance test-scaninstance -o jsonpath='{.metadata.labels}'

# Verify annotations
kubectl get scaninstance test-scaninstance -o jsonpath='{.metadata.annotations}'

# Verify status
kubectl get scaninstance test-scaninstance -o jsonpath='{.status}'
```

## Docker Image

### Build

```dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    qemu-utils \
    nfs-common \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt

# Copy code
COPY datastore-attacher /app/
WORKDIR /app

# Make CLI executable
RUN chmod +x prescan/cli.py

ENTRYPOINT ["python3", "prescan/cli.py"]
```

### Build and Push

```bash
docker build -t prescan:latest .
docker tag prescan:latest your-registry/prescan:latest
docker push your-registry/prescan:latest
```

## Next Steps

1. **Test with Sample Backups**: Run prescan against test backups
2. **Integrate with Controller**: Update Go controller to create prescan jobs
3. **Add Monitoring**: Add metrics and logging
4. **Add TVO Support**: Implement TVO detection and metadata parsing

## Related Documentation

- [Prescan README](prescan/README.md) - Detailed prescan documentation
- [Shared Package README](shared/README.md) - Shared utilities documentation
- [Refactoring Summary](REFACTORING_SUMMARY.md) - Complete refactoring details
- [Architecture](../architecture.md) - Overall threat scanning architecture

