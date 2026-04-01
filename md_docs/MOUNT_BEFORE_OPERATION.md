# Mount Datastore Before Operations

**Date:** January 22, 2026  
**Status:** ✅ Complete

## Overview

All jobs (target validation, prescan, and poller) now **mount the datastore first** using `mount_by_target_crd` before executing their respective operations.

## Mount Command

The mount utility is invoked as:

```bash
python3 /opt/threat-scanning/datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py \
  --target-name=<target-name> \
  --group=threatscanning.trilio.io \
  --version=v1
```

This command:
- Fetches the Target CR
- Parses datastore credentials and configuration
- Mounts the datastore to `/triliodata` (NFS or ObjectStore via s3fuse)

## Updated Job Commands

### 1. Target Validation Job

#### For ObjectStore Backup Targets
```bash
# Mount first
python3 /opt/threat-scanning/datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py \
  --target-name=test-s3-target-1 \
  --group=threatscanning.trilio.io \
  --version=v1 \
&& \
# Then validate
target-validator \
  --target-name=test-s3-target-1 \
  --type=backup \
  --group=threatscanning.trilio.io \
  --version=v1
```

#### For NFS Targets
```bash
# No mount command needed - NFS mounted via volume
target-validator \
  --target-name=test-nfs-target \
  --type=backup \
  --group=threatscanning.trilio.io \
  --version=v1
```

#### For Reporting Targets
```bash
# No mount command needed - uses boto3 API
target-validator \
  --target-name=test-reporting-target \
  --type=reporting \
  --group=threatscanning.trilio.io \
  --version=v1
```

**Logic:**
```go
if target.IsNFSTarget() {
    // NFS: Direct mount via volume, no mount command
    validationCmd = validateCmd
} else if target.IsReportingTarget() {
    // Reporting: Uses boto3 API, no mounting
    validationCmd = validateCmd
} else {
    // ObjectStore backup: mount first, then validate
    validationCmd = fmt.Sprintf("%s && %s", mountCmd, validateCmd)
}
```

### 2. PreScan Job

```bash
# Mount first
python3 /opt/threat-scanning/datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py \
  --target-name=test-s3-target-1 \
  --group=threatscanning.trilio.io \
  --version=v1 \
&& \
# Then run prescan
prescan \
  --target-name=test-s3-target-1 \
  --backup-path=/backups/sample-backup \
  --backup-uid=backup-uid-12345 \
  --scaninstance-name=scaninstance-sample
```

**Note:** PreScan always mounts (both NFS and ObjectStore) because it needs filesystem access to read backup metadata.

**Logic:**
```go
// Mount first, then run prescan
preScanCmd := fmt.Sprintf("%s && %s", mountCmd, prescanCmd)
```

### 3. Target Poller CronJob

#### For ObjectStore Targets
```bash
# Mount first
python3 /opt/threat-scanning/datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py \
  --target-name=test-s3-target-1 \
  --group=threatscanning.trilio.io \
  --version=v1 \
&& \
# Then poll
target-poller \
  --target-name=test-s3-target-1 \
  --group=threatscanning.trilio.io \
  --version=v1
```

#### For NFS Targets
```bash
# No mount command needed - NFS mounted via volume
target-poller \
  --target-name=test-nfs-target \
  --group=threatscanning.trilio.io \
  --version=v1
```

**Logic:**
```go
if target.IsNFSTarget() {
    // NFS: Direct mount via volume, no mount command
    pollerCmd = pollCmd
} else {
    // ObjectStore: mount first, then poll
    pollerCmd = fmt.Sprintf("%s && %s", mountCmd, pollCmd)
}
```

## Why Mount First?

### Target Validation
- **ObjectStore Backup:** Needs to mount to verify filesystem access
- **NFS:** Uses Kubernetes NFS volume (no mount command needed)
- **Reporting:** Uses boto3 API for write validation (no mount needed)

### PreScan
- **All Targets:** Needs filesystem access to read backup metadata files:
  - `tvk-meta.json` - TVK metadata
  - `backup.json` - Backup metadata
  - VM workload detection requires reading backup structure

### Target Poller
- **ObjectStore:** Needs to mount to poll for new backups
- **NFS:** Uses Kubernetes NFS volume (no mount command needed)

## Command Flow Diagram

### ObjectStore Target (S3/MinIO/Azure)

```
┌─────────────────────────────────────────────────────────────────┐
│ Job Pod Starts                                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Mount Datastore                                         │
│                                                                 │
│ python3 .../mount_by_target_crd/mount_datastores.py \           │
│   --target-name=test-s3-target-1 \                              │
│   --group=threatscanning.trilio.io \                            │
│   --version=v1                                                  │
│                                                                 │
│ Actions:                                                        │
│ 1. Fetch Target CR from Kubernetes API                          │
│ 2. Parse credentials (from secret)                              │
│ 3. Mount via s3fuse to /triliodata                              │
│    └─> Requires: privileged=true, SYS_ADMIN capability          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Execute Operation                                       │
│                                                                 │
│ For Validation:                                                 │
│   target-validator --target-name=... --type=backup              │
│   └─> Validates /triliodata is accessible                       │
│                                                                 │
│ For PreScan:                                                    │
│   prescan --target-name=... --backup-path=... --backup-uid=...  │
│   └─> Reads /triliodata/<backup-path>/tvk-meta.json            │
│   └─> Reads /triliodata/<backup-path>/backup.json              │
│   └─> Updates ScanInstance CR                                   │
│                                                                 │
│ For Poller:                                                     │
│   target-poller --target-name=...                               │
│   └─> Polls /triliodata for new backups                         │
│   └─> Updates Target CR status                                  │
└─────────────────────────────────────────────────────────────────┘
```

### NFS Target

```
┌─────────────────────────────────────────────────────────────────┐
│ Job Pod Starts                                                  │
│                                                                 │
│ NFS Volume already mounted via Kubernetes:                      │
│   volumes:                                                      │
│     - name: nfs-target                                          │
│       nfs:                                                      │
│         server: nfs.example.com                                 │
│         path: /exports/backups                                  │
│   volumeMounts:                                                 │
│     - name: nfs-target                                          │
│       mountPath: /mnt/target                                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Execute Operation (No mount command needed)                     │
│                                                                 │
│ For Validation:                                                 │
│   target-validator --target-name=... --type=backup              │
│   └─> Validates /mnt/target is accessible                       │
│                                                                 │
│ For PreScan:                                                    │
│   prescan --target-name=... --backup-path=... --backup-uid=...  │
│   └─> Reads /mnt/target/<backup-path>/tvk-meta.json            │
│                                                                 │
│ For Poller:                                                     │
│   target-poller --target-name=...                               │
│   └─> Polls /mnt/target for new backups                         │
└─────────────────────────────────────────────────────────────────┘
```

## Security Context Requirements

| Target Type | Operation | Privileged | Reason |
|-------------|-----------|------------|--------|
| **ObjectStore** | Validation | ✅ Yes | s3fuse mount requires privileged + SYS_ADMIN |
| **ObjectStore** | PreScan | ✅ Yes | s3fuse mount requires privileged + SYS_ADMIN |
| **ObjectStore** | Poller | ✅ Yes | s3fuse mount requires privileged + SYS_ADMIN |
| **NFS** | Validation | ❌ No | NFS volume mounted by Kubernetes |
| **NFS** | PreScan | ✅ Yes | Added for consistency (may not be needed) |
| **NFS** | Poller | ❌ No | NFS volume mounted by Kubernetes |
| **Reporting** | Validation | ❌ No | boto3 API, no mounting |

## Implementation Details

### Code Location
File: `pkg/helpers/job_helper.go`

### Target Validation Job
```go
mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
    internal.Py3Path,
    fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
    target.Name)

validateCmd := fmt.Sprintf("target-validator --target-name=%s --type=%s --group=threatscanning.trilio.io --version=v1",
    target.Name, targetType)

if target.IsNFSTarget() {
    validationCmd = validateCmd
} else if target.IsReportingTarget() {
    validationCmd = validateCmd
} else {
    validationCmd = fmt.Sprintf("%s && %s", mountCmd, validateCmd)
}
```

### PreScan Job
```go
mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
    internal.Py3Path,
    fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
    targetName)

prescanCmd := fmt.Sprintf("prescan --target-name=%s --backup-path=%s --backup-uid=%s --scaninstance-name=%s",
    targetName, backupPath, backupUID, scanInstName)

preScanCmd := fmt.Sprintf("%s && %s", mountCmd, prescanCmd)
```

### Target Poller CronJob
```go
mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
    internal.Py3Path,
    fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
    target.Name)

pollCmd := fmt.Sprintf("target-poller --target-name=%s --group=threatscanning.trilio.io --version=v1",
    target.Name)

if target.IsNFSTarget() {
    pollerCmd = pollCmd
} else {
    pollerCmd = fmt.Sprintf("%s && %s", mountCmd, pollCmd)
}
```

## Environment Variables Used

From `internal/constants.go`:

```go
const (
    Py3Path              = "python3"
    BasePath             = "/opt/threat-scanning/datastore-attacher"
    DatastoreMountUtil   = "mount_utility/mount_by_target_crd/mount_datastores.py"
)
```

## Mount Path

All datastores are mounted to: **`/triliodata`**

This is defined in `mount_utility/constants.py`:
```python
DEFAULT_DATASTORE_BASE_PATH = "/triliodata"
```

## Testing

### Build Verification
```bash
cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture
make build
# ✅ Build successful
```

### Expected Behavior

1. **ObjectStore Target:**
   - Job starts → Mount command executes → s3fuse mounts to /triliodata → Operation executes
   
2. **NFS Target:**
   - Job starts → NFS already mounted via volume → Operation executes directly
   
3. **Reporting Target:**
   - Job starts → No mounting → Operation uses boto3 API directly

## Benefits

1. **Consistent Approach:** All operations follow the same pattern (mount → operate)
2. **Reuses Existing Code:** Leverages proven `mount_by_target_crd` utility
3. **Proper Error Handling:** Mount failures are caught before operations execute
4. **Clean Separation:** Mounting is separate from business logic

## Files Modified

1. **`pkg/helpers/job_helper.go`**
   - Updated `GetTargetValidatorJob()` to mount before validation
   - Updated `GetPreScanJob()` to mount before prescan
   - Updated `GetTargetPollerCronJob()` to mount before polling

---

**Implementation Complete** ✅  
All jobs now mount datastores before executing operations.

