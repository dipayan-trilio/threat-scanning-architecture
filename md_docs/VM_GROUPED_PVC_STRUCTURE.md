# VM-Grouped PVC Structure Implementation

## Overview

Restructured the `ScanLocation` API to group PVCs by their owning VirtualMachine. Each VM now has a list of PVC paths, making it easy to see which PVCs belong to which VM and enabling future boot disk filtering.

## API Structure

### VMInfo Type

```go
// VMInfo contains information about a VM and its PVCs that need scanning
type VMInfo struct {
    // VMName is the name of the VirtualMachine
    VMName string `json:"vmName"`

    // PVCPaths contains the list of PVC paths for this VM
    // For now, includes all VM PVCs (boot disk + data disks)
    // Future: Will be filtered to include only the boot disk
    PVCPaths []string `json:"pvcPaths"`
}
```

### ScanLocation Type

```go
// ScanLocation represents a backup location with VMs to scan
type ScanLocation struct {
    Namespace   string     `json:"namespace,omitempty"`
    BackupUID   string     `json:"backupUID"`
    BackupPath  string     `json:"backupPath"`
    VMs         []VMInfo   `json:"vms"`  // List of VMs with their PVC paths
}
```

## Data Structure Example

### Single Namespace Backup with Multiple VMs

```json
{
  "status": {
    "type": "TVK",
    "scanLocations": [
      {
        "namespace": "",
        "backupUID": "1bbba2bd-a28c-4691-a588-284ac26f97f9",
        "backupPath": "35a9f73b-.../1bbba2bd-...",
        "vms": [
          {
            "vmName": "postgres-primary",
            "pvcPaths": [
              "35a9f73b-.../custom/data-snapshot/postgres-primary-boot",
              "35a9f73b-.../custom/data-snapshot/postgres-primary-data"
            ]
          },
          {
            "vmName": "postgres-replica",
            "pvcPaths": [
              "35a9f73b-.../custom/data-snapshot/postgres-replica-boot"
            ]
          }
        ]
      }
    ]
  }
}
```

### Cluster-Backup with VMs in Multiple Namespaces

```json
{
  "status": {
    "type": "TVK",
    "scanLocations": [
      {
        "namespace": "database",
        "backupUID": "abc-123",
        "backupPath": "plan1/abc-123",
        "vms": [
          {
            "vmName": "postgres-primary",
            "pvcPaths": [
              "plan1/abc-123/custom/data-snapshot/postgres-primary-boot",
              "plan1/abc-123/custom/data-snapshot/postgres-primary-data",
              "plan1/abc-123/custom/data-snapshot/postgres-primary-logs"
            ]
          },
          {
            "vmName": "redis-cache",
            "pvcPaths": [
              "plan1/abc-123/custom/data-snapshot/redis-cache-boot"
            ]
          }
        ]
      },
      {
        "namespace": "frontend",
        "backupUID": "def-456",
        "backupPath": "plan1/def-456",
        "vms": [
          {
            "vmName": "web-server",
            "pvcPaths": [
              "plan1/def-456/custom/data-snapshot/web-server-boot",
              "plan1/def-456/custom/data-snapshot/web-server-static-content"
            ]
          }
        ]
      }
    ]
  }
}
```

## Implementation Details

### 1. Detector Changes (`tvk_detector.py`)

#### Method: `_extract_vm_pvc_locations()`

**Returns a dict mapping VM name to list of PVC paths:**

```python
{
    'postgres-primary': [
        'plan1/backup1/custom/data-snapshot/postgres-primary-boot',
        'plan1/backup1/custom/data-snapshot/postgres-primary-data'
    ],
    'postgres-replica': [
        'plan1/backup1/custom/data-snapshot/postgres-replica-boot'
    ]
}
```

**Implementation:**
```python
vm_pvc_map = {}

for ds in data_snapshots:
    # ... extract owner info ...
    vm_name = owner.get('name', '')
    
    # Group by VM name
    if vm_name not in vm_pvc_map:
        vm_pvc_map[vm_name] = []
    
    vm_pvc_map[vm_name].append(location)

return vm_pvc_map
```

#### Namespace Backup Metadata

```python
vm_pvc_map = self._extract_vm_pvc_locations(backup_json)

# Convert map to list of VM entries
vms = []
for vm_name, pvc_paths in vm_pvc_map.items():
    vms.append({
        'vm_name': vm_name,
        'pvc_paths': pvc_paths
    })

scan_locations.append({
    'namespace': '',
    'backup_uid': extracted_backup_uid,
    'backup_path': relative_backup_path,
    'vms': vms
})
```

#### Cluster-Backup Metadata

Same structure, but with namespace populated for each child backup.

### 2. Prescan CLI Changes (`cli.py`)

#### Calculate VM and PVC Counts

```python
total_vm_count = sum(len(loc['vms']) for loc in scan_locations)
total_pvc_count = sum(
    sum(len(vm['pvc_paths']) for vm in loc['vms'])
    for loc in scan_locations
)
```

#### Convert to CamelCase for K8s API

```python
scan_locations_camel = []
for loc in scan_locations:
    vms_camel = []
    for vm in loc['vms']:
        vms_camel.append({
            'vmName': vm['vm_name'],
            'pvcPaths': vm['pvc_paths']  # Already a list
        })
    
    scan_locations_camel.append({
        'namespace': loc.get('namespace', ''),
        'backupUID': loc['backup_uid'],
        'backupPath': loc['backup_path'],
        'vms': vms_camel
    })
```

## Benefits

### 1. Clear VM Organization
```yaml
vms:
- vmName: "postgres-primary"
  pvcPaths:
  - "path/to/boot-disk"
  - "path/to/data-disk-1"
  - "path/to/data-disk-2"
- vmName: "postgres-replica"
  pvcPaths:
  - "path/to/boot-disk"
```

**Immediately clear:**
- `postgres-primary` has 3 PVCs (1 boot + 2 data disks)
- `postgres-replica` has 1 PVC (boot disk only)

### 2. Easy Boot Disk Filtering (Future)

When boot disk detection is added:

```python
# Filter to keep only boot disk for each VM
for vm in vms:
    boot_disk = identify_boot_disk(vm['pvcPaths'])
    vm['pvcPaths'] = [boot_disk]
```

Result:
```yaml
vms:
- vmName: "postgres-primary"
  pvcPaths:
  - "path/to/boot-disk"  # Only boot disk
- vmName: "postgres-replica"
  pvcPaths:
  - "path/to/boot-disk"  # Only boot disk
```

### 3. Controller Logic

```go
for _, scanLoc := range scanInstance.Status.ScanLocations {
    for _, vm := range scanLoc.VMs {
        logger.Info("Processing VM", 
            "vm", vm.VMName, 
            "pvc_count", len(vm.PVCPaths))
        
        // Iterate over all PVCs for this VM
        for _, pvcPath := range vm.PVCPaths {
            createScanJob(scanLoc, vm.VMName, pvcPath)
        }
    }
}
```

### 4. Statistics and Reporting

Easy to calculate:
- **Total VMs**: Count of all VM entries across all scan locations
- **Total PVCs**: Sum of all PVC path lists
- **VMs by namespace**: Group by `scanLocation.namespace`
- **Multi-disk VMs**: Filter VMs where `len(pvcPaths) > 1`

## Logging Output

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
✓ Namespace backup with 2 VM(s) and 3 PVC(s) to scan
```

## Testing

### Test Case 1: Single VM with Multiple PVCs

**Scenario:** VM with boot disk + 2 data disks

**Expected Output:**
```yaml
vms:
- vmName: "test-vm"
  pvcPaths:
  - "path/to/boot"
  - "path/to/data-1"
  - "path/to/data-2"
```

### Test Case 2: Multiple VMs with Different PVC Counts

**Scenario:** 
- VM1: 1 PVC (boot only)
- VM2: 3 PVCs (boot + 2 data)

**Expected Output:**
```yaml
vms:
- vmName: "vm1"
  pvcPaths:
  - "path/to/vm1-boot"
- vmName: "vm2"
  pvcPaths:
  - "path/to/vm2-boot"
  - "path/to/vm2-data-1"
  - "path/to/vm2-data-2"
```

### Test Case 3: Cluster-Backup with VMs in Multiple Namespaces

**Expected Output:**
```yaml
scanLocations:
- namespace: "ns1"
  vms:
  - vmName: "vm-ns1"
    pvcPaths: [...]
- namespace: "ns2"
  vms:
  - vmName: "vm-ns2-a"
    pvcPaths: [...]
  - vmName: "vm-ns2-b"
    pvcPaths: [...]
```

## Future Enhancements

### Boot Disk Detection

1. **Add detection logic** in `_extract_vm_pvc_locations()`:
   ```python
   def _identify_boot_disk(vm_name: str, pvc_list: list) -> str:
       # Logic to identify boot disk from PVC list
       # Could use:
       # - PVC naming conventions (e.g., "*-boot", "*-root")
       # - PVC annotations/labels from backup metadata
       # - Volume order or role metadata
       pass
   ```

2. **Filter in metadata extraction**:
   ```python
   for vm_name, pvc_paths in vm_pvc_map.items():
       boot_disk = self._identify_boot_disk(vm_name, pvc_paths)
       vms.append({
           'vm_name': vm_name,
           'pvc_paths': [boot_disk]  # Only boot disk
       })
   ```

3. **Result**: `pvcPaths` array will contain only one element (the boot disk)

## Files Modified

- `api/v1/scaninstance_types.go` - Added `VMInfo` struct, updated `ScanLocation`
- `datastore-attacher/shared/backup_detection/tvk_detector.py` - Return dict grouped by VM
- `datastore-attacher/prescan/cli.py` - Convert VM-grouped structure to camelCase
- `config/crd/bases/threatscanning.trilio.io_scaninstances.yaml` - Generated CRD

## Migration from Previous Structure

**Previous (flat list of PVCs with VM name repeated):**
```json
{
  "vmPVCs": [
    {"vmName": "vm1", "pvcName": "pvc1", "pvcPath": "path1"},
    {"vmName": "vm1", "pvcName": "pvc2", "pvcPath": "path2"},
    {"vmName": "vm2", "pvcName": "pvc3", "pvcPath": "path3"}
  ]
}
```

**Current (grouped by VM):**
```json
{
  "vms": [
    {"vmName": "vm1", "pvcPaths": ["path1", "path2"]},
    {"vmName": "vm2", "pvcPaths": ["path3"]}
  ]
}
```

**Benefits:**
- No repetition of VM names
- Clearer ownership relationship
- Easier to implement boot disk filtering (apply to each VM's list)
- More efficient data structure
