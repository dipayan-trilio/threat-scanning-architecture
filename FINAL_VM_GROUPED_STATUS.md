# Implementation Complete: VM-Grouped PVC Structure

## Summary

Successfully restructured the `ScanLocation` API to group PVCs by their owning VirtualMachine. Each VM now maintains its own list of PVC paths, providing clear ownership and enabling future boot disk filtering.

## What Changed

### API Structure

**New Types:**
```go
type VMInfo struct {
    VMName   string   `json:"vmName"`
    PVCPaths []string `json:"pvcPaths"`
}

type ScanLocation struct {
    Namespace  string   `json:"namespace,omitempty"`
    BackupUID  string   `json:"backupUID"`
    BackupPath string   `json:"backupPath"`
    VMs        []VMInfo `json:"vms"`
}
```

### Key Benefits

1. **VM-Centric Organization**: Each VM is represented once with all its PVCs grouped together
2. **No Redundancy**: VM name appears once per VM (not repeated for each PVC)
3. **Easy Boot Disk Filtering**: Can filter each VM's `pvcPaths` array independently
4. **Clear Statistics**: Easy to count VMs, PVCs per VM, and total PVCs
5. **Natural Model**: Matches how users conceptually think about VMs and their disks

## Data Structure Example

```json
{
  "status": {
    "scanLocations": [
      {
        "namespace": "production",
        "backupUID": "abc-123",
        "backupPath": "plan1/abc-123",
        "vms": [
          {
            "vmName": "postgres-primary",
            "pvcPaths": [
              "plan1/abc-123/custom/data-snapshot/postgres-primary-boot",
              "plan1/abc-123/custom/data-snapshot/postgres-primary-data",
              "plan1/abc-123/custom/data-snapshot/postgres-primary-wal"
            ]
          },
          {
            "vmName": "redis-cache",
            "pvcPaths": [
              "plan1/abc-123/custom/data-snapshot/redis-cache-boot"
            ]
          }
        ]
      }
    ]
  }
}
```

**Insights from this structure:**
- 2 VMs in this backup location
- `postgres-primary` has 3 PVCs (boot + 2 data disks)
- `redis-cache` has 1 PVC (boot disk only)
- Total: 4 PVCs to scan

## Implementation Details

### 1. Detector (`tvk_detector.py`)

**Returns VM-to-PVCs mapping:**
```python
def _extract_vm_pvc_locations(self, backup_json: Dict) -> Dict[str, list]:
    """
    Returns:
        {
            'vm-name-1': ['path/to/pvc1', 'path/to/pvc2'],
            'vm-name-2': ['path/to/pvc3']
        }
    """
    vm_pvc_map = {}
    
    for ds in data_snapshots:
        vm_name = owner.get('name', '')
        if vm_name not in vm_pvc_map:
            vm_pvc_map[vm_name] = []
        vm_pvc_map[vm_name].append(location)
    
    return vm_pvc_map
```

**Converts to list format:**
```python
vms = []
for vm_name, pvc_paths in vm_pvc_map.items():
    vms.append({
        'vm_name': vm_name,
        'pvc_paths': pvc_paths
    })
```

### 2. Prescan CLI (`cli.py`)

**Calculates statistics:**
```python
total_vm_count = sum(len(loc['vms']) for loc in scan_locations)
total_pvc_count = sum(
    sum(len(vm['pvc_paths']) for vm in loc['vms'])
    for loc in scan_locations
)
```

**Converts to camelCase:**
```python
vms_camel = []
for vm in loc['vms']:
    vms_camel.append({
        'vmName': vm['vm_name'],
        'pvcPaths': vm['pvc_paths']
    })
```

## Files Modified

1. ✅ `api/v1/scaninstance_types.go`
   - Added `VMInfo` struct
   - Updated `ScanLocation` with `VMs []VMInfo`

2. ✅ `datastore-attacher/shared/backup_detection/tvk_detector.py`
   - Modified `_extract_vm_pvc_locations()` to return dict grouped by VM
   - Updated namespace and cluster-backup metadata extraction

3. ✅ `datastore-attacher/prescan/cli.py`
   - Updated statistics calculation
   - Enhanced camelCase conversion for nested VM structure
   - Improved logging messages

4. ✅ `config/crd/bases/threatscanning.trilio.io_scaninstances.yaml`
   - Regenerated with new schema

## Syntax Verification

✅ **Go Code**: CRD manifests generated successfully
✅ **Python Code**: Syntax check passed

## Testing Steps

1. **Apply updated CRD:**
   ```bash
   kubectl apply -f config/crd/bases/threatscanning.trilio.io_scaninstances.yaml
   ```

2. **Rebuild datastore-attacher image:**
   ```bash
   cd datastore-attacher
   docker build -t <registry>/datastore-attacher:latest .
   docker push <registry>/datastore-attacher:latest
   ```

3. **Test with real backup:**
   - Create or update ScanInstance
   - Check prescan job logs for VM grouping
   - Verify ScanInstance status has correct structure

4. **Verify output:**
   ```bash
   kubectl get scaninstance <name> -o jsonpath='{.status.scanLocations[0].vms}' | jq
   ```

   Expected:
   ```json
   [
     {
       "vmName": "vm-test",
       "pvcPaths": [
         "path/to/boot",
         "path/to/data"
       ]
     }
   ]
   ```

## Expected Log Output

### Detector Logs
```
Found VM PVC: vm=postgres-primary, pvc=postgres-primary-boot
Found VM PVC: vm=postgres-primary, pvc=postgres-primary-data
VM 'postgres-primary' has 2 PVC(s)
Found VM PVC: vm=redis-cache, pvc=redis-cache-boot
VM 'redis-cache' has 1 PVC(s)
Added scan location with 2 VM(s) and 3 PVC(s)
```

### Prescan CLI Logs
```
✓ Extracted metadata: instance_id=..., is_vm_workload=true, 
  scan_locations_count=1, total_vms=2, total_pvcs=3
✓ Successfully updated ScanInstance dc7462fa-...
✓ Namespace backup with 2 VM(s) and 3 PVC(s) to scan
✓ Prescan validation completed successfully
```

## Future: Boot Disk Filtering

When boot disk detection is implemented:

```python
# In _extract_vm_pvc_locations() or metadata extraction
for vm_name, pvc_paths in vm_pvc_map.items():
    boot_disk = identify_boot_disk(vm_name, pvc_paths)
    vms.append({
        'vm_name': vm_name,
        'pvc_paths': [boot_disk]  # Only boot disk
    })
```

Result will be:
```json
{
  "vms": [
    {
      "vmName": "postgres-primary",
      "pvcPaths": ["path/to/boot"]
    },
    {
      "vmName": "redis-cache",
      "pvcPaths": ["path/to/boot"]
    }
  ]
}
```

## Controller Integration (Next Step)

The controller will read the new structure:

```go
for _, scanLoc := range scanInstance.Status.ScanLocations {
    namespace := scanLoc.Namespace
    backupPath := scanLoc.BackupPath
    
    for _, vm := range scanLoc.VMs {
        vmName := vm.VMName
        pvcCount := len(vm.PVCPaths)
        
        logger.Info("Creating scan jobs for VM",
            "vm", vmName,
            "namespace", namespace,
            "pvc_count", pvcCount)
        
        for _, pvcPath := range vm.PVCPaths {
            // Create scan job for this PVC
            createScanJob(namespace, backupPath, vmName, pvcPath)
        }
    }
}
```

## Documentation

Created comprehensive documentation:
- [VM_GROUPED_PVC_STRUCTURE.md](./VM_GROUPED_PVC_STRUCTURE.md) - Complete implementation guide
- [SCANLOCATION_API_EVOLUTION.md](./SCANLOCATION_API_EVOLUTION.md) - Evolution from V1 to V3
- This status document

## Completion Checklist

- [x] API types updated (`VMInfo` struct, `ScanLocation.VMs`)
- [x] Detector groups PVCs by VM name
- [x] Namespace backup metadata uses VM grouping
- [x] Cluster-backup metadata uses VM grouping
- [x] Prescan CLI calculates VM and PVC statistics
- [x] Prescan CLI converts to camelCase correctly
- [x] CRD regenerated and validated
- [x] Python syntax verified
- [x] Documentation created
- [ ] Rebuild and redeploy datastore-attacher
- [ ] Test with real backups
- [ ] Update controller to use new structure

## Next Steps

1. **Rebuild Image**: Build new datastore-attacher image with changes
2. **Deploy**: Push and deploy the updated image
3. **Test**: Verify with actual VM backups (single namespace and cluster)
4. **Controller**: Update controller logic to iterate over `VMs` array
5. **Boot Disk**: Add boot disk detection logic (future enhancement)

---

**Status**: ✅ Implementation complete and ready for testing!
