# Poller Cleanup & Log Improvements

## Changes Made (Dec 30, 2025)

### 1. **Suppressed Debug Logs**

Added suppression for verbose third-party library logs:

```python
# Suppress boto3/botocore/urllib3 debug logs
python_logging.getLogger('boto3').setLevel(python_logging.WARNING)
python_logging.getLogger('botocore').setLevel(python_logging.WARNING)
python_logging.getLogger('urllib3').setLevel(python_logging.WARNING)

# Suppress kubernetes client debug logs - only show INFO and above
python_logging.getLogger('kubernetes').setLevel(python_logging.INFO)
```

**Before**: Hundreds of DEBUG logs from boto3, botocore, urllib3, and kubernetes client  
**After**: Only WARNING and ERROR logs from these libraries

---

### 2. **Removed Empty Log Entries**

**Removed all instances of**:
```python
logging.info("")  # Empty log entries
```

**Impact**: Cleaner log output without unnecessary blank lines in JSON logs

---

### 3. **Converted Separator Lines to Print Statements**

**Changed**:
```python
logging.info("=" * 70)
logging.info(" " * 20 + "CLEANUP PHASE")
logging.info("=" * 70)
```

**To**:
```python
print("\n" + "=" * 70)
print(" " * 20 + "CLEANUP PHASE")
print("=" * 70)
```

**Reason**: Separator lines don't need to be in structured JSON logs. Using `print()` keeps them visible in console but out of log files.

---

### 4. **Fixed Backup Type Detection Logging**

**Before**:
```
INFO - Detecting backup type...
INFO - Detected backup type: UNKNOWN
WARNING - Could not detect backup type, defaulting to TVK
INFO - Backup type: TVK
```

**After**:
```
INFO - Detecting backup type from target structure...
INFO - Detected backup type: TVK
```

**Changes**:
- Removed redundant "Detecting backup type..." log from detector
- Removed "Detected backup type: UNKNOWN" log
- Only log once when detection succeeds

---

### 5. **Fixed NFS/S3 Confusion in Discovery**

**Problem**: For S3 targets, logs showed:
```
INFO - Scanning NFS mount '/triliodata' for new backups...
```

**Root Cause**: Incorrect comparison in `tvk_handler.py`:
```python
if self.target_type.lower() == 'ObjectStore':  # Wrong!
```

**Fix**:
```python
if self.target_type.lower() == 'objectstore':  # Correct!
```

**Now Shows**:
- For S3: `Scanning S3 bucket 'bucket-name' for new backups...`
- For NFS: `Scanning NFS mount '/triliodata' for new backups...`

---

### 6. **Ignore Data Segments Directory**

**Problem**: The directory `80bc80ff-0c51-4534-86a2-ec5e719643c2` is used to store data segments (not backup metadata), but was being counted as a backupplan.

**Fix in `base_handler.py` (cleanup listing)**:
```python
# Skip data segments directory (used for storing backup data, not metadata)
if backupplan_uid == '80bc80ff-0c51-4534-86a2-ec5e719643c2':
    continue

# Skip data segment subdirectories
if '-segments' not in backup_prefix['Prefix']:
    all_objects.append(backup_prefix['Prefix'])
```

**Fix in `tvk_handler.py` (discovery listing)**:
```python
# Skip data segments directory
if obj_key.startswith('80bc80ff-0c51-4534-86a2-ec5e719643c2/'):
    continue

# Skip segment directories
if '-segments' not in backupplan_uid:
    backupplans_with_new_backups.add(backupplan_uid)
```

**Impact**: 
- Accurate backupplan count
- No false positives from data storage directories

---

### 7. **Simplified Log Messages**

**Before**:
```
INFO - Step 1: Detecting backup type from target structure...
INFO - Step 2: Creating handler...
INFO - Step 3: Performing cleanup...
INFO - ✓ CLEANUP COMPLETED SUCCESSFULLY
INFO -   - Backup type: TVK
INFO -   - Backupplans processed: 43
```

**After**:
```
INFO - Detecting backup type from target structure...
INFO - Detected backup type: TVK
INFO - ✓ Cleanup completed successfully
INFO -   Backup type: TVK
INFO -   Backupplans processed: 43
```

**Changes**:
- Removed "Step 1/2/3" prefixes
- Removed redundant "Creating handler..." log
- Simplified success messages (lowercase, no ALL CAPS)
- Removed leading dashes from summary items

---

## Before & After Comparison

### Before (Verbose & Cluttered)
```json
{"level": "INFO", "msg": ""}
{"level": "INFO", "msg": "======================================================================"}
{"level": "INFO", "msg": "                    CLEANUP PHASE"}
{"level": "INFO", "msg": "======================================================================"}
{"level": "INFO", "msg": "Step 1: Detecting backup type from target structure..."}
{"level": "INFO", "msg": "Detecting backup type..."}
{"level": "DEBUG", "msg": "Event before-parameter-build.s3.ListObjectsV2: ..."}
{"level": "DEBUG", "msg": "Making request for OperationModel(name=ListObjectsV2) ..."}
{"level": "INFO", "msg": "Detected backup type: UNKNOWN"}
{"level": "WARNING", "msg": "Could not detect backup type, defaulting to TVK"}
{"level": "INFO", "msg": "Backup type: TVK"}
{"level": "INFO", "msg": ""}
{"level": "INFO", "msg": "Step 2: Creating handler..."}
{"level": "INFO", "msg": ""}
{"level": "INFO", "msg": "Step 3: Performing cleanup..."}
{"level": "INFO", "msg": "Scanning NFS mount '/triliodata' for new backups..."}
{"level": "INFO", "msg": "Listed 92 backup directories from S3 bucket shiwam-test"}
{"level": "INFO", "msg": ""}
{"level": "INFO", "msg": "----------------------------------------------------------------------"}
{"level": "INFO", "msg": "✓ CLEANUP COMPLETED SUCCESSFULLY"}
{"level": "INFO", "msg": "  - Backup type: TVK"}
{"level": "INFO", "msg": "  - Backupplans processed: 43"}
```

### After (Clean & Focused)
```
======================================================================
                    CLEANUP PHASE
======================================================================
{"level": "INFO", "msg": "Detecting backup type from target structure..."}
{"level": "INFO", "msg": "Detected backup type: TVK"}
{"level": "INFO", "msg": "Starting cleanup for target: minio-target"}
{"level": "INFO", "msg": "Listed 43 backup directories from S3 bucket shiwam-test"}
{"level": "INFO", "msg": "Found 43 backupplans with total 92 backups"}
{"level": "INFO", "msg": "Found 0 total ScanInstances for target"}
{"level": "INFO", "msg": "Cleanup completed: deleted 0 stale ScanInstances"}
----------------------------------------------------------------------
{"level": "INFO", "msg": "✓ Cleanup completed successfully"}
{"level": "INFO", "msg": "  Backup type: TVK"}
{"level": "INFO", "msg": "  Backupplans processed: 43"}
{"level": "INFO", "msg": "  Total backups found: 92"}
{"level": "INFO", "msg": "  Stale ScanInstances deleted: 0"}
----------------------------------------------------------------------
```

---

## Benefits

1. **✅ Cleaner Logs**: No more boto3/botocore/kubernetes debug spam
2. **✅ Accurate Counts**: Data segments directory no longer counted as backupplan
3. **✅ Correct Messages**: S3 targets show "Scanning S3 bucket", not "Scanning NFS mount"
4. **✅ No Redundancy**: Single detection log, no "UNKNOWN then TVK" confusion
5. **✅ Better Readability**: Simplified messages, no empty logs
6. **✅ Structured Logs**: Separators use `print()`, actual data uses `logging`

---

## Files Modified

1. `main.py` - Log suppression, removed empty logs, simplified messages
2. `cleanup/detector.py` - Removed redundant detection logs
3. `cleanup/base_handler.py` - Filter data segments directory in cleanup
4. `cleanup/tvk_handler.py` - Fixed S3/NFS detection, filter data segments in discovery

---

## Testing

Run the poller and verify:
```bash
./poller/QUICK_TEST.sh minio-target 24
```

**Expected Output**:
- ✅ No boto3/botocore/kubernetes DEBUG logs
- ✅ No empty log entries (`msg: ""`)
- ✅ Separator lines visible in console (not in JSON logs)
- ✅ S3 targets show "Scanning S3 bucket"
- ✅ NFS targets show "Scanning NFS mount"
- ✅ Single "Detected backup type: TVK" log
- ✅ Data segments directory not counted in backupplan count
- ✅ Clean, focused log output

---

## Rollback

If needed, revert with:
```bash
git checkout HEAD -- datastore-attacher/poller/main.py
git checkout HEAD -- datastore-attacher/poller/cleanup/detector.py
git checkout HEAD -- datastore-attacher/poller/cleanup/base_handler.py
git checkout HEAD -- datastore-attacher/poller/cleanup/tvk_handler.py
```

