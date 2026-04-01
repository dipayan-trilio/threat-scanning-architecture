# Datastore-Attacher Integration for Threat-Scanning-Architecture

## Overview

This document describes the integration of k8s-commons datastore-attacher into threat-scanning-architecture with modifications for read-only backup target validation and write-enabled reporting target validation.

## Architecture Changes

### Source
- **Original**: `k8s-commons/datastore-attacher` (from k8s-triliovault)
- **Adapted For**: `threat-scanning-architecture/datastore-attacher`

### Key Modifications

1. **API Group**: Changed from `triliovault.trilio.io` to `threatscanning.trilio.io`
2. **Target Validation**: Split into two modes:
   - **Backup Target** (read-only): Mount + List + Read operations
   - **Reporting Target** (write-enabled): Direct S3 API validation
3. **Removed**: QCOW2 verification (not needed for threat scanning)
4. **Removed**: Write/Update/Delete operations for backup targets

---

## Implementation Details

### 1. Target Types

#### Backup Target (Read-Only)
**Purpose**: Scan existing backup data stored by k8s-triliovault

**Validation Steps**:
- Mount target (NFS or ObjectStore via s3fuse)
- Verify mount succeeded
- List files/objects in root directory
- Read file metadata (using `os.stat()`)
- Read first 1KB of a file's content
- **NO write operations**

**Use Cases**:
- Scanning backup qcow2 images for threats
- Browsing backup metadata
- Reading backup manifests

#### Reporting Target (Write-Enabled)
**Purpose**: Upload scan reports/results using boto3 APIs

**Validation Steps**:
- Direct S3 API validation (no mounting)
- Test operations: `head_bucket`, `list_objects`, `put_object`, `get_object`, `delete_object`
- Uses `validate_s3_permission()` from utilities

**Use Cases**:
- Uploading scan reports
- Storing vulnerability findings
- Publishing compliance reports

---

## File Structure

```
threat-scanning-architecture/
├── datastore-attacher/                    # Copied from k8s-commons
│   ├── scripts/
│   │   └── target_validations.py         # MODIFIED: Added --type flag, new validation methods
│   ├── mount_utility/
│   │   ├── constants.py                   # MODIFIED: Updated API group, added target types
│   │   ├── utilities.py                   # UNCHANGED: Reused from k8s-commons
│   │   ├── kube_utilities.py              # UNCHANGED: Reused from k8s-commons
│   │   ├── logger.py                      # UNCHANGED: Reused from k8s-commons
│   │   └── mount_by_target_crd/
│   │       ├── mount_datastores.py        # UNCHANGED: Supports dynamic API group
│   │       └── triliodata_crd_parser.py   # UNCHANGED: Supports dynamic API group
│   ├── s3fuse/                            # UNCHANGED: Reused from k8s-commons
│   └── requirements.txt                   # UNCHANGED: Reused from k8s-commons
├── internal/
│   └── constants.go                       # MODIFIED: Added datastore-attacher paths
├── pkg/helpers/
│   └── job_helper.go                      # MODIFIED: Updated validation command with --type flag
└── controllers/target/
    ├── controller.go                      # UNCHANGED: No modifications needed
    └── controller_helper.go               # UNCHANGED: No modifications needed
```

---

## Modified Files Summary

### 1. `datastore-attacher/scripts/target_validations.py`

**Changes**:
- ✅ Added `--type` flag (required, choices: `backup` or `reporting`)
- ✅ Implemented `validate_backup_target()` - read-only validation
- ✅ Implemented `validate_reporting_target()` - S3 API validation
- ✅ Implemented `validate_nfs_backup_target()` - read-only NFS validation
- ✅ Removed `validate_create()`, `validate_update()`, `validate_delete()` (not needed)
- ✅ Removed `qemu_verification()` call
- ✅ Simplified `validate()` method to route based on target type

**New CLI Interface**:
```bash
# Backup target validation (read-only)
# Note: --namespace is NOT used (targets are cluster-scoped)
python3 target_validations.py \
    --target-name=my-backup-target \
    --type=backup \
    --group=threatscanning.trilio.io \
    --version=v1

# Reporting target validation (write-enabled)
# Note: --namespace is NOT used (targets are cluster-scoped)
python3 target_validations.py \
    --target-name=my-reporting-target \
    --type=reporting \
    --group=threatscanning.trilio.io \
    --version=v1
```

### 2. `datastore-attacher/mount_utility/constants.py`

**Changes**:
- ✅ Updated `TVK_CRD_GROUP` from `triliovault.trilio.io` to `threatscanning.trilio.io`
- ✅ Removed `TVS_TARGET_CRD_GROUP` (not needed for threat scanning)
- ✅ Updated `CREDENTIAL_HASH_ANNOTATION` to `trilio.io/credentials-hash`
- ✅ Updated `TVKConfig` to `threat-scanning-config`
- ✅ Added `TARGET_TYPE_BACKUP = "backup"`
- ✅ Added `TARGET_TYPE_REPORTING = "reporting"`

### 3. `internal/constants.go`

**Changes**:
- ✅ Added `BasePath = "/opt/threat-scanning"`
- ✅ Added `Py3Path = "/usr/bin/python3"`
- ✅ Added `DatastoreValidatorUtil = "datastore-attacher/scripts/target_validations.py"`
- ✅ Added `DatastoreMountUtil = "datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py"`
- ✅ Added `DatastoreAttacherPathInContainer = "/opt/threat-scanning/datastore-attacher"`

### 4. `pkg/helpers/job_helper.go`

**Changes**:
- ✅ Updated `GetTargetValidatorJob()` to determine target type via `target.IsReportingTarget()`
- ✅ Built validation command with `--type` flag
- ✅ Updated API group in command to `threatscanning.trilio.io`
- ✅ For ObjectStore targets: mount first (via `mount_datastores.py`), then validate
- ✅ For NFS targets: validate directly (already mounted via volume)
- ✅ Added privileged security context for ObjectStore targets (needed for s3fuse)

**Command Structure**:
```go
// For NFS targets
validationCmd = "/usr/bin/python3 /opt/threat-scanning/datastore-attacher/scripts/target_validations.py --target-name=<name> --type=backup --group=threatscanning.trilio.io --version=v1"

// For ObjectStore targets
mountCmd = "/usr/bin/python3 /opt/threat-scanning/datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py --target-name=<name> --group=threatscanning.trilio.io --version=v1"
validateCmd = "/usr/bin/python3 /opt/threat-scanning/datastore-attacher/scripts/target_validations.py --target-name=<name> --type=<backup|reporting> --group=threatscanning.trilio.io --version=v1"
validationCmd = mountCmd + " && " + validateCmd
```

---

## Validation Logic Flow

### Backup Target Validation (Read-Only)

#### For ObjectStore (S3/MinIO/etc.):
```
1. Controller creates validation Job
2. Job pod starts with privileged container
3. Mount s3fuse: mount_datastores.py --target-name=<name>
4. Validate read operations:
   a. Verify mount succeeded: os.path.ismount()
   b. List files: os.listdir()
   c. Read file metadata: os.stat()
   d. Read first 1KB: open(file, 'rb').read(1024)
5. Exit with success/failure
```

#### For NFS:
```
1. Controller creates validation Job with NFS volume
2. Job pod starts with NFS already mounted
3. Validate read operations:
   a. Verify mount succeeded
   b. List files
   c. Read file metadata
   d. Read first 1KB
4. Exit with success/failure
```

### Reporting Target Validation (Write-Enabled)

```
1. Controller creates validation Job
2. Job pod starts (no privileged needed)
3. NO mounting - use boto3 directly
4. Validate S3 operations:
   a. head_bucket
   b. list_objects
   c. put_object (test file)
   d. get_object (test file)
   e. delete_object (test file)
5. Exit with success/failure
```

---

## Security Considerations

### Privileged Containers
- **ObjectStore Backup Targets**: Require privileged container for s3fuse FUSE mounting
- **NFS Targets**: No privileged container needed (uses native Kubernetes NFS volumes)
- **Reporting Targets**: No privileged container needed (direct boto3 API)

### Service Account
All validation jobs run with the controller's service account: `trilio-threat-scanning`

### RBAC Requirements
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: threat-scanning-controller
rules:
- apiGroups: ["threatscanning.trilio.io"]
  resources: ["targets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets", "configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

---

## Container Image Requirements

### Validator Image
The validator image must include:
- Python 3 (`/usr/bin/python3`)
- Required Python packages (from `requirements.txt`):
  - `boto3` (S3 API client)
  - `kubernetes` (k8s client)
  - `fusepy` (for s3fuse)
  - All dependencies in `requirements.txt`
- Datastore-attacher code at `/opt/threat-scanning/datastore-attacher/`
- s3fuse utilities

**Dockerfile Example**:
```dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    fuse \
    && rm -rf /var/lib/apt/lists/*

# Copy datastore-attacher
COPY datastore-attacher /opt/threat-scanning/datastore-attacher/

# Install Python dependencies
RUN pip install --no-cache-dir -r /opt/threat-scanning/datastore-attacher/requirements.txt

# Set working directory
WORKDIR /opt/threat-scanning

CMD ["/bin/bash"]
```

---

## Differences from k8s-triliovault

| Feature | k8s-triliovault | threat-scanning-architecture |
|---------|-----------------|------------------------------|
| **API Group** | `triliovault.trilio.io` | `threatscanning.trilio.io` |
| **Target Scope** | Namespaced or Cluster | **Cluster-scoped only** (no `--namespace` param) |
| **Validation Mode** | Write-enabled for all | Read-only for backup, write for reporting |
| **QCOW2 Verification** | ✅ Yes (creates test qcow2) | ❌ No (not needed) |
| **Write Operations** | ✅ Yes (create/update/delete) | ❌ No for backup targets |
| **Target Types** | Single mode | Dual mode (backup/reporting) |
| **Event Targets** | ✅ Supported | ❌ Not supported |
| **Immutability Checks** | ✅ Full validation | ⚠️  Simplified (reuse existing) |
| **Secret Cloning** | ✅ Supported | ❌ Not needed (cluster-scoped) |

---

## Testing

### Manual Testing

#### 1. Test Backup Target (S3)
```bash
# Create target
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-s3-backup
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    url: "https://s3.amazonaws.com"
    bucketName: "my-backup-bucket"
    region: "us-east-1"
    credentialSecret:
      name: s3-credentials
      namespace: threat-scanning-system
EOF

# Check validation job
kubectl get jobs -n threat-scanning-system | grep threat-scan-target-validation

# Check validation logs
kubectl logs -n threat-scanning-system <validation-job-pod>
```

#### 2. Test Reporting Target (S3)
```bash
# Create target with reporting annotation
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-s3-reporting
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  vendor: MinIO
  objectStoreCredentials:
    url: "https://minio.example.com"
    bucketName: "scan-reports"
    credentialSecret:
      name: minio-credentials
      namespace: threat-scanning-system
EOF

# Check validation - should test write operations
kubectl logs -n threat-scanning-system <validation-job-pod>
```

#### 3. Test NFS Backup Target
```bash
# Create NFS target
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-nfs-backup
spec:
  type: NFS
  vendor: Other
  nfsCredentials:
    nfsExport: "192.168.1.100:/backup/path"
    nfsOptions: "rw,hard,intr"
EOF

# Check validation - should mount and read-only validate
kubectl logs -n threat-scanning-system <validation-job-pod>
```

### Expected Validation Output

#### Successful Backup Target Validation:
```
Target validation in progress for type: backup
Target storage type: objectstore
Target validation type: backup
Validating backup target (read-only)
✅ Verified /triliodata is mounted
✅ Successfully listed 15 objects in target
✅ Successfully read file metadata: backup-001.qcow2 (size=1073741824 bytes, mode=0o100644)
✅ Successfully read 1024 bytes from file backup-001.qcow2
✅ Backup target validation completed successfully
================================================================================
🎉 Target 'test-s3-backup' validation SUCCESSFUL (type: backup)
================================================================================
```

#### Successful Reporting Target Validation:
```
Target validation in progress for type: reporting
Target storage type: objectstore
Target validation type: reporting
Validating reporting target (write-enabled using S3 API)
Verifying S3 permissions...
head_bucket Check Started
head_bucket Check Completed
list_objects Check Started
list_objects Check Completed
put_object Check Started
put_object Check Completed
get_object Check Started
get_object Check Completed
delete_object Check Started
delete_object Check Completed
✅ Reporting target validation completed successfully
================================================================================
🎉 Target 'test-s3-reporting' validation SUCCESSFUL (type: reporting)
================================================================================
```

---

## Future Enhancements

1. **Parallel File Reading**: Test reading multiple files concurrently
2. **Depth-First Search**: Validate directory structure recursively
3. **Large File Testing**: Test reading large QCOW2 images (>10GB)
4. **Performance Metrics**: Measure read throughput and latency
5. **Azure Blob Support**: Add read-only validation for Azure targets
6. **GCS Support**: Add read-only validation for Google Cloud Storage

---

## Troubleshooting

### Common Issues

#### Issue 1: Validation Job Pod in CrashLoopBackOff
**Cause**: Missing Python dependencies or datastore-attacher code
**Solution**: Verify validator image has all required packages and code at `/opt/threat-scanning/datastore-attacher/`

#### Issue 2: "Mount failed" for ObjectStore targets
**Cause**: Container not privileged or missing SYS_ADMIN capability
**Solution**: Check `SecurityContext` in job spec has `privileged: true`

#### Issue 3: "Failed to list objects" for S3 targets
**Cause**: Incorrect credentials or bucket permissions
**Solution**: Verify secret has correct `accessKey` and `secretKey`, and bucket allows `s3:ListBucket`

#### Issue 4: "Target has active scans" when deleting
**Cause**: Controller cleanup logic preventing deletion
**Solution**: Wait for scans to complete or manually delete ConfigMap entry

---

## Summary

The datastore-attacher integration provides a robust, production-ready validation mechanism for threat-scanning-architecture:

✅ **Read-Only Backup Validation**: Safely validates access to existing backup data  
✅ **Write-Enabled Reporting**: Validates ability to upload scan results  
✅ **Dual Storage Support**: Works with both NFS and ObjectStore targets  
✅ **Security**: Minimal privileges (only privileged for s3fuse mounting)  
✅ **Reusable**: Leverages battle-tested k8s-commons code  
✅ **Extensible**: Easy to add new target types or validation methods  

This implementation strikes a balance between security (read-only for backups), functionality (write for reports), and code reuse (minimal changes to k8s-commons).

