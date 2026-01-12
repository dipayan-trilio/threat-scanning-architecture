# Unified NFS Mounting Using mount_datastores.py

## Problem

The poller had **two different NFS mounting implementations**:

1. **Discovery Phase**: Used `mount_datastores.py` ✅
2. **Cleanup Phase**: Used custom `mount -t nfs` commands ❌

This was:
- ❌ Duplicating logic
- ❌ Inconsistent behavior
- ❌ Different mount points for same target
- ❌ More code to maintain

## Solution

**Use `mount_datastores.py` for BOTH cleanup and discovery phases!**

## Changes Made

### Before: Two Different Approaches

**Cleanup Phase** (Custom NFS mount):
```python
def _mount_nfs(self) -> str:
    metadata = self.parsed_target['metaData']
    nfs_export = metadata['nfsExport']
    mount_options = metadata.get('mountOptions', 'rw,hard,intr')
    
    # Custom mount point per target
    mount_path = f'/mnt/targets/{self.target_uid}'
    os.makedirs(mount_path, exist_ok=True)
    
    # Manual mount command
    mount_cmd = f"mount -t nfs -o {mount_options} {nfs_export} {mount_path}"
    utilities.run_cmd(mount_cmd)
    
    return mount_path  # Returns /mnt/targets/<uid>
```

**Discovery Phase** (Using mount_datastores.py):
```python
def mount_target_for_discovery(self) -> str:
    mount_cmd = (
        f"python3 {mount_script} "
        f"--target-name={self.target_name} "
        f"--group=threatscanning.trilio.io"
    )
    utilities.run_cmd(mount_cmd)
    
    return TRILIODATA_MOUNT_PATH  # Returns /triliodata
```

### After: Unified Approach

**Both Cleanup and Discovery** (Using mount_datastores.py):
```python
def _mount_nfs(self) -> str:
    """Mount NFS using datastore-attacher's mount script."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mount_script = os.path.join(
        script_dir, 
        'mount_utility', 
        'mount_by_target_crd', 
        'mount_datastores.py'
    )
    
    os.makedirs(TRILIODATA_MOUNT_PATH, exist_ok=True)
    
    mount_cmd = (
        f"python3 {mount_script} "
        f"--target-name={self.target_name} "
        f"--group=threatscanning.trilio.io"
    )
    
    utilities.run_cmd(mount_cmd)
    return TRILIODATA_MOUNT_PATH  # Always returns /triliodata
```

## Benefits

### 1. **Single Mount Point**

**Before**:
- Cleanup: `/mnt/targets/<target-uid>`
- Discovery: `/triliodata`

**After**:
- Both: `/triliodata` ✅

### 2. **Code Reuse**

**Before**:
- 2 different mount implementations
- ~50 lines of custom NFS mount code

**After**:
- 1 unified implementation
- ~20 lines reusing existing script

### 3. **Consistency**

**Before**:
- Cleanup: Manual credential parsing, mount options
- Discovery: Automatic via mount_datastores.py

**After**:
- Both: Automatic via mount_datastores.py ✅

### 4. **Maintainability**

**Before**:
- Bug fixes needed in 2 places
- Different behavior between phases

**After**:
- Single source of truth ✅
- Consistent behavior

## Mount Point: /triliodata

Both cleanup and discovery now use `/triliodata`:

```python
# Constant defined at top of base_handler.py
TRILIODATA_MOUNT_PATH = '/triliodata'

# Cleanup phase
mount_path = self._mount_nfs()  # Returns /triliodata
nfs_data = self._list_nfs_structure(mount_path)

# Discovery phase  
mount_path = self.mount_target_for_discovery()  # Returns /triliodata
backupplans = self.get_backupplans_with_new_backups(since_time)
```

## Flow Comparison

### Before: Cleanup Phase

```
Cleanup Phase
    ↓
_mount_nfs()
    ↓
Parse credentials manually
    ↓
Build mount command: "mount -t nfs -o rw,hard,intr <export> /mnt/targets/<uid>"
    ↓
utilities.run_cmd(mount_cmd)
    ↓
Mounted at /mnt/targets/<uid>
    ↓
List backups with find
    ↓
_unmount_nfs(/mnt/targets/<uid>)
```

### After: Cleanup Phase

```
Cleanup Phase
    ↓
_mount_nfs()
    ↓
Call mount_datastores.py
    ↓
Script handles:
  - Credential parsing
  - Mount options
  - NFS mount
    ↓
Mounted at /triliodata
    ↓
List backups with find
    ↓
_unmount_nfs(/triliodata)
```

## Why This Works

### mount_datastores.py Handles Everything

1. **Fetches Target CR** from Kubernetes
2. **Parses credentials** from secrets
3. **Determines target type** (NFS or S3)
4. **Applies mount options** from target spec
5. **Mounts to /triliodata** (default path)
6. **Error handling** built-in

### No Need for Custom Logic

The script already does:
- ✅ Credential parsing
- ✅ Mount option handling
- ✅ Error handling
- ✅ Logging
- ✅ Timeout management

## Code Reduction

### Lines of Code

**Before**:
- Custom NFS mount: ~30 lines
- Discovery mount: ~20 lines
- **Total**: ~50 lines

**After**:
- Unified mount function: ~20 lines (reused)
- **Total**: ~20 lines

**Reduction**: 60% less code! 🎉

### Functions

**Before**:
- `_mount_nfs()` - Custom implementation
- `mount_target_for_discovery()` - Uses script
- 2 different implementations

**After**:
- Both use same pattern
- 1 unified approach

## Testing

### Test NFS Cleanup
```bash
# Should mount to /triliodata
./poller/QUICK_TEST.sh nfs-target

# Verify mount point
mount | grep /triliodata
# Should show: <nfs-export> on /triliodata type nfs
```

### Test NFS Discovery
```bash
# Should also mount to /triliodata
./poller/QUICK_TEST.sh nfs-target 24

# Same mount point for both phases
```

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Cleanup Mount** | Custom `mount -t nfs` | `mount_datastores.py` |
| **Discovery Mount** | `mount_datastores.py` | `mount_datastores.py` |
| **Cleanup Path** | `/mnt/targets/<uid>` | `/triliodata` |
| **Discovery Path** | `/triliodata` | `/triliodata` |
| **Implementations** | 2 different | 1 unified |
| **Lines of Code** | ~50 | ~20 |
| **Maintenance** | 2 places | 1 place |
| **Consistency** | Different | Same ✅ |

## Files Modified

- **`cleanup/base_handler.py`**:
  - `_mount_nfs()`: Now uses `mount_datastores.py` instead of custom mount
  - `_unmount_nfs()`: Updated to expect `/triliodata` path
  - Both cleanup and discovery use same mounting approach

🎯 **Result**: Unified, consistent, maintainable NFS mounting across all poller phases!

