# Subprocess-based Mount Implementation

## Overview

This document describes the change from using `utilities.run_cmd()` to `subprocess.run()` for mounting targets in the poller.

## Problem

The `utilities.run_cmd()` function was causing issues when trying to execute the `mount_datastores.py` script. The error messages indicated that the shell was trying to execute the Python file as a bash script:

```
/path/to/mount_datastores.py: line 1: import: command not found
```

## Root Cause

The `utilities.run_cmd()` function uses `shlex.split()` and `subprocess.Popen()` with specific settings that were not working correctly for our use case. The exact issue was unclear, but the Python script was being executed as a shell script instead of being run with the Python interpreter.

## Solution

Replaced `utilities.run_cmd()` with direct `subprocess.run()` calls for all mount operations.

### Benefits of `subprocess.run()`

1. **Direct Control**: We pass the command as a list of arguments, avoiding any shell interpretation
2. **Better Error Handling**: `subprocess.run()` with `check=True` raises `CalledProcessError` with detailed error information
3. **Output Capture**: `capture_output=True` captures both stdout and stderr for debugging
4. **Timeout Support**: Built-in timeout parameter prevents hanging
5. **Cleaner Code**: More straightforward and Pythonic

## Implementation Details

### Command Structure

Commands are passed as a list of strings (not a single string):

```python
mount_cmd = [
    'python3',
    mount_script,  # Absolute path to mount_datastores.py
    f'--target-name={self.target_name}',
    '--group=threatscanning.trilio.io'
]
```

### Execution

```python
result = subprocess.run(
    mount_cmd,
    check=True,           # Raise exception on non-zero exit
    capture_output=True,  # Capture stdout and stderr
    text=True,            # Return strings instead of bytes
    timeout=300           # 5 minute timeout
)
```

### Error Handling

Three types of exceptions are handled:

1. **CalledProcessError**: Command returned non-zero exit code
   - Logs exit code, stdout, and stderr
   - Raises RuntimeError with stderr message

2. **TimeoutExpired**: Command took longer than 300 seconds
   - Raises RuntimeError with timeout message

3. **Generic Exception**: Any other error
   - Raises RuntimeError with error message

### Example Error Output

```python
except subprocess.CalledProcessError as e:
    self.logger.error(f"Mount failed with exit code {e.returncode}")
    self.logger.error(f"Stdout: {e.stdout}")
    self.logger.error(f"Stderr: {e.stderr}")
    raise RuntimeError(f"Failed to mount NFS target {self.target_name}: {e.stderr}")
```

## Changes Made

### 1. Added Import

```python
import subprocess
```

### 2. Updated NFS Mount (in `get_target_data()`)

**Before:**
```python
mount_cmd = (
    f"python3 {mount_script} "
    f"--target-name={self.target_name} --group=threatscanning.trilio.io"
)
utilities.run_cmd(mount_cmd)
```

**After:**
```python
mount_cmd = [
    'python3',
    mount_script,
    f'--target-name={self.target_name}',
    '--group=threatscanning.trilio.io'
]

result = subprocess.run(
    mount_cmd,
    check=True,
    capture_output=True,
    text=True,
    timeout=300
)
if result.stdout:
    self.logger.info(f"Mount stdout: {result.stdout}")
```

### 3. Updated S3 Mount (in `mount_target_for_discovery()`)

Same pattern as NFS mount above.

## Testing

To test the mount functionality:

```bash
# Set environment variables
export TARGET_NAME=your-target-name
export TARGET_NAMESPACE=trilio-system
export KUBECONFIG=/path/to/kubeconfig

# Run the poller
python3 datastore-attacher/poller/main.py
```

The logs should show:
```
Mount command: python3 /absolute/path/to/mount_datastores.py --target-name=your-target --group=threatscanning.trilio.io
Successfully mounted NFS your-target at /triliodata
```

## Comparison: utilities.run_cmd vs subprocess.run

| Feature | utilities.run_cmd | subprocess.run |
|---------|------------------|----------------|
| Command format | String (split with shlex) | List of strings |
| Error handling | Generic exception | Specific exceptions |
| Output capture | To stdout/stderr directly | Captured in result object |
| Timeout | Custom implementation | Built-in parameter |
| Exit code check | Manual check | Automatic with check=True |
| Logging | Built-in verbose logging | Manual logging |

## Future Considerations

If we need to revert to `utilities.run_cmd()`, we should investigate:

1. Whether the issue is with how the command string is constructed
2. Whether `utilities.run_cmd()` needs to be fixed for Python script execution
3. Whether we should use `shell=True` parameter (not recommended for security reasons)

For now, `subprocess.run()` provides a clean, reliable solution.

