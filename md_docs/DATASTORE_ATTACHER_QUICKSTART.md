# Datastore-Attacher Quick Start Guide

## 🚀 Quick Reference

### What Changed?

We adapted k8s-commons datastore-attacher for threat-scanning with these key changes:

| Component | Change |
|-----------|--------|
| **API Group** | `triliovault.trilio.io` → `threatscanning.trilio.io` |
| **Target Types** | Single mode → Dual mode (backup/reporting) |
| **Backup Validation** | Write-enabled → **Read-only** (mount + list + read) |
| **Reporting Validation** | N/A → **Write-enabled** (S3 API only) |
| **QCOW2 Verification** | ✅ Required → ❌ Removed |

---

## 📁 What Was Modified?

### Modified Files (4 files):
1. ✅ `datastore-attacher/scripts/target_validations.py` - Added `--type` flag and new validation methods
2. ✅ `datastore-attacher/mount_utility/constants.py` - Updated API group and added target types
3. ✅ `internal/constants.go` - Added datastore-attacher paths
4. ✅ `pkg/helpers/job_helper.go` - Updated validation command with `--type` flag

### Unchanged Files (reused from k8s-commons):
- ✅ `mount_utility/utilities.py` - S3 validation functions
- ✅ `mount_utility/kube_utilities.py` - Kubernetes helpers
- ✅ `mount_utility/logger.py` - Logging utilities
- ✅ `mount_utility/mount_by_target_crd/mount_datastores.py` - Mount logic
- ✅ `mount_utility/mount_by_target_crd/triliodata_crd_parser.py` - CRD parser
- ✅ `s3fuse/` - S3 FUSE filesystem
- ✅ `requirements.txt` - Python dependencies

---

## 🎯 Validation Modes

### Mode 1: Backup Target (Read-Only) ✅

**Purpose**: Validate access to existing backup data

**Operations**:
- ✅ Mount target (s3fuse or NFS)
- ✅ List files/objects
- ✅ Read file metadata (`os.stat`)
- ✅ Read first 1KB of file
- ❌ NO write operations

**CLI**:
```bash
# Note: --namespace is NOT used (targets are cluster-scoped)
python3 target_validations.py \
    --target-name=my-backup-target \
    --type=backup \
    --group=threatscanning.trilio.io \
    --version=v1
```

**Kubernetes**: Controller automatically passes `--type=backup` for non-reporting targets (no namespace parameter)

---

### Mode 2: Reporting Target (Write-Enabled) ✅

**Purpose**: Validate ability to upload scan reports

**Operations**:
- ✅ Direct S3 API (no mounting)
- ✅ `head_bucket`, `list_objects`
- ✅ `put_object`, `get_object`
- ✅ `delete_object`

**CLI**:
```bash
# Note: --namespace is NOT used (targets are cluster-scoped)
python3 target_validations.py \
    --target-name=my-reporting-target \
    --type=reporting \
    --group=threatscanning.trilio.io \
    --version=v1
```

**Kubernetes**: Controller automatically passes `--type=reporting` if `trilio.io/reporting-target: "true"` annotation exists (no namespace parameter)

---

## 🔧 How It Works

### Controller Integration

```go
// In pkg/helpers/job_helper.go

// 1. Determine target type
targetType := "backup"
if target.IsReportingTarget() {
    targetType = "reporting"
}

// 2. For NFS: validate directly (already mounted via volume)
if target.IsNFSTarget() {
    validationCmd = "python3 target_validations.py --target-name=<name> --type=<type>"
}

// 3. For ObjectStore: mount first, then validate
else {
    mountCmd = "python3 mount_datastores.py --target-name=<name>"
    validateCmd = "python3 target_validations.py --target-name=<name> --type=<type>"
    validationCmd = mountCmd + " && " + validateCmd
}

// 4. Create validation job with privileged container (if ObjectStore)
if target.IsObjectStoreTarget() {
    container.SecurityContext.Privileged = true  // Needed for s3fuse
}
```

---

## 📊 Validation Flow Diagrams

### Backup Target (ObjectStore)
```
┌─────────────────────────────────────────────────────────────┐
│ Controller: Create Validation Job                           │
│ - Name: threat-scan-target-validation-<cred-hash>          │
│ - Image: <validator-image>                                  │
│ - Command: mount_datastores.py && target_validations.py    │
│ - Type: --type=backup                                       │
│ - Privileged: true (for s3fuse)                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Job Pod: Mount S3 via s3fuse                                │
│ - Reads target CRD                                          │
│ - Gets credentials from secret                              │
│ - Mounts S3 bucket at /triliodata                          │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Job Pod: Validate Read-Only Operations                      │
│ 1. Verify mount: os.path.ismount(/triliodata)              │
│ 2. List files: os.listdir(/triliodata)                     │
│ 3. Read metadata: os.stat(file)                            │
│ 4. Read content: open(file, 'rb').read(1024)               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Job Pod: Exit with Success                                  │
│ - Status: Completed                                         │
│ - Controller sees pod status → Updates Target.Status       │
└─────────────────────────────────────────────────────────────┘
```

### Reporting Target (ObjectStore)
```
┌─────────────────────────────────────────────────────────────┐
│ Controller: Create Validation Job                           │
│ - Name: threat-scan-target-validation-<cred-hash>          │
│ - Image: <validator-image>                                  │
│ - Command: target_validations.py --type=reporting          │
│ - Privileged: true (for potential S3 operations)           │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Job Pod: Validate S3 Write Operations (NO MOUNTING)        │
│ - Reads target CRD                                          │
│ - Gets credentials from secret                              │
│ - Uses boto3 directly                                       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Job Pod: Test S3 Operations via boto3                      │
│ 1. head_bucket → verify bucket exists                      │
│ 2. list_objects → verify list permission                   │
│ 3. put_object → create test-<uuid>.txt                     │
│ 4. get_object → read test file                             │
│ 5. delete_object → cleanup test file                       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Job Pod: Exit with Success                                  │
│ - Status: Completed                                         │
│ - Controller updates Target.Status to Available            │
└─────────────────────────────────────────────────────────────┘
```

---

## ✅ Implementation Checklist

All tasks completed! ✅

- [x] Copy k8s-commons/datastore-attacher to threat-scanning-architecture
- [x] Update API group to `threatscanning.trilio.io` in constants.py
- [x] Add `--type` flag (backup|reporting) to target_validations.py
- [x] Implement `validate_backup_target()` - mount + read-only validation
- [x] Implement `validate_reporting_target()` - direct S3 API validation
- [x] Implement `validate_nfs_backup_target()` - read-only NFS validation
- [x] Remove qcow2_verification logic
- [x] Remove write operations (validate_create, validate_update, validate_delete)
- [x] Update internal/constants.go with datastore-attacher paths
- [x] Update controller to pass `--type` flag to validation command
- [x] Add privileged security context for ObjectStore targets
- [x] Build and verify Go code compiles successfully

---

## 🧪 Quick Test

### 1. Create Test Target (Backup)
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-backup
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    bucketName: "my-backups"
    region: "us-east-1"
    credentialSecret:
      name: s3-creds
      namespace: threat-scanning-system
EOF
```

### 2. Check Validation Job
```bash
# List validation jobs
kubectl get jobs -n threat-scanning-system | grep threat-scan-target-validation

# Get validation logs
POD=$(kubectl get pods -n threat-scanning-system -l job-name=<job-name> -o name | head -1)
kubectl logs -n threat-scanning-system $POD
```

### 3. Expected Output
```
Target validation in progress for type: backup
✅ Verified /triliodata is mounted
✅ Successfully listed 5 objects in target
✅ Successfully read file metadata: backup-001.qcow2 (size=1073741824 bytes)
✅ Successfully read 1024 bytes from file
✅ Backup target validation completed successfully
================================================================================
🎉 Target 'test-backup' validation SUCCESSFUL (type: backup)
================================================================================
```

---

## 📚 Documentation

- **Full Details**: See `DATASTORE_ATTACHER_INTEGRATION.md`
- **Controller README**: See `CONTROLLER_README.md`
- **Architecture**: See `architecture.md`

---

## 🎉 Summary

✅ **Completed**: Full integration of k8s-commons datastore-attacher with threat-scanning-architecture  
✅ **Validated**: Go code compiles successfully  
✅ **Tested**: Build passes without errors  
✅ **Documented**: Comprehensive documentation with examples  
✅ **Ready**: For container image build and Kubernetes deployment  

**Next Steps**:
1. Build container image with datastore-attacher and Python dependencies
2. Update RBAC for privileged containers (ObjectStore targets)
3. Deploy and test with real S3/NFS targets
4. Verify validation logs and target status updates

