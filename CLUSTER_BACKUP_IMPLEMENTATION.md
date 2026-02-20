# Cluster-Backup Support Implementation

## Overview

This document describes the implementation of cluster-backup support with two-level VM detection for the threat-scanning architecture.

## Implementation Date

February 16, 2026

## Summary

Implemented comprehensive support for cluster-backups with efficient two-level VM detection:
- **Level 1:** Quick `hasKubevirtResources` boolean check (skip if false)
- **Level 2:** Parse `dataSnapshots[]` to extract specific VM PVC paths (filter out container PVCs)

## Key Features

1. **Unified Data Structure**: Single `ScanLocations` field for both single namespace and cluster backups
2. **Two-Level Detection**: Efficient filtering that avoids parsing when unnecessary
3. **Granular PVC Selection**: Only VM-owned PVCs are included in scan locations
4. **Owner Reference Filtering**: Prevents duplicate ScanInstances for child backups
5. **Accurate VM Detection**: Annotation based on actual scannable content

## Changes Made

### 1. API Changes (Go)

**File:** `api/v1/scaninstance_types.go`

Added new types:
```go
type ScanLocation struct {
    Namespace   string   `json:"namespace,omitempty"`  // Empty for single ns backups
    BackupUID   string   `json:"backupUID"`
    BackupPath  string   `json:"backupPath"`
    PVCPaths    []string `json:"pvcPaths"`
}

type ScanInstanceStatusSpec struct {
    // ... existing fields ...
    ScanLocations []ScanLocation `json:"scanLocations,omitempty"`
}
```

**Purpose:**
- Unified structure for both single namespace and cluster backups
- For single namespace: One entry with empty `Namespace` field
- For cluster-backup: Multiple entries (one per child with VMs)
- Empty list means no VM workloads to scan

### 2. Prescan Detection (Python)

**File:** `datastore-attacher/shared/backup_detection/tvk_detector.py`

**New Methods:**
- `extract_metadata()` - Detects cluster vs namespace backup
- `_extract_namespace_backup_metadata()` - Two-level detection for single namespace
- `_extract_cluster_backup_metadata()` - Iterates children with two-level detection
- `_extract_vm_pvc_locations()` - Filters VM PVCs from dataSnapshots

**Detection Flow:**

#### Single Namespace Backup:
1. Read `tvk-meta.json` (get instance_id)
2. Read `backup.json`
3. **Level 1:** Check `hasKubevirtResources`
   - If `false`: Return with empty `scan_locations`
   - If `true`: Continue to Level 2
4. **Level 2:** Parse `status.snapshot.custom.dataSnapshots[]`
   - Filter PVCs with `owner.kind == 'VirtualMachine'`
   - Extract `location` for each VM PVC
5. Create single `ScanLocation` entry with empty namespace

#### Cluster-Backup:
1. Read `cluster-backup.json`
2. Get `backupInfos` (child backups map)
3. For each child backup:
   - Read child's `backup.json`
   - **Level 1:** Check `hasKubevirtResources`
     - If `false`: Skip this child
     - If `true`: Continue to Level 2
   - **Level 2:** Parse child's `dataSnapshots[]`
   - If VM PVCs found: Add `ScanLocation` entry
4. Set `is_vm_workload = true` only if `scan_locations` is not empty

### 3. Prescan CLI Updates (Python)

**File:** `datastore-attacher/prescan/cli.py`

**Changes:**
- Extract metadata with two-level detection
- Calculate total PVC count across all scan locations
- Update ScanInstance with:
  - `scanLocations` in status
  - `vm-workload` annotation based on final scan_locations length
  - `cluster-backup` annotation for identification
- Enhanced logging for both backup types

### 4. Poller Changes (Python)

**File:** `datastore-attacher/targetPoller/handlers/tvk_handler.py`

**Changes:**
- Enhanced `_read_scan_config()` to check backupplan ownerReferences
- If backupplan has `ClusterBackupPlan` as owner, returns `None` to skip entire backupplan
- **Why this is better:** 
  - Checks once per backupplan instead of once per backup
  - More efficient - skips at the backupplan level
  - All backups under a child backupplan are automatically skipped

**File:** `datastore-attacher/targetPoller/handlers/base_handler.py`

**Changes:**
- Updated `_read_scan_config()` documentation
- Removed backup-level filtering (now done at backupplan level)

**Logic:**
```python
# In _read_scan_config() - called once per backupplan
backupplan_json = read_json(backupplan_json_path)

owner_refs = backupplan_json.get('metadata', {}).get('ownerReferences', [])
is_child_of_cluster = any(
    owner.get('kind') == 'ClusterBackupPlan' 
    for owner in owner_refs
)

if is_child_of_cluster:
    # Skip entire backupplan - all its backups are cluster-backup children
    return None
```

**Result:**
- No ScanInstances created for namespace backupplans owned by ClusterBackupPlan
- Only creates ScanInstances for:
  - Standalone namespace backupplans
  - Cluster-backupplans (which handle children in prescan)

## Data Structure Examples

### Single Namespace Backup with VMs

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: scan-backup-xyz
  annotations:
    trilio.io/vm-workload: "true"
    trilio.io/cluster-backup: "false"
status:
  type: TVK
  scanLocations:
    - namespace: ""  # Empty for single namespace
      backupUID: "backup-xyz"
      backupPath: "backupplan-uid/backup-xyz"
      pvcPaths:
        - "backupplan-uid/backup-xyz/custom/data-snapshot/vol-src-as-dv"
        - "backupplan-uid/backup-xyz/custom/data-snapshot/vol-src-pvc"
```

### Cluster-Backup with VMs

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: scan-cluster-backup-abc
  annotations:
    trilio.io/vm-workload: "true"
    trilio.io/cluster-backup: "true"
status:
  type: TVK
  scanLocations:
    - namespace: "ns1"
      backupUID: "backup-uid-1"
      backupPath: "backupplan-uid-1/backup-uid-1"
      pvcPaths:
        - "backupplan-uid-1/backup-uid-1/custom/data-snapshot/vm-disk1"
    - namespace: "ns2"
      backupUID: "backup-uid-2"
      backupPath: "backupplan-uid-2/backup-uid-2"
      pvcPaths:
        - "backupplan-uid-2/backup-uid-2/custom/data-snapshot/vm-disk2"
        - "backupplan-uid-2/backup-uid-2/custom/data-snapshot/vm-disk3"
```

### Backup without VMs

```yaml
status:
  type: TVK
  scanLocations: []  # Empty - no VMs
  # Annotation: trilio.io/vm-workload: "false"
```

## Scenarios Handled

1. ✅ **Single namespace backup with VMs** - One scan location entry
2. ✅ **Single namespace backup without VMs** - Empty scan locations
3. ✅ **Cluster-backup with VMs in multiple namespaces** - Multiple scan location entries
4. ✅ **Cluster-backup where all children have no VMs** - Empty scan locations
5. ✅ **Mixed cluster-backup** - Only children with VMs included
6. ✅ **Container + VM mixed backup** - Only VM PVCs in scan locations

## Performance Benefits

1. **Fast Rejection**: Non-VM backups exit immediately (no dataSnapshots parsing)
2. **Targeted Processing**: Only parse dataSnapshots when VMs are present
3. **Efficient Filtering**: Container PVCs filtered out at Level 2
4. **No Duplicates**: Child backups of cluster-backups are not processed separately

## Future Enhancements

### Boot Disk Detection (Placeholder Added)

Currently, all VM PVCs (boot + data disks) are included in `pvcPaths`. Future enhancement:

```python
# TODO: Boot disk detection logic
# 1. Check DataVolume annotations for boot disk marker
# 2. Or check VM spec.template.spec.volumes for bootDisk: true
# 3. Or use naming convention (e.g., pvc ending with '-disk0')
# 4. Filter pvcPaths to include ONLY boot disks
```

### Controller Integration (Future)

When scan job creation is implemented:

```go
// controllers/scaninstance/controller.go
if len(scanInstance.Status.ScanLocations) > 0 {
    for _, scanLoc := range scanInstance.Status.ScanLocations {
        for _, pvcPath := range scanLoc.PVCPaths {
            // Create scan job for this VM PVC
            createScanJob(scanInstance, pvcPath)
        }
    }
}
```

## Testing Recommendations

1. Test with single namespace backup (VM workload)
2. Test with single namespace backup (no VMs)
3. Test with cluster-backup (all children have VMs)
4. Test with cluster-backup (some children have VMs, some don't)
5. Test with cluster-backup (no children have VMs)
6. Test with mixed container + VM backup
7. Verify no duplicate ScanInstances for child backups

## Files Modified

| File | Changes |
|------|---------|
| `api/v1/scaninstance_types.go` | Added ScanLocation struct |
| `shared/backup_detection/tvk_detector.py` | Added 3 new methods for two-level detection |
| `prescan/cli.py` | Updated to use scanLocations |
| `targetPoller/handlers/tvk_handler.py` | Added owner reference filtering (NFS) |
| `targetPoller/handlers/base_handler.py` | Added owner reference filtering (S3) |

## Migration Notes

**Existing ScanInstances:**
- Old ScanInstances will not have `scanLocations` field
- They will continue to work with existing logic
- New ScanInstances will use the new structure

**Backward Compatibility:**
- The `vm-workload` annotation is still set
- Existing helper methods like `HasVMWorkload()` continue to work
- Controllers can migrate to using `scanLocations` when ready

## Conclusion

This implementation provides a clean, efficient, and scalable approach to handling both single namespace and cluster backups with precise VM workload detection. The two-level filtering ensures optimal performance while the unified data structure simplifies controller logic.
