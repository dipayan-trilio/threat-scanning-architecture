# Prescan CLI Refactoring - Final Design

## Overview

The prescan CLI has been refactored based on the following requirements:
1. **Target mounting is handled by the controller** - Prescan assumes target is already mounted
2. **Type-specific implementations** - VM detection and metadata extraction are in detector classes
3. **Simplified workflow** - Prescan validates path, detects type, calls detector methods, updates CR
4. **Target name in labels** - Uses target name instead of UID for filtering

## Architecture

```
Controller (Go)
    ↓
    1. Mounts target to /triliodata using mount-datastore command
    ↓
    2. Creates prescan Job
    ↓
Prescan CLI (Python)
    ↓
    3. Validates backup path exists
    ↓
    4. Detects backup type (TVK/TVO) → returns detector instance
    ↓
    5. Calls detector.detect_vm_workload(backup_path)
    ↓
    6. Calls detector.extract_metadata(backup_path, backup_uid)
    ↓
    7. Updates ScanInstance CR
```

## Key Changes

### 1. Removed Target Mounting

**Before:**
```python
# Prescan validated and mounted target
target_cr = k8s_client.get_target(target_name)
mount_path = mount_target(target_name)
```

**After:**
```python
# Controller mounts target, prescan just validates path
full_backup_path = os.path.join(TRILIODATA_MOUNT_PATH, args.backup_path)
validate_backup_path(full_backup_path)
```

### 2. Type-Specific Detector Methods

**Added to `BaseBackupDetector`:**
```python
@abstractmethod
def detect_vm_workload(self, backup_path: str) -> bool:
    """Detect if backup contains VM workload."""
    pass

@abstractmethod
def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
    """Extract metadata from backup."""
    pass
```

**Implemented in `TVKBackupDetector`:**
```python
def detect_vm_workload(self, backup_path: str) -> bool:
    """
    Mounts metadata-snapshot.qcow2 using qemu-nbd.
    Reads metadata.json.
    Checks for VM/VMI/DV/VMPool resources.
    """
    # Implementation...

def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
    """
    Reads tvk-meta.json for instance ID.
    Parses path structure for backupplan/backup UIDs.
    Returns: {instance_id, backupplan_uid, backup_uid}
    """
    # Implementation...
```

**Stubbed in `TVOBackupDetector`:**
```python
def detect_vm_workload(self, backup_path: str) -> bool:
    return False  # TVO not implemented

def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
    raise NotImplementedError("TVO prescan not yet implemented")
```

### 3. Simplified Prescan CLI

**New workflow:**
```python
def main():
    # 1. Validate backup path (target already mounted)
    full_backup_path = os.path.join(TRILIODATA_MOUNT_PATH, args.backup_path)
    validate_backup_path(full_backup_path)
    
    # 2. Get target CR for metadata
    target_cr = k8s_client.get_target(args.target_name)
    
    # 3. Detect backup type
    backup_type, detector = detect_backup_type(...)
    
    # 4. Use detector for VM detection and metadata extraction
    is_vm_workload = detector.detect_vm_workload(full_backup_path)
    metadata = detector.extract_metadata(full_backup_path, args.backup_uid)
    
    # 5. Update ScanInstance CR
    labels = {
        'trilio.io/instance-id': metadata['instance_id'],
        'trilio.io/backup-target': args.target_name,  # ← target name
        'trilio.io/backupplan': metadata['backupplan_uid'],
        'trilio.io/backup': metadata['backup_uid']
    }
    annotations = {'trilio.io/vm-workload': str(is_vm_workload).lower()}
    status = {'type': backup_type}
    
    k8s_client.patch_scan_instance(args.scaninstance_name, labels, annotations, status)
```

### 4. Updated Labels

**Before:**
```yaml
labels:
  trilio.io/backup-target: target-uid  # UID for reference
```

**After:**
```yaml
labels:
  trilio.io/backup-target: target-name  # Name for filtering
```

**Rationale:** Cleanup already uses target name for filtering ScanInstances, so using name is more consistent.

## TVK Implementation Details

### VM Workload Detection

```python
def detect_vm_workload(self, backup_path: str) -> bool:
    """
    1. Check if metadata-snapshot.qcow2 exists
    2. Allocate free NBD device (/dev/nbd0-15)
    3. Connect qcow2 to NBD: sudo qemu-nbd -c /dev/nbd0 -r metadata-snapshot.qcow2
    4. Mount NBD device: sudo mount -o ro /dev/nbd0 /tmp/mount
    5. Read metadata.json from mount point
    6. Check for KubeVirt resources:
       - VirtualMachine
       - VirtualMachineInstance
       - DataVolume
       - VirtualMachinePool
    7. Unmount and disconnect NBD
    8. Return True if VM resources found, False otherwise
    """
```

### Metadata Extraction

```python
def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
    """
    1. Read tvk-meta.json from backup_path
    2. Extract instanceID from JSON
    3. Parse path structure:
       /triliodata/backupplan-uid/backup-uid/
       Extract: backupplan-uid and backup-uid
    4. Validate backup_uid matches path
    5. Return: {
         'instance_id': '...',
         'backupplan_uid': '...',
         'backup_uid': '...'
       }
    """
```

## Controller Integration

### Step 1: Mount Target

```go
// Create init container to mount target
initContainer := corev1.Container{
    Name:  "mount-target",
    Image: "datastore-attacher:latest",
    Command: []string{
        "python3",
        "/mount_utility/mount_by_target_crd/mount_datastores.py",
        "--target-name=" + targetName,
        "--group=threatscanning.trilio.io",
    },
    VolumeMounts: []corev1.VolumeMount{
        {
            Name:      "triliodata",
            MountPath: "/triliodata",
        },
    },
}
```

### Step 2: Run Prescan

```go
// Create prescan container
prescanContainer := corev1.Container{
    Name:  "prescan",
    Image: "prescan:latest",
    Command: []string{
        "python3",
        "/prescan/cli.py",
        "--target-name=" + targetName,
        "--backup-path=" + backupPath,
        "--backup-uid=" + backupUID,
        "--scaninstance-name=" + scanInstanceName,
    },
    VolumeMounts: []corev1.VolumeMount{
        {
            Name:      "triliodata",
            MountPath: "/triliodata",
        },
        {
            Name:      "dev",
            MountPath: "/dev",  // For qemu-nbd
        },
    },
    SecurityContext: &corev1.SecurityContext{
        Privileged: ptr.To(true),  // Required for qemu-nbd
    },
}
```

### Step 3: Share Volume

```go
volumes := []corev1.Volume{
    {
        Name: "triliodata",
        VolumeSource: corev1.VolumeSource{
            EmptyDir: &corev1.EmptyDirVolumeSource{},
        },
    },
    {
        Name: "dev",
        VolumeSource: corev1.VolumeSource{
            HostPath: &corev1.HostPathVolumeSource{
                Path: "/dev",
            },
        },
    },
}
```

## Files Modified

### New Methods Added

1. **`shared/backup_detection/base_detector.py`**
   - Added `detect_vm_workload()` abstract method
   - Added `extract_metadata()` abstract method

2. **`shared/backup_detection/tvk_detector.py`**
   - Implemented `detect_vm_workload()` with qemu-nbd mounting
   - Implemented `extract_metadata()` with tvk-meta.json parsing
   - Added `_check_vm_resources_in_metadata()` helper
   - Added `_allocate_nbd_device()` helper

3. **`shared/backup_detection/tvo_detector.py`**
   - Stubbed `detect_vm_workload()` (returns False)
   - Stubbed `extract_metadata()` (raises NotImplementedError)

### Modified

4. **`prescan/cli.py`**
   - Removed target validation and mounting
   - Simplified to use detector methods
   - Updated to use target name in labels

5. **`prescan/README.md`**
   - Updated workflow documentation
   - Removed target mounting section
   - Updated component descriptions

### Deleted

6. **`prescan/vm_detector.py`**
   - Functionality moved to detector classes

## Benefits

### 1. Cleaner Separation of Concerns
- **Controller**: Handles target mounting
- **Prescan**: Handles validation and metadata extraction

### 2. Type-Specific Implementations
- TVK and TVO have their own VM detection logic
- Easy to extend for different backup types

### 3. Reusable Detector Classes
- Same detectors used by poller and prescan
- Single source of truth for detection logic

### 4. Consistent Labeling
- Uses target name for filtering (matches cleanup logic)
- Easier to query ScanInstances by target

## Testing

### Unit Tests

```python
# Test TVK VM detection
detector = TVKBackupDetector(parsed_target, 'nfs', logger)
is_vm = detector.detect_vm_workload('/path/to/backup')
assert is_vm == True

# Test TVK metadata extraction
metadata = detector.extract_metadata('/path/to/backup', 'backup-uid')
assert 'instance_id' in metadata
assert 'backupplan_uid' in metadata
assert 'backup_uid' in metadata
```

### Integration Tests

```bash
# 1. Mount target
mount-datastore --target-name=test-target

# 2. Run prescan
python3 prescan/cli.py \
  --target-name=test-target \
  --backup-path=test-bp/test-backup \
  --backup-uid=test-backup-uid \
  --scaninstance-name=test-si

# 3. Verify ScanInstance labels
kubectl get scaninstance test-si -o yaml
```

## Future Enhancements

### TVO Support

1. Implement `TVOBackupDetector.detect_vm_workload()`
   - TVO-specific VM detection logic
   - Different metadata structure

2. Implement `TVOBackupDetector.extract_metadata()`
   - Read TVO metadata files
   - Parse TVO path structure

### Error Handling

1. Add retry logic for transient failures
2. Add timeout handling for long-running operations
3. Add detailed error messages for debugging

### Performance

1. Cache NBD device allocation
2. Parallel processing for multiple backups
3. Optimize qcow2 mounting

## Conclusion

The refactored prescan CLI:
- ✅ Delegates target mounting to controller
- ✅ Uses type-specific detector implementations
- ✅ Simplifies the prescan workflow
- ✅ Uses consistent labeling strategy
- ✅ Ready for controller integration

The design is clean, extensible, and follows the principle of separation of concerns.

