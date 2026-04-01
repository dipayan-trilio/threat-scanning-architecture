# VM Name Addition to ScanLocations

## Overview

Enhanced the `ScanLocation` API structure to include detailed VM PVC information (VM name, PVC name, and PVC path) instead of just PVC paths. This makes it easier to identify which VirtualMachine each PVC belongs to.

## Changes

### 1. API Changes (`api/v1/scaninstance_types.go`)

#### New Struct: `VMPVCInfo`

```go
// VMPVCInfo contains information about a VM PVC that needs scanning
type VMPVCInfo struct {
    // VMName is the name of the VirtualMachine that owns this PVC
    VMName string `json:"vmName"`

    // PVCName is the name of the PersistentVolumeClaim
    PVCName string `json:"pvcName"`

    // PVCPath is the path to the PVC data
    PVCPath string `json:"pvcPath"`
}
```

#### Updated Struct: `ScanLocation`

**Before:**
```go
type ScanLocation struct {
    Namespace   string   `json:"namespace,omitempty"`
    BackupUID   string   `json:"backupUID"`
    BackupPath  string   `json:"backupPath"`
    PVCPaths    []string `json:"pvcPaths"`  // Simple string array
}
```

**After:**
```go
type ScanLocation struct {
    Namespace   string        `json:"namespace,omitempty"`
    BackupUID   string        `json:"backupUID"`
    BackupPath  string        `json:"backupPath"`
    VMPVCs      []VMPVCInfo   `json:"vmPVCs"`  // Rich object array with VM metadata
}
```

### 2. Detector Changes (`tvk_detector.py`)

#### Updated Method: `_extract_vm_pvc_locations()`

**Before:**
```python
def _extract_vm_pvc_locations(self, backup_json: Dict) -> list:
    """Returns list of PVC path strings"""
    # ...
    vm_pvc_locations.append(location)  # Just the path string
    return vm_pvc_locations
```

**After:**
```python
def _extract_vm_pvc_locations(self, backup_json: Dict) -> list:
    """Returns list of dicts with VM name, PVC name, and PVC path"""
    # ...
    vm_name = owner.get('name', '')
    
    vm_pvc_infos.append({
        'vm_name': vm_name,      # NEW: VM owner name
        'pvc_name': pvc_name,    # NEW: PVC name
        'pvc_path': location     # Path (already existed)
    })
    return vm_pvc_infos
```

#### Updated: Namespace Backup Metadata

**Before:**
```python
scan_locations.append({
    'namespace': '',
    'backup_uid': extracted_backup_uid,
    'backup_path': relative_backup_path,
    'pvc_paths': pvc_paths  # List of strings
})
```

**After:**
```python
scan_locations.append({
    'namespace': '',
    'backup_uid': extracted_backup_uid,
    'backup_path': relative_backup_path,
    'vm_pvcs': vm_pvc_infos  # List of dicts with VM metadata
})
```

#### Updated: Cluster-Backup Metadata

**Before:**
```python
scan_locations.append({
    'namespace': ns_name,
    'backup_uid': child_backup_uid,
    'backup_path': child_location,
    'pvc_paths': pvc_paths  # List of strings
})
```

**After:**
```python
scan_locations.append({
    'namespace': ns_name,
    'backup_uid': child_backup_uid,
    'backup_path': child_location,
    'vm_pvcs': vm_pvc_infos  # List of dicts with VM metadata
})
```

### 3. Prescan CLI Changes (`prescan/cli.py`)

#### Updated: PVC Count Calculation

**Before:**
```python
total_pvc_count = sum(len(loc['pvc_paths']) for loc in scan_locations)
```

**After:**
```python
total_pvc_count = sum(len(loc['vm_pvcs']) for loc in scan_locations)
```

#### Updated: Kubernetes API Conversion

**Before:**
```python
scan_locations_camel.append({
    'namespace': loc.get('namespace', ''),
    'backupUID': loc['backup_uid'],
    'backupPath': loc['backup_path'],
    'pvcPaths': loc['pvc_paths']  # Simple array
})
```

**After:**
```python
# Convert VM PVC infos to camelCase
vm_pvcs_camel = []
for pvc_info in loc['vm_pvcs']:
    vm_pvcs_camel.append({
        'vmName': pvc_info['vm_name'],
        'pvcName': pvc_info['pvc_name'],
        'pvcPath': pvc_info['pvc_path']
    })

scan_locations_camel.append({
    'namespace': loc.get('namespace', ''),
    'backupUID': loc['backup_uid'],
    'backupPath': loc['backup_path'],
    'vmPVCs': vm_pvcs_camel  # Rich array with VM metadata
})
```

## Example Output

### Single Namespace Backup with VM

```yaml
status:
  type: TVK
  scanLocations:
  - namespace: ""
    backupUID: "1bbba2bd-a28c-4691-a588-284ac26f97f9"
    backupPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9"
    vmPVCs:
    - vmName: "vm-test-1"
      pvcName: "vol-vm-test-1"
      pvcPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9/custom/data-snapshot/vol-vm-test-1"
    - vmName: "vm-test-1"
      pvcName: "data-disk-vm-test-1"
      pvcPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9/custom/data-snapshot/data-disk-vm-test-1"
```

### Cluster-Backup with Multiple VMs

```yaml
status:
  type: TVK
  scanLocations:
  - namespace: "dp"
    backupUID: "1bbba2bd-a28c-4691-a588-284ac26f97f9"
    backupPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9"
    vmPVCs:
    - vmName: "vm-dp-1"
      pvcName: "vol-vm-dp-1"
      pvcPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9/custom/data-snapshot/vol-vm-dp-1"
  - namespace: "prod"
    backupUID: "2ccba3ce-bb3d-5782-b699-395bd42f98f0"
    backupPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/2ccba3ce-bb3d-5782-b699-395bd42f98f0"
    vmPVCs:
    - vmName: "vm-prod-1"
      pvcName: "vol-vm-prod-1"
      pvcPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/2ccba3ce-bb3d-5782-b699-395bd42f98f0/custom/data-snapshot/vol-vm-prod-1"
    - vmName: "vm-prod-2"
      pvcName: "vol-vm-prod-2"
      pvcPath: "35a9f73b-e134-4afa-a896-53e4b10ca70f/2ccba3ce-bb3d-5782-b699-395bd42f98f0/custom/data-snapshot/vol-vm-prod-2"
```

## Benefits

1. **Clear VM Ownership**: Immediately identify which VM each PVC belongs to without parsing paths
2. **Better Logging**: Can log VM names in addition to PVC names for debugging
3. **Easier Controller Logic**: Controller can easily group PVCs by VM or filter by VM name
4. **Future Boot Disk Detection**: When boot disk filtering is added, the VM name will help identify which PVC is the boot disk
5. **User-Friendly**: VM names are more meaningful than PVC names for operators/users

## Data Flow

1. **Detector** reads `backup.json` → extracts `owner.name` from each VM PVC → returns dict with `vm_name`, `pvc_name`, `pvc_path`
2. **Prescan CLI** receives scan_locations with `vm_pvcs` → converts snake_case to camelCase → patches `ScanInstance` status
3. **ScanInstance CR** stores rich metadata → `vmPVCs` array with `vmName`, `pvcName`, `pvcPath` fields
4. **Controller** reads `ScanInstance.status.scanLocations` → can iterate over VMs and their PVCs with full metadata

## Testing

After rebuilding the datastore-attacher image and redeploying:

1. Create a new `ScanInstance` for a backup with VMs
2. Check the prescan job logs - should show VM names being logged
3. Inspect the `ScanInstance` status:
   ```bash
   kubectl get scaninstance <name> -o yaml
   ```
4. Verify `status.scanLocations[].vmPVCs[]` contains `vmName`, `pvcName`, and `pvcPath` fields

## Backward Compatibility

This is a **breaking change** for the API. The `pvcPaths` field has been replaced with `vmPVCs`. Any existing code that reads `scanLocations` must be updated to use the new structure.

**Migration Steps:**
1. Update CRD: `kubectl apply -f config/crd/bases/threatscanning.trilio.io_scaninstances.yaml`
2. Rebuild and redeploy datastore-attacher image
3. Update any controller code that reads `scanLocations` to use new `vmPVCs` structure
4. Delete and recreate existing `ScanInstance` CRs (old structure won't work)
