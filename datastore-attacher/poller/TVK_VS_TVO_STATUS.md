# TVK vs TVO Implementation Status

## Quick Reference

| Feature | TVK | TVO |
|---------|-----|-----|
| **Cleanup Phase** | ✅ Fully Implemented | ⚠️ Placeholder (uses TVK-like structure) |
| **Discovery Phase** | ✅ Fully Implemented | ❌ Not Implemented |
| **Backup Type Detection** | ✅ Detects `tvk-meta.json` | ❌ Returns 'UNKNOWN' |
| **Directory Parsing** | ✅ `backupplan-uid/backup-uid/` | ⚠️ Assumes similar structure |
| **New Backup Detection** | ✅ S3 API + NFS find | ❌ Returns empty list |
| **Latest Backup Retrieval** | ✅ Reads backup.json | ❌ Returns None |

## TVK Implementation (Complete)

### Cleanup Phase ✅
- **Detection**: Looks for `tvk-meta.json` in `backupplan-uid/backup-uid/` structure
- **Parsing**: Extracts backupplan UIDs and backup UIDs from directory structure
- **Stale Detection**: Compares ScanInstance CRs against actual backups in target
- **Aggressive Cleanup**: Deletes all ScanInstances when BackupPlan is deleted

### Discovery Phase ✅
- **Time-based Filtering**: Uses CronJob `lastSuccessfulTime` (default: 6 hours ago)
- **S3 Detection**: Uses boto3 API to check `LastModified` timestamps
- **NFS Detection**: Uses `find` command with `-newermt` flag
- **Latest Backup**: Reads `backup.json` or `cluster-backup.json`, parses `creationTimestamp`
- **Mount Point**: Uses `/triliodata` for all operations

### TVK Directory Structure
```
/triliodata/
├── backupplan-uid-1/
│   ├── backup-uid-1/
│   │   ├── tvk-meta.json          ← Detection indicator
│   │   ├── backup.json            ← Metadata (namespace-scoped)
│   │   ├── backupplan.json
│   │   ├── metadata.qcow2
│   │   └── ...
│   └── backup-uid-2/
│       ├── tvk-meta.json
│       ├── cluster-backup.json    ← Metadata (cluster-scoped)
│       └── ...
└── backupplan-uid-2/
    └── ...
```

### TVK Metadata Format
```json
// backup.json or cluster-backup.json
{
  "metadata": {
    "name": "backup-name",
    "uid": "backup-uid",
    "creationTimestamp": "2024-01-01T00:00:00Z"  ← Used for sorting
  },
  "spec": { ... },
  "status": { ... }
}
```

## TVO Implementation (Not Complete)

### Cleanup Phase ⚠️
- **Detection**: Always returns 'UNKNOWN' (not implemented)
- **Parsing**: Uses TVK-like logic as placeholder (may not be correct)
- **Note**: May work if TVO structure is similar to TVK, but not verified

### Discovery Phase ❌
- **`get_backupplans_with_new_backups()`**: Returns empty list with warning
- **`get_latest_backup_for_backupplan()`**: Returns None with warning
- **Result**: No new backups will be discovered for TVO targets

### TVO Directory Structure (Unknown)
```
/triliodata/
├── workload-id-1/          ← Placeholder structure
│   ├── snapshot-id-1/
│   │   ├── snapshot.json?       ← Unknown
│   │   ├── vm-metadata.json?    ← Unknown
│   │   └── ...
│   └── snapshot-id-2/
│       └── ...
└── workload-id-2/
    └── ...
```

### What Needs to be Determined for TVO

1. **Directory Structure**:
   - Is it `workload-id/snapshot-id/` or something else?
   - What is the equivalent of TVK's backupplan and backup?

2. **Detection Indicators**:
   - What file(s) uniquely identify a TVO backup?
   - Equivalent of `tvk-meta.json`?

3. **Metadata Files**:
   - What files contain snapshot metadata?
   - `snapshot.json`? `vm-metadata.json`? Other?

4. **Timestamp Fields**:
   - Where is the creation timestamp stored?
   - What is the field name and format?

5. **Backup Organization**:
   - How are incremental/full backups organized?
   - How to identify the "latest" backup?

## Behavior When TVO Target is Used

### Current Behavior
1. **Backup Type Detection**: Returns 'UNKNOWN', defaults to TVK handler
2. **Cleanup Phase**: May work if structure is similar, but not guaranteed
3. **Discovery Phase**: Will log warnings and return no new backups
4. **Result**: TVO targets will not have new backups discovered

### Recommended Approach
- Do not use poller with TVO targets until TVO implementation is complete
- Or: Implement TVO-specific logic based on actual TVO backup structure
- Or: If TVO structure is identical to TVK, update detection to recognize TVO

## Implementation Checklist for TVO

When implementing TVO support, follow these steps:

- [ ] Determine TVO directory structure from actual TVO backups
- [ ] Identify TVO-specific detection indicators (files/patterns)
- [ ] Implement `detect_backup_type()` in `tvo_handler.py`
- [ ] Verify/update `parse_directory_structure()` for TVO
- [ ] Implement `get_backupplans_with_new_backups()` for TVO
- [ ] Implement `get_latest_backup_for_backupplan()` for TVO
- [ ] Test cleanup phase with actual TVO backups
- [ ] Test discovery phase with actual TVO backups
- [ ] Update documentation with TVO-specific details

## Code Locations

### TVK Implementation
- **Handler**: `cleanup/tvk_handler.py`
- **Detection**: `detect_backup_type()` - looks for `tvk-meta.json`
- **Cleanup**: `parse_directory_structure()` - parses TVK structure
- **Discovery**: `get_backupplans_with_new_backups()`, `get_latest_backup_for_backupplan()`

### TVO Placeholder
- **Handler**: `cleanup/tvo_handler.py`
- **Detection**: `detect_backup_type()` - returns 'UNKNOWN'
- **Cleanup**: `parse_directory_structure()` - uses TVK-like logic (placeholder)
- **Discovery**: Both methods return empty/None with warnings

### Base Handler
- **File**: `cleanup/base_handler.py`
- **Abstract Methods**: Define interface for both TVK and TVO
- **Common Logic**: Mounting, S3 client, CronJob status, etc.

## Summary

✅ **TVK is production-ready** for both cleanup and discovery phases  
❌ **TVO is NOT ready** - discovery will not work, cleanup may or may not work  
⚠️ **Action Required**: Implement TVO-specific logic when TVO structure is known

