# Disk Image Path Prefix Fix

## Problem

The ConfigMap was generating disk image paths with incorrect formatting when PVC paths didn't start with `/`:

### Before Fix
```
PVCPath: "backups/backup-123/vm-disk"
Result:  "/triliodatabackups/backup-123/vm-disk"  ❌ (missing separator)
```

### Expected
```
PVCPath: "backups/backup-123/vm-disk"
Result:  "/triliodata/backups/backup-123/vm-disk"  ✅ (proper separator)
```

## Root Cause

The path construction used string concatenation without ensuring a separator:

```go
// Before
diskImage = fmt.Sprintf("/triliodata%s", vm.PVCPaths[0])
```

If `vm.PVCPaths[0]` was `"backups/..."` (no leading slash), the result would be `/triliodatabackups/...` instead of `/triliodata/backups/...`.

## Solution

Added explicit check to ensure the PVC path starts with `/`:

```go
// After
pvcPath := vm.PVCPaths[0]
if !strings.HasPrefix(pvcPath, "/") {
    pvcPath = "/" + pvcPath
}
diskImage = fmt.Sprintf("/triliodata%s", pvcPath)
```

## Examples

### Case 1: Path with Leading Slash (Standard)
```go
Input:  vm.PVCPaths[0] = "/backups/backup-123/vm-disk"
Check:  strings.HasPrefix("/backups/...", "/") = true
Action: No modification needed
Result: "/triliodata/backups/backup-123/vm-disk" ✅
```

### Case 2: Path without Leading Slash (Edge Case)
```go
Input:  vm.PVCPaths[0] = "backups/backup-123/vm-disk"
Check:  strings.HasPrefix("backups/...", "/") = false
Action: Add "/" prefix → "/backups/backup-123/vm-disk"
Result: "/triliodata/backups/backup-123/vm-disk" ✅
```

### Case 3: Empty or Root Path
```go
Input:  vm.PVCPaths[0] = ""
Check:  strings.HasPrefix("", "/") = false
Action: Add "/" prefix → "/"
Result: "/triliodata/" ✅
```

## ConfigMap Output

After the fix, the ConfigMap will always have properly formatted paths:

```json
{
  "vm_artifacts": {
    "web-server_production": {
      "disk_image": "/triliodata/backups/backup-abc123/production/web-server-boot-pvc",
      ...
    }
  }
}
```

## Scan Job Access

The scan job can now correctly access disk images:

```python
# In scan job container
disk_image = "/triliodata/backups/backup-abc123/production/web-server-boot-pvc"

# Target is mounted at /triliodata
# File is accessible at the exact path
with open(disk_image, 'rb') as f:
    disk_data = f.read()
```

## Files Modified

- **pkg/helpers/job_helper.go**
  - Added `strings` import
  - Updated `GetScanConfigMapData()` to ensure PVC paths start with `/` (lines 725-738)

## Testing

### Verification Command

```bash
# Get ConfigMap
kubectl get configmap scan-config-<scaninstance-name> -o yaml

# Extract disk_image paths
kubectl get configmap scan-config-<scaninstance-name> \
  -o jsonpath='{.data.vm_artifacts_configuration\.json}' | \
  jq -r '.vm_artifacts[].disk_image'

# Expected output (all paths should start with /triliodata/):
# /triliodata/backups/backup-123/namespace/vm1-boot-pvc
# /triliodata/backups/backup-123/namespace/vm2-boot-pvc
```

### Test Cases

1. **Standard Path** (with leading `/`)
   ```
   Input:  ["/backups/backup-123/vm-disk"]
   Output: "/triliodata/backups/backup-123/vm-disk"
   ```

2. **Relative Path** (without leading `/`)
   ```
   Input:  ["backups/backup-123/vm-disk"]
   Output: "/triliodata/backups/backup-123/vm-disk"
   ```

3. **Root-Relative Path**
   ```
   Input:  ["backup-123/vm-disk"]
   Output: "/triliodata/backup-123/vm-disk"
   ```

## Build Verification

```bash
cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture
make build
# ✅ Build succeeded
```

## Why This Matters

1. **Correctness**: Scan job needs exact paths to access disk images
2. **Mount Point**: Target is mounted at `/triliodata`, not `/triliodatabackups`
3. **File Access**: Incorrect paths cause "file not found" errors during scanning
4. **Consistency**: All disk image paths should follow the same format

## Related Documentation

- [CONFIGMAP_FORMAT.md](CONFIGMAP_FORMAT.md): Full ConfigMap structure documentation
- [BOOT_DISK_ONLY_SCANNING.md](BOOT_DISK_ONLY_SCANNING.md): Boot disk filtering logic
- [SCAN_JOB_MOUNT_AND_SCAN.md](SCAN_JOB_MOUNT_AND_SCAN.md): Target mounting and scan execution
