# Optimized S3 Scanning Implementation

## Overview

This document describes the optimized S3 scanning implementation that uses regex filtering and backup status verification to efficiently discover new backups.

## Problem with Previous Implementation

The previous implementation had several inefficiencies:

1. **Checked every object**: Scanned all objects in the S3 bucket, including data files, segments, and non-metadata files
2. **No status verification**: Added backupplans to the discovery list even if backups were incomplete or failed
3. **Inefficient filtering**: Only filtered by timestamp, not by file type
4. **High S3 API costs**: Made unnecessary API calls for irrelevant objects

## New Implementation

### Key Improvements

1. **Targeted file search**: Only processes backup/snapshot metadata files (both S3 and NFS)
2. **Status verification**: Reads metadata to verify backup is in "Available" state
3. **Reduced processing**: Dramatically fewer files to process by filtering early
4. **Better accuracy**: Only discovers backups that are complete and ready for scanning
5. **Consistent approach**: Both S3 and NFS now use similar filtering and verification logic

### S3: Regex Pattern

```python
backup_metadata_pattern = re.compile(
    r'^(.*?)/(backup|snapshot|cluster-backup|cluster-snapshot)\.json\.manifest\.([0-9a-f]{8})$'
)
```

This pattern matches:
- `backup.json.manifest.<hex>` - Namespace-scoped backups
- `cluster-backup.json.manifest.<hex>` - Cluster-scoped backups
- `snapshot.json.manifest.<hex>` - Namespace-scoped snapshots
- `cluster-snapshot.json.manifest.<hex>` - Cluster-scoped snapshots

Where `<hex>` is an 8-character hexadecimal number (s3fuse manifest format).

### NFS: Find Command with Name Filters

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

This command finds:
- `backup.json` - Namespace-scoped backups
- `cluster-backup.json` - Cluster-scoped backups
- `snapshot.json` - Namespace-scoped snapshots
- `cluster-snapshot.json` - Cluster-scoped snapshots

At depth 3 (format: `/triliodata/backupplan-uid/backup-uid/metadata.json`) modified since the given time.

### Algorithm Flow

#### For S3 Targets

1. **List all objects** in the bucket using paginator
2. **Filter by regex**: Check if object key matches backup metadata pattern
3. **Check timestamp**: Skip if `LastModified` <= `since_time`
4. **Extract UIDs**: Parse backupplan and backup UIDs from the object key path
5. **Read metadata**: Fetch and parse the JSON file from S3
6. **Verify status**: Check if `status.status == "Available"`
7. **Add to set**: Only add backupplan UID if backup is available

#### For NFS Targets

NFS scanning has been optimized similarly:
- Uses `find` command to search for specific metadata files: `backup.json`, `cluster-backup.json`, `snapshot.json`, `cluster-snapshot.json`
- Filters by `-newermt` to find files modified since `since_time`
- Reads each metadata file to verify backup status
- Only adds backupplans with available backups
- Extracts backupplan and backup UIDs from file paths

### Code Changes

#### 1. Added Import

```python
import re
```

#### 2. Updated `get_backupplans_with_new_backups()`

**Key changes:**
- Compiles regex pattern for metadata file matching
- Tracks three metrics: `total_objects_checked`, `metadata_files_found`, `available_backups_found`
- Only processes objects matching the metadata pattern
- Reads each metadata file to check backup status
- Only adds backupplans with available backups

**Example log output:**
```
S3 scan complete: checked 15234 objects, found 42 metadata files, 38 available backups
Found 12 backupplans with new available backups (since 2026-01-09 02:00:00)
```

#### 3. Updated `get_latest_backup_for_backupplan()`

**Key changes:**
- Handles both NFS format (`backup.json`) and S3 s3fuse format (`backup.json.manifest.<hex>`)
- Supports all metadata file types: `backup`, `cluster-backup`, `snapshot`, `cluster-snapshot`
- Tries exact match first (NFS), then manifest format (S3)
- More robust error handling

**Metadata file patterns checked:**
1. `backup.json` (exact match)
2. `backup.json.manifest.<hex>` (s3fuse format)
3. `cluster-backup.json` (exact match)
4. `cluster-backup.json.manifest.<hex>` (s3fuse format)
5. `snapshot.json` (exact match)
6. `snapshot.json.manifest.<hex>` (s3fuse format)
7. `cluster-snapshot.json` (exact match)
8. `cluster-snapshot.json.manifest.<hex>` (s3fuse format)

## Performance Impact

### S3 Targets

#### Before
For a bucket with 15,000 objects and 40 backups:
- **Objects checked**: 15,000
- **S3 API calls**: ~15,000 (list) + 0 (get) = 15,000
- **Backups discovered**: 40 (including incomplete/failed)

#### After
For the same bucket:
- **Objects checked**: 15,000 (list only)
- **Metadata files found**: 42
- **S3 API calls**: ~15,000 (list) + 42 (get) = 15,042
- **Available backups discovered**: 38 (only complete/available)

**Key improvements:**
- ✅ Filters out incomplete/failed backups
- ✅ More accurate discovery (only available backups)
- ✅ Better logging with detailed metrics
- ✅ Supports snapshots in addition to backups

**Note:** While the number of list API calls remains the same (we still need to scan all objects to find metadata files), we now:
1. Only process relevant files (metadata files)
2. Verify backup status before adding to discovery
3. Get more accurate results

### NFS Targets

#### Before
For an NFS mount with 10,000 directories and 40 backups:
- **Directories scanned**: 10,000 (all directories at depth 2)
- **File operations**: 10,000 (stat operations)
- **Backups discovered**: 40 (including incomplete/failed)

#### After
For the same NFS mount:
- **Files scanned**: Only metadata files (backup.json, etc.)
- **Metadata files found**: 42
- **File operations**: 42 (read operations)
- **Available backups discovered**: 38 (only complete/available)

**Key improvements:**
- ✅ Dramatically fewer file operations (42 vs 10,000)
- ✅ Only reads relevant metadata files
- ✅ Filters out incomplete/failed backups
- ✅ Consistent behavior with S3 scanning

## Status Verification

The implementation checks the backup status by reading the metadata file:

```python
backup_metadata = json.loads(response['Body'].read().decode('utf-8'))
status = backup_metadata.get('status', {})
backup_status = status.get('status', '').lower()

if backup_status == 'available':
    # Add to discovery
```

**Valid status values:**
- `Available` - Backup is complete and ready for scanning ✅
- `InProgress` - Backup is still running ❌
- `Failed` - Backup failed ❌
- `Deleting` - Backup is being deleted ❌

Only backups with `Available` status are added to the discovery list.

## Debugging

### Debug Logs

When `LOG_LEVEL=DEBUG`, you'll see:
- Each available backup found with its type
- Skipped backups with their status
- Malformed paths that are skipped
- Failed metadata file reads

Example:
```
Found available backup: abc123 in backupplan def456 (type: backup)
Skipping backup xyz789 with status 'inprogress' (not Available)
```

### Testing

To test the optimized scanning:

```bash
# Set debug logging
export LOG_LEVEL=DEBUG

# Run the poller
python3 datastore-attacher/poller/main.py
```

Look for these log lines:
- `Scanning S3 bucket '<bucket>' for new backup metadata files...`
- `S3 scan complete: checked X objects, found Y metadata files, Z available backups`
- `Found N backupplans with new available backups`

## Future Optimizations

Potential further optimizations:

1. **Prefix-based filtering**: If backupplan UIDs follow a pattern, use S3 prefix to reduce objects scanned
2. **Parallel processing**: Process multiple metadata files concurrently
3. **Caching**: Cache backup status to avoid re-reading unchanged files
4. **Index file**: Maintain an index of available backups to avoid full scans

## Backward Compatibility

This implementation is fully backward compatible:
- Works with both NFS and S3 targets
- Handles both old and new backup formats
- Supports all metadata file types (backup, cluster-backup, snapshot, cluster-snapshot)
- Falls back gracefully if metadata files are missing or malformed

