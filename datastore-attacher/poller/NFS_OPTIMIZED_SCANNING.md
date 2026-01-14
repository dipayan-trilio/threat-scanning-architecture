# NFS Optimized Scanning

## Overview

This document describes the optimization applied to NFS scanning to make it consistent with the S3 scanning approach.

## Previous Implementation

The previous NFS scanning approach:

```bash
find /triliodata -mindepth 2 -maxdepth 2 -type d -newermt '2026-01-09 02:00:00'
```

**Problems:**
1. Scanned all directories at depth 2 (backup directories)
2. No verification of backup status
3. Could include incomplete or failed backups
4. Required additional processing to determine if backups were valid

## New Implementation

The new NFS scanning approach:

```bash
find /triliodata \
  -mindepth 3 -maxdepth 3 \
  -type f \
  '(' \
    -name 'backup.json' \
    -o -name 'cluster-backup.json' \
    -o -name 'snapshot.json' \
    -o -name 'cluster-snapshot.json' \
  ')' \
  -newermt '2026-01-09 02:00:00'
```

**Improvements:**
1. ✅ Searches for specific metadata files only
2. ✅ Reads and verifies backup status from metadata
3. ✅ Only discovers backups with "Available" status
4. ✅ Consistent with S3 scanning logic
5. ✅ Dramatically fewer file operations

## Algorithm

1. **Find metadata files**: Use `find` with specific file name filters
2. **Check timestamp**: Only process files modified since `since_time`
3. **Extract UIDs**: Parse backupplan and backup UIDs from file path
4. **Read metadata**: Open and parse the JSON file
5. **Verify status**: Check if `status.status == "Available"`
6. **Add to set**: Only add backupplan UID if backup is available

## Code Example

```python
# Find backup metadata files modified since the given time
result = subprocess.run(
    [
        'find', TRILIODATA_MOUNT_PATH,
        '-mindepth', '3', '-maxdepth', '3',
        '-type', 'f',
        '(',
        '-name', 'backup.json',
        '-o', '-name', 'cluster-backup.json',
        '-o', '-name', 'snapshot.json',
        '-o', '-name', 'cluster-snapshot.json',
        ')',
        '-newermt', time_str
    ],
    capture_output=True,
    text=True,
    check=True,
    timeout=300
)

# Parse and verify each metadata file
for metadata_file_path in metadata_files_found:
    # Extract UIDs from path
    parts = metadata_file_path.strip('/').split('/')
    backupplan_uid = parts[-3]
    backup_uid = parts[-2]
    
    # Read and verify status
    with open(metadata_file_path, 'r') as f:
        backup_metadata = json.load(f)
    
    status = backup_metadata.get('status', {})
    backup_status = status.get('status', '').lower()
    
    if backup_status == 'available':
        backupplans_with_new_backups.add(backupplan_uid)
```

## Performance Comparison

### Scenario: NFS mount with 1,000 backupplans, 40 new backups

#### Before
- **Find command**: Scans all directories at depth 2
- **Directories found**: ~1,000 (all backupplan/backup combinations)
- **File operations**: 1,000 stat operations
- **Processing**: Adds all 1,000 to discovery list
- **Backups discovered**: 40 (including incomplete)

#### After
- **Find command**: Scans only specific metadata files at depth 3
- **Files found**: 42 metadata files
- **File operations**: 42 read operations
- **Processing**: Reads and verifies status for 42 files
- **Backups discovered**: 38 (only available)

**Performance gain:** ~96% reduction in file operations (42 vs 1,000)

## Benefits

1. **Efficiency**: Dramatically fewer file operations
2. **Accuracy**: Only discovers complete, available backups
3. **Consistency**: Same logic for both S3 and NFS
4. **Better logging**: Shows metadata files found and available backups
5. **Supports snapshots**: Handles both backups and snapshots

## Example Output

```
Scanning NFS mount '/triliodata' for new backup metadata files...
NFS scan complete: found 42 metadata files modified since 2026-01-09 02:00:00
Found available backup: abc123 in backupplan def456 (type: backup)
Found available backup: xyz789 in backupplan ghi012 (type: cluster-backup)
Skipping backup jkl345 with status 'inprogress' (not Available)
Found 38 available backups in 12 backupplans
```

## Metadata Files Supported

The implementation searches for these metadata file types:

1. **backup.json** - Namespace-scoped backups
2. **cluster-backup.json** - Cluster-scoped backups
3. **snapshot.json** - Namespace-scoped snapshots
4. **cluster-snapshot.json** - Cluster-scoped snapshots

All files are expected at depth 3 in the structure:
```
/triliodata/
  └── <backupplan-uid>/
      └── <backup-uid>/
          ├── backup.json (or cluster-backup.json, snapshot.json, cluster-snapshot.json)
          ├── backupplan.json
          └── ... other files
```

## Error Handling

The implementation includes robust error handling:

1. **Malformed paths**: Skips paths that don't match expected structure
2. **Read errors**: Logs warning and continues with next file
3. **Parse errors**: Logs warning if JSON is malformed
4. **Missing status**: Treats as not available
5. **Timeout**: Raises error if find command takes > 300 seconds

## Testing

To test the optimized NFS scanning:

```bash
# Create test backups with different statuses
mkdir -p /triliodata/test-bp-1/test-backup-1
echo '{"status": {"status": "Available"}}' > /triliodata/test-bp-1/test-backup-1/backup.json

mkdir -p /triliodata/test-bp-1/test-backup-2
echo '{"status": {"status": "InProgress"}}' > /triliodata/test-bp-1/test-backup-2/backup.json

# Run the poller with debug logging
export LOG_LEVEL=DEBUG
python3 datastore-attacher/poller/main.py

# Expected: Only test-backup-1 should be discovered
```

## Backward Compatibility

This implementation is fully backward compatible:
- Works with existing NFS mounts
- Handles all metadata file types
- Falls back gracefully if files are missing or malformed
- No changes to mount logic or cleanup phase




