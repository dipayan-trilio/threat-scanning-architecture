# Backup Type Detection Update

## Changes Made

### 1. TVK Handler (`tvk_handler.py`)

**Updated `detect_backup_type()` method** to properly detect TVK backups by checking for `tvk-meta.json` in the correct directory structure.

#### Detection Logic:
- **Expected Structure**: `backupplan-uid/backup-uid/tvk-meta.json`
- **Validation**: Ensures the path has at least 3 components and ends with `tvk-meta.json`
- **Works for both S3 and NFS**: Handles both object keys and file paths

#### Example:
```python
# Valid TVK structures:
'backupplan-abc/backup-123/tvk-meta.json'  # S3
'/mnt/target/backupplan-abc/backup-123/tvk-meta.json'  # NFS

# Invalid structures (rejected):
'tvk-meta.json'  # At root
'backupplan-abc/tvk-meta.json'  # Only 2 levels
```

### 2. TVO Handler (`tvo_handler.py`)

**Updated `detect_backup_type()` method** to always return `'UNKNOWN'`.

#### Rationale:
- TVO detection logic is not yet implemented
- Returning `'UNKNOWN'` prevents false positives
- Allows safe fallback to TVK handler (via factory default)

### 3. Base Handler (`base_handler.py`)

**Updated `_extract_sample_structure()` method** to sample one backup directory for type detection.

#### Sampling Strategy:

**For S3:**
1. Takes the first backup directory from the list
2. Makes a single `list_objects_v2` call with `MaxKeys=100`
3. Returns sample objects from that backup directory
4. Detection checks these objects for `tvk-meta.json`

**For NFS:**
1. Takes the first backup directory from the list
2. Uses `glob` to list files in that directory
3. Returns sample paths from that backup directory
4. Detection checks these paths for `tvk-meta.json`

#### Performance:
- **S3**: +1 additional API call for sampling (only during detection)
- **NFS**: +1 glob operation (only during detection)
- Detection only runs if backup type is not set via annotation

## Testing

### Unit Tests (`test_detection.py`)

All tests passing ✅:

```
======================================================================
                    TVK DETECTION TESTS
======================================================================

Testing TVK detection with S3 structure...
  ✓ TVK detection test passed (S3)

Testing TVK detection with NFS structure...
  ✓ TVK detection test passed (NFS)

Testing non-TVK structure...
  ✓ Non-TVK structure correctly not detected

Testing malformed paths...
  ✓ Malformed paths correctly rejected

======================================================================
                    ALL TESTS PASSED!
======================================================================
```

### Test Coverage:
1. ✅ TVK detection with S3 structure
2. ✅ TVK detection with NFS structure
3. ✅ Non-TVK structure (no false positives)
4. ✅ Malformed paths (proper validation)

## Usage

### With Annotation (Recommended)
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: my-backup-target
  annotations:
    trilio.io/backup-type: "TVK"  # Skip auto-detection
spec:
  # ... target configuration
```

### Without Annotation (Auto-detection)
If no annotation is present:
1. Poller samples one backup directory
2. Checks for `tvk-meta.json` in proper structure
3. Returns `'TVK'` if found, `'UNKNOWN'` otherwise
4. Factory defaults to TVK handler if unknown

## Performance Impact

### Before:
- No sampling needed
- Relied on annotation or default

### After:
- **With annotation**: No change (no sampling)
- **Without annotation**: +1 S3 API call or +1 glob operation
- Sampling only happens once per cleanup run
- Minimal performance impact

## Benefits

1. **Accurate Detection**: Properly identifies TVK backups by structure
2. **No False Positives**: Validates path structure before detection
3. **Safe Fallback**: TVO returns UNKNOWN to avoid misidentification
4. **Efficient**: Only samples one backup directory
5. **Flexible**: Works with both S3 and NFS targets

## Future Enhancements

### TVO Detection
When TVO structure is known, implement:
```python
def detect_backup_type(self, sample_structure: Dict) -> str:
    # Check for TVO-specific files
    for obj_key in sample_structure.get('objects', []):
        if obj_key.endswith('tvo-meta.json'):  # Or TVO-specific file
            parts = obj_key.strip('/').split('/')
            if len(parts) >= 3:  # Validate structure
                return 'TVO'
    return 'UNKNOWN'
```

### Caching
Cache detection result to avoid repeated sampling:
```python
# In base_handler.__init__()
self._detected_type_cache = None

# In perform_cleanup()
if not self.backup_type:
    if self._detected_type_cache:
        self.backup_type = self._detected_type_cache
    else:
        sample = self._extract_sample_structure(target_data)
        self.backup_type = self.detect_backup_type(sample)
        self._detected_type_cache = self.backup_type
```

## Files Modified

1. `cleanup/tvk_handler.py` - Updated detection logic
2. `cleanup/tvo_handler.py` - Return UNKNOWN
3. `cleanup/base_handler.py` - Added sampling logic
4. `test_detection.py` - New test file

## Backward Compatibility

✅ **Fully backward compatible**:
- Existing deployments with annotations work unchanged
- New auto-detection adds capability without breaking existing behavior
- Factory still defaults to TVK if detection fails

