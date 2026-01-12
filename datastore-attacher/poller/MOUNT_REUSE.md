# Reusing Datastore-Attacher Mount Logic

## Problem

The poller was trying to reimplement NFS and S3 mounting logic, which is:
- ❌ Duplicating existing code
- ❌ Error-prone (missing s3fuse implementation)
- ❌ Hard to maintain (two places to update)

## Solution

**Reuse the existing `mount_datastores.py` script** which already handles:
- ✅ NFS mounting with proper options
- ✅ S3 mounting with s3fuse
- ✅ Credential parsing
- ✅ Error handling
- ✅ All edge cases

## Implementation

### Before (Broken)

```python
def _mount_nfs_to_triliodata(self) -> str:
    # Custom NFS mounting code...
    subprocess.run(['mount', '-t', 'nfs', ...])

def _mount_s3_to_triliodata(self) -> str:
    # Not implemented!
    raise NotImplementedError("S3 mounting using s3fuse is not yet implemented")
```

### After (Working)

```python
def mount_target_for_discovery(self) -> str:
    """
    Mount target using datastore-attacher's mount script.
    Works for both NFS and S3.
    """
    # Call existing mount script
    mount_cmd = [
        'python3',
        'mount_utility/mount_by_target_crd/mount_datastores.py',
        f'--target-name={self.target_name}',
        '--group=threatscanning.trilio.io'
    ]
    
    subprocess.run(mount_cmd, check=True, timeout=300)
    return '/triliodata'
```

## How It Works

### 1. Script Location
```
datastore-attacher/
├── mount_utility/
│   └── mount_by_target_crd/
│       └── mount_datastores.py  ← The script we call
└── poller/
    └── cleanup/
        └── base_handler.py  ← Calls the script
```

### 2. Script Parameters

```bash
python3 mount_datastores.py \
  --target-name=minio-target \
  --group=threatscanning.trilio.io
```

**Parameters**:
- `--target-name`: Name of the Target CR
- `--group`: CRD group (defaults to `triliovault.trilio.io`, we override to `threatscanning.trilio.io`)

**Mount Path**: 
- Automatically mounts to `/triliodata` (defined in `constants.DEFAULT_DATASTORE_BASE_PATH`)

### 3. What the Script Does

1. **Fetches Target CR** from Kubernetes
2. **Parses credentials** from secrets/configmaps
3. **Determines target type** (NFS or S3)
4. **Mounts appropriately**:
   - **NFS**: Uses `mount -t nfs` with proper options
   - **S3**: Uses s3fuse with all the right configuration

### 4. Error Handling

```python
try:
    result = subprocess.run(mount_cmd, check=True, timeout=300)
    logger.info(f"Successfully mounted {target_name} at /triliodata")
except subprocess.CalledProcessError as e:
    logger.error(f"Failed to mount: {e.stderr}")
    raise RuntimeError(...)
except subprocess.TimeoutExpired:
    logger.error(f"Mount timed out")
    raise RuntimeError(...)
```

## Benefits

### 1. **Code Reuse**
- ✅ No duplication
- ✅ Single source of truth
- ✅ Tested and proven code

### 2. **Maintenance**
- ✅ Bug fixes in one place
- ✅ Feature additions benefit both
- ✅ Consistent behavior

### 3. **Completeness**
- ✅ S3 mounting works out of the box
- ✅ All edge cases handled
- ✅ Proper credential management

### 4. **Simplicity**
- ✅ 20 lines instead of 100+
- ✅ Clear and easy to understand
- ✅ Less room for bugs

## Mount Path

The script always mounts to `/triliodata`:

```python
# In mount_utility/constants.py
DEFAULT_DATASTORE_BASE_PATH = '/triliodata'

# In mount_datastores.py
ds_base_path, ... = init()  # Returns '/triliodata'
main(ds_base_path, ...)     # Mounts to '/triliodata'
```

This is perfect for our use case since:
- Discovery phase expects `/triliodata`
- TVK handler uses `TRILIODATA_MOUNT_PATH = '/triliodata'`
- Consistent with datastore-attacher behavior

## Testing

### Test NFS Mount
```bash
python3 mount_utility/mount_by_target_crd/mount_datastores.py \
  --target-name=nfs-target \
  --group=threatscanning.trilio.io

# Check mount
mount | grep /triliodata
ls /triliodata
```

### Test S3 Mount
```bash
python3 mount_utility/mount_by_target_crd/mount_datastores.py \
  --target-name=minio-target \
  --group=threatscanning.trilio.io

# Check mount (s3fuse)
mount | grep /triliodata
ls /triliodata
```

### Test from Poller
```bash
./poller/QUICK_TEST.sh minio-target 24
```

**Expected**:
```
INFO - Starting discovery phase
INFO - Mounting target minio-target to /triliodata using mount_datastores.py
INFO - Successfully mounted minio-target at /triliodata
INFO - Scanning S3 bucket 'bucket-name' for new backups...
```

## Unmounting

The unmount logic remains simple:

```python
def _unmount_triliodata(self):
    """Unmount /triliodata."""
    subprocess.run(['umount', TRILIODATA_MOUNT_PATH], check=True)
```

This works for both NFS and S3 (s3fuse).

## Flow Diagram

```
Poller Discovery Phase
        ↓
mount_target_for_discovery()
        ↓
subprocess.run([
    'python3',
    'mount_datastores.py',
    '--target-name=X',
    '--group=threatscanning.trilio.io'
])
        ↓
mount_datastores.py:
  1. Fetch Target CR
  2. Parse credentials
  3. Determine type (NFS/S3)
  4. Call utilities.mount_datastore()
     ├─ NFS: mount -t nfs ...
     └─ S3: s3fuse ...
        ↓
    Mounted at /triliodata
        ↓
Discovery continues...
        ↓
_unmount_triliodata()
```

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **NFS Mounting** | Custom implementation | Reused script |
| **S3 Mounting** | Not implemented | Reused script |
| **Lines of Code** | ~100 lines | ~20 lines |
| **Maintenance** | Two places | One place |
| **Testing** | Separate tests needed | Already tested |
| **Reliability** | Untested | Production-proven |

🎯 **Result**: Clean, reliable, maintainable mounting using existing infrastructure!

