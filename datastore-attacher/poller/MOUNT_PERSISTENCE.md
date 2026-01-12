# Mount Persistence Strategy

## Overview

This document describes the mount persistence strategy used by the poller, where mounts are created once and reused across both cleanup and discovery phases, with no unmount logic needed.

## Key Principles

1. **Single Mount per Target**: Each target is mounted at most once during the poller's lifecycle
2. **Mount Reuse**: NFS mounts created during cleanup are reused for discovery
3. **No Unmount**: Mounts persist until the pod terminates (no explicit unmount logic)
4. **Standard Mount Point**: All targets are mounted at `/triliodata`

## Flow by Target Type

### NFS Targets

```
Cleanup Phase:
  1. Mount NFS to /triliodata using mount_datastores.py
  2. List directory structure using find
  3. Perform cleanup operations
  4. Mount persists (no unmount)

Discovery Phase:
  1. Reuse existing mount at /triliodata
  2. Use find to detect new backups
  3. Process backupplans
  4. Mount persists (no unmount)

Pod Termination:
  - Kubernetes automatically cleans up mounts when pod terminates
```

### S3 Targets

```
Cleanup Phase:
  1. Use S3 API to list directory structure (no mount)
  2. Perform cleanup operations
  3. No mount created

Discovery Phase:
  1. Use S3 API to detect new backups
  2. If new backups found:
     - Mount S3 to /triliodata using mount_datastores.py (s3fuse)
     - Process backupplans
     - Mount persists (no unmount)
  3. If no new backups:
     - Skip mount entirely

Pod Termination:
  - Kubernetes automatically cleans up mounts when pod terminates
```

## Benefits

1. **Efficiency**: No redundant mount/unmount operations
2. **Simplicity**: Cleaner code without unmount error handling
3. **Reliability**: Kubernetes handles cleanup automatically
4. **Performance**: NFS mount is reused, avoiding remount overhead

## Implementation Details

### Mount Creation

All mounting is done via `mount_datastores.py` from datastore-attacher:

```python
mount_cmd = (
    f"python3 {path_to_mount_datastores.py} "
    f"--target-name={self.target_name} "
    f"--group=threatscanning.trilio.io"
)
utilities.run_cmd(mount_cmd)
```

### Mount Reuse (NFS)

For NFS targets, `mount_target_for_discovery()` detects that the target is NFS and returns the existing mount path:

```python
def mount_target_for_discovery(self) -> str:
    if self.target_type.lower() != constants.OBJECT_STORE:
        # NFS already mounted during cleanup phase
        self.logger.info(f"NFS target already mounted at {TRILIODATA_MOUNT_PATH}, reusing for discovery")
        return TRILIODATA_MOUNT_PATH
    
    # S3 target - mount now
    # ... mount logic ...
```

### No Unmount Logic

Both `perform_cleanup()` and `perform_discovery()` have been updated to remove all unmount logic:

```python
# Old code (removed):
finally:
    if mount_path:
        try:
            self._unmount_nfs(mount_path)  # or self._unmount_triliodata()
        except Exception as e:
            self.logger.warning(f"Failed to unmount: {str(e)}")

# New code:
# Note: No unmount logic needed
# For NFS: Mount persists from cleanup phase
# For S3: Mount persists until pod terminates
# This is intentional - no need to unmount
```

## Removed Methods

The following methods have been removed as they are no longer needed:

- `_unmount_nfs()` from `BaseBackupTargetHandler`
- `_unmount_triliodata()` from `BaseBackupTargetHandler`

Note: `detector.py` still has its own `_unmount_nfs()` method, which is fine since it's a separate class with different lifecycle requirements.

## Error Handling

Since there's no unmount logic, there's no need to handle unmount errors. Any mount errors are handled during the mount operation itself.

## Testing Considerations

When testing locally:

1. **NFS**: Mount will persist after cleanup phase and be reused for discovery
2. **S3**: Mount will only be created if new backups are found during discovery
3. **Cleanup**: Manually unmount `/triliodata` between test runs if needed:
   ```bash
   sudo umount /triliodata
   ```

## Future Considerations

If we ever need to unmount (e.g., for resource cleanup in long-running processes), we can:

1. Add an explicit cleanup method called at the end of `main.py`
2. Use a context manager pattern for mount lifecycle
3. Add a signal handler to unmount on graceful shutdown

For now, the pod-based lifecycle makes unmounting unnecessary.

