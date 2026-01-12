# Using utilities.run_cmd for Command Execution

## Change Summary

Replaced direct `subprocess.run()` calls with `utilities.run_cmd()` for consistency with datastore-attacher patterns.

## Benefits of utilities.run_cmd

### 1. **Consistent Logging**
```python
# utilities.run_cmd automatically logs:
- Command being executed
- Execution start time
- Execution completion time
- Exit code
- Any errors
```

### 2. **Built-in Timeout Handling**
```python
# Default timeout from constants.DEFAULT_WAIT_TIMEOUT
# No need to specify timeout parameter
utilities.run_cmd(command)
```

### 3. **Automatic Error Handling**
```python
# Automatically checks return code
# Raises exception with proper logging if command fails
# No need for try/except boilerplate
```

### 4. **Standard Pattern**
```python
# Follows the same pattern as rest of datastore-attacher
# Makes code more maintainable
# Familiar to other developers
```

## Changes Made

### 1. Mount Target (Discovery Phase)

**Before**:
```python
mount_cmd = ['python3', mount_script, '--target-name=X', '--group=Y']

result = subprocess.run(
    mount_cmd,
    check=True,
    capture_output=True,
    text=True,
    timeout=300
)
```

**After**:
```python
mount_cmd = f"python3 {mount_script} --target-name=X --group=Y"

utilities.run_cmd(mount_cmd)
```

### 2. Unmount Target (Discovery Phase)

**Before**:
```python
subprocess.run(
    ['umount', TRILIODATA_MOUNT_PATH],
    check=True,
    capture_output=True,
    text=True,
    timeout=30
)
```

**After**:
```python
utilities.run_cmd(f"umount {TRILIODATA_MOUNT_PATH}")
```

### 3. Mount NFS (Cleanup Phase)

**Before**:
```python
mount_cmd = ['mount', '-t', 'nfs']
if mount_options:
    mount_cmd.extend(['-o', mount_options])
mount_cmd.extend([nfs_export, mount_path])

subprocess.run(
    mount_cmd,
    check=True,
    capture_output=True,
    text=True,
    timeout=60
)
```

**After**:
```python
mount_cmd = f"mount -t nfs"
if mount_options:
    mount_cmd += f" -o {mount_options}"
mount_cmd += f" {nfs_export} {mount_path}"

utilities.run_cmd(mount_cmd)
```

### 4. Unmount NFS (Cleanup Phase)

**Before**:
```python
subprocess.run(
    ['umount', mount_path],
    check=True,
    capture_output=True,
    text=True,
    timeout=30
)
```

**After**:
```python
utilities.run_cmd(f"umount {mount_path}")
```

## Exception: Find Command

The `find` command in `_list_nfs_structure()` still uses `subprocess.run()` because:

1. **Need to capture output**: `utilities.run_cmd()` outputs directly to stdout/stderr
2. **Need to parse output**: We need the list of directories returned by `find`
3. **Local import**: We import `subprocess` locally only where needed

```python
def _list_nfs_structure(self, mount_path: str) -> Dict:
    # Import subprocess locally since we need to capture output
    import subprocess
    
    result = subprocess.run(
        ['find', mount_path, '-mindepth', '2', '-maxdepth', '2', '-type', 'd'],
        capture_output=True,
        text=True,
        check=True,
        timeout=300
    )
    
    paths = [p for p in result.stdout.strip().split('\n') if p]
    return {'type': 'nfs', 'paths': paths, 'mount_path': mount_path}
```

## Code Comparison

### Command String Format

**utilities.run_cmd** expects a command string:
```python
utilities.run_cmd("mount -t nfs -o rw /export /mnt")
```

**subprocess.run** expects a list:
```python
subprocess.run(['mount', '-t', 'nfs', '-o', 'rw', '/export', '/mnt'])
```

### Error Handling

**utilities.run_cmd**:
```python
try:
    utilities.run_cmd(command)
except Exception as e:
    # Generic exception, already logged
    raise RuntimeError(f"Command failed: {str(e)}")
```

**subprocess.run**:
```python
try:
    subprocess.run(command, check=True)
except subprocess.CalledProcessError as e:
    # Specific exception type
    raise RuntimeError(f"Command failed: {e.stderr}")
except subprocess.TimeoutExpired:
    raise RuntimeError("Command timed out")
```

## Logging Output

### Before (subprocess.run)
```
# No automatic logging, must add manually
INFO - Mounting target minio-target to /triliodata
INFO - Successfully mounted minio-target at /triliodata
```

### After (utilities.run_cmd)
```
# Automatic detailed logging from utilities.run_cmd
INFO - Mounting target minio-target to /triliodata

INFO - Executing command python3 /path/to/mount_datastores.py --target-name=minio-target --group=threatscanning.trilio.io
INFO - python3 /path/to/mount_datastores.py --target-name=minio-target --group=threatscanning.trilio.io command execution starting time: 2025-12-30 09:30:00
INFO - waiting for command to complete...
INFO - python3 /path/to/mount_datastores.py --target-name=minio-target --group=threatscanning.trilio.io command execution completion time: 2025-12-30 09:30:05
INFO - Command:python3 /path/to/mount_datastores.py --target-name=minio-target --group=threatscanning.trilio.io, ExitCode:0

INFO - Successfully mounted minio-target at /triliodata
```

## Summary

| Aspect | subprocess.run | utilities.run_cmd |
|--------|---------------|-------------------|
| **Format** | List of args | String command |
| **Logging** | Manual | Automatic |
| **Timeout** | Must specify | Built-in default |
| **Error Handling** | Manual try/except | Automatic |
| **Exit Code Check** | Must use `check=True` | Automatic |
| **Consistency** | Not standard | Standard pattern |
| **Output Capture** | Easy with `capture_output=True` | Outputs to stdout/stderr |

## When to Use Each

### Use utilities.run_cmd
- ✅ Mount/unmount operations
- ✅ Commands where you don't need output
- ✅ Following datastore-attacher patterns
- ✅ Want automatic logging and error handling

### Use subprocess.run
- ✅ Need to capture and parse output
- ✅ Need specific exception types
- ✅ Need fine-grained control
- ✅ Commands like `find`, `ls`, etc.

## Files Modified

- **`cleanup/base_handler.py`**:
  - Removed top-level `subprocess` import
  - Updated `mount_target_for_discovery()` to use `utilities.run_cmd`
  - Updated `_unmount_triliodata()` to use `utilities.run_cmd`
  - Updated `_mount_nfs()` to use `utilities.run_cmd`
  - Updated `_unmount_nfs()` to use `utilities.run_cmd`
  - Kept `_list_nfs_structure()` using `subprocess.run` (local import)

🎯 **Result**: Consistent command execution pattern aligned with datastore-attacher standards!

