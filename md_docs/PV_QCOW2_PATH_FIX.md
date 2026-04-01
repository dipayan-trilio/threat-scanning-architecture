# Fix: Add pv.qcow2 Suffix to Disk Image Paths in ConfigMap

## Problem

The scan configmap was being created with incomplete disk image paths. The PVC paths from `ScanInstance.status.scanLocations` were missing the `/pv.qcow2` suffix that points to the actual disk image file.

### Example Issue

**What We Had:**
```json
{
  "vm_artifacts": {
    "ubuntu-vm_namespace1": {
      "disk_image": "/triliodata/dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1",
      ...
    }
  }
}
```

**What We Need:**
```json
{
  "vm_artifacts": {
    "ubuntu-vm_namespace1": {
      "disk_image": "/triliodata/dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1/pv.qcow2",
      ...
    }
  }
}
```

## Root Cause

In `pkg/helpers/job_helper.go`, the `GetScanConfigMapData()` function was constructing the disk image path by concatenating:
- `internal.DefaultDatastoreBase` = `/triliodata`
- `vm.PVCPaths[0]` = `dipayan-ts-namespace1-e8d1e3f6/backups/.../dataSnapshots/ubuntu-vm-disk-1`

But it was not appending `/pv.qcow2` at the end to point to the actual QCOW2 disk image file.

## Solution

Updated the disk image path construction to append `/pv.qcow2`:

### Code Change

**File: `pkg/helpers/job_helper.go`**

**Before:**
```go
pvcPath := vm.PVCPaths[0]
if !strings.HasPrefix(pvcPath, "/") {
    pvcPath = "/" + pvcPath
}
diskImage = fmt.Sprintf("%s%s", internal.DefaultDatastoreBase, pvcPath)
// Result: /triliodata/a/b/dataSnapshots/vm-disk-1
```

**After:**
```go
pvcPath := vm.PVCPaths[0]
if !strings.HasPrefix(pvcPath, "/") {
    pvcPath = "/" + pvcPath
}
// Construct full path: /triliodata/<pvc-path>/pv.qcow2
diskImage = fmt.Sprintf("%s%s/pv.qcow2", internal.DefaultDatastoreBase, pvcPath)
// Result: /triliodata/a/b/dataSnapshots/vm-disk-1/pv.qcow2
```

## Path Structure Breakdown

### From Prescan Job

The prescan job detects VM PVC paths from `backup.json`:

```json
{
  "dataSnapshots": [
    {
      "volumeName": "ubuntu-vm-disk-1",
      "location": "dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1"
    }
  ]
}
```

This `location` value is stored in `ScanInstance.status.scanLocations[].vms[].pvcPaths[]`.

### In Scan Job

The scan job needs to access the actual disk image file, which has the structure:

```
/triliodata/                                    ← Mounted target root
  └── dipayan-ts-namespace1-e8d1e3f6/          ← Instance ID
      └── backups/
          └── bc17e8b8-.../                     ← Backup UID
              └── dataSnapshots/
                  └── ubuntu-vm-disk-1/         ← PVC snapshot directory
                      └── pv.qcow2              ← Actual disk image file ✅
```

The `/pv.qcow2` suffix is the actual QCOW2 file that contains the VM disk data and needs to be scanned.

## ConfigMap Example

### Before Fix
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scan-config-test-si
data:
  config.json: |
    {
      "vm_artifacts": {
        "ubuntu-vm_namespace1": {
          "hostname": "ubuntu-vm",
          "disk_image": "/triliodata/dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1",
          "collection_time": "2026-02-19T08:39:58Z",
          "priority": "high",
          "suspected_compromise": true
        }
      }
    }
```

### After Fix
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scan-config-test-si
data:
  config.json: |
    {
      "vm_artifacts": {
        "ubuntu-vm_namespace1": {
          "hostname": "ubuntu-vm",
          "disk_image": "/triliodata/dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1/pv.qcow2",
          "collection_time": "2026-02-19T08:39:58Z",
          "priority": "high",
          "suspected_compromise": true
        }
      }
    }
```

## Why This Matters

The scan job (enhanced-soc-analysis scanner) expects the `disk_image` field to point to an actual QCOW2 file that it can open and analyze. Without the `/pv.qcow2` suffix:

❌ **Incorrect path**: `/triliodata/.../ubuntu-vm-disk-1` (directory)
- Scanner tries to open this path as a file → fails
- `open("/triliodata/.../ubuntu-vm-disk-1")` → "Is a directory" error

✅ **Correct path**: `/triliodata/.../ubuntu-vm-disk-1/pv.qcow2` (file)
- Scanner can successfully open and read the QCOW2 image
- `open("/triliodata/.../ubuntu-vm-disk-1/pv.qcow2")` → success

## Testing

To verify the fix works:

1. **Create a ScanInstance** with VM workload
2. **Check the configmap** after prescan completes:
   ```bash
   kubectl get configmap scan-config-<scaninstance-name> -n threat-scanning-system -o yaml
   ```
3. **Verify** the `disk_image` field ends with `/pv.qcow2`
4. **Check scan job logs** to ensure it can successfully open the disk image

## Files Modified

| File | Change |
|------|--------|
| `pkg/helpers/job_helper.go` | Added `/pv.qcow2` suffix to disk image path in `GetScanConfigMapData()` |

## Impact

✅ **Compilation**: Code compiles successfully
✅ **Functionality**: Scan job can now correctly locate and open VM disk images
✅ **Backward Compatibility**: Only affects newly created configmaps, existing failed scans need to be retried

## Related Constants

From `internal/constants.go`:

```go
// DefaultDatastoreBase is the default mount path for datastores (NFS, ObjectStore)
// This is where the target is mounted in prescan and scan jobs
// Matches k8s-triliovault's DefaultDatastoreBase constant
DefaultDatastoreBase = "/triliodata"
```

This constant ensures consistent paths between:
- **Prescan job**: Detects backups at `/triliodata/...`
- **Scan job**: Accesses disk images at `/triliodata/.../pv.qcow2`
- **Target mount**: Both jobs mount the target at `/triliodata`

## Summary

The fix ensures that the disk image paths in the scan configmap correctly point to the actual QCOW2 files by appending `/pv.qcow2` to the PVC path. This allows the enhanced-soc-analysis scanner to successfully open and analyze VM disk images from TrilioVault backups.

**Change**: `diskImage = fmt.Sprintf("%s%s/pv.qcow2", internal.DefaultDatastoreBase, pvcPath)`

**Result**: Paths now correctly include the `/pv.qcow2` suffix pointing to the actual disk image file.
