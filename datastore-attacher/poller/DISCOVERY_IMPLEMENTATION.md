# Discovery Phase Implementation

## Overview

The discovery phase has been implemented **for TVK (TrilioVault for Kubernetes)** to detect new backups created since the last successful CronJob run and prepare them for scanning. This document describes the implementation details and design decisions.

**Note**: TVO (TrilioVault for OpenStack) discovery is NOT yet implemented. TVO-specific logic will be added later when the TVO directory structure and metadata format are known.

## Key Design Decisions

### 1. S3 API Usage for Detection
**Decision**: Use S3 API (boto3) for detecting new backups even after mounting, rather than relying on s3fuse filesystem operations.

**Rationale**: 
- S3 API calls are significantly faster than s3fuse filesystem operations
- Direct API access provides reliable `LastModified` timestamps
- Reduces dependency on s3fuse mount stability during detection phase

**Implementation**:
- For S3 targets: Use `list_objects_v2` with `LastModified` filtering
- For NFS targets: Use `find` command with `-newermt` flag on mounted filesystem

### 2. Standard Mount Point
**Decision**: Use `/triliodata` as the standard mount point for all targets.

**Rationale**:
- Consistent with existing datastore-attacher conventions
- Simplifies path handling across different components
- Easier to manage and debug

### 3. Handler Reuse
**Decision**: Reuse the handler instance created during cleanup phase for discovery phase.

**Rationale**:
- Both phases operate on the same target
- Avoids redundant initialization and credential parsing
- Maintains consistent backup type detection across phases

### 4. CronJob Status for Time-Based Filtering
**Decision**: Query CronJob status to get `lastSuccessfulTime`, default to 6 hours ago if not available.

**Rationale**:
- Ensures we only process truly new backups
- Avoids reprocessing backups from previous runs
- 6-hour fallback provides reasonable coverage for first run

## Implementation Details

### Abstract Methods Added to BaseBackupTargetHandler

```python
@abstractmethod
def get_backupplans_with_new_backups(
    self, 
    since_time: datetime,
    s3_client=None
) -> List[str]:
    """
    Get list of backupplan UIDs that have new backups since the given time.
    
    For S3: Use S3 API (boto3) to check LastModified timestamps.
    For NFS: Use find command on mounted filesystem.
    """
    pass

@abstractmethod
def get_latest_backup_for_backupplan(
    self,
    backupplan_uid: str
) -> Optional[str]:
    """
    Get the latest backup UID for a given backupplan.
    
    Should read backup metadata (backup.json/cluster-backup.json) and
    return the backup with the most recent creationTimestamp.
    """
    pass
```

### Concrete Methods Added to BaseBackupTargetHandler

1. **`get_last_successful_run_time(cronjob_name: str) -> datetime`**
   - Queries CronJob status for `lastSuccessfulTime`
   - Defaults to 6 hours ago if no successful run found
   - Uses `dateutil.parser` for ISO 8601 timestamp parsing

2. **`mount_target_for_discovery() -> str`**
   - Mounts target to `/triliodata`
   - For NFS: Uses standard NFS mount
   - For S3: Uses s3fuse logic (placeholder for now)

3. **`perform_discovery(cronjob_name: str) -> DiscoveryResult`**
   - Main orchestration method for discovery phase
   - Handles mounting, detection, and cleanup
   - Returns structured result with statistics

### TVK-Specific Implementation

#### `get_backupplans_with_new_backups()`

**For S3 Targets**:
```python
# Use boto3 API to list all objects
# Filter by LastModified > since_time
# Extract unique backupplan UIDs from matching object keys
```

**For NFS Targets**:
```python
# Use find command with -newermt flag
# find /triliodata -mindepth 2 -maxdepth 2 -type d -newermt "2024-01-01 00:00:00"
# Extract unique backupplan UIDs from matching paths
```

#### `get_latest_backup_for_backupplan()`

1. List all backup directories under the backupplan path
2. Read metadata from each backup:
   - Try `backup.json` (namespace-scoped backups)
   - Try `cluster-backup.json` (cluster-scoped backups)
3. Parse `creationTimestamp` from metadata
4. Sort by timestamp and return the most recent backup UID

### K8s Client Updates

Added `get_cronjob()` method to retrieve CronJob status:
```python
def get_cronjob(self, name: str, namespace: str = 'default') -> Optional[Dict]:
    """Get CronJob by name."""
    # Uses BatchV1Api to read CronJob
    # Returns dict with status.lastSuccessfulTime
```

### Main Flow Integration

```python
def main():
    # ... initialization ...
    
    # Step 3: Run cleanup phase (returns handler)
    cleanup_success, handler = run_cleanup_phase(k8s_client, backup_target)
    
    # Step 4: Run discovery phase (reuses handler)
    discovery_success = run_discovery_phase(
        k8s_client, backup_target, handler, cronjob_name
    )
    
    # ... summary and exit ...
```

## Environment Variables

Added new environment variables:
- `CRONJOB_NAME`: Name of the CronJob (passed by controller) - **Required**
- `CRONJOB_NAMESPACE`: Namespace of the CronJob (default: `default`) - Optional

## Discovery Flow

```
1. Get last successful run time from CronJob status
   └─> Default to 6 hours ago if not found

2. Detect backupplans with new backups
   ├─> S3: Use boto3 API to check LastModified
   │   ├─> List all objects in bucket
   │   ├─> Filter by LastModified > since_time
   │   └─> Extract unique backupplan UIDs
   │
   └─> NFS: Mount first, then use find
       ├─> Mount to /triliodata
       ├─> Run: find /triliodata -mindepth 2 -maxdepth 2 -type d -newermt <time>
       └─> Extract unique backupplan UIDs

3. Mount target (if not already mounted)
   ├─> S3: Only mount if new backups found (optimization)
   └─> NFS: Already mounted in step 2

4. For each backupplan with new backups:
   ├─> Get latest backup UID
   │   ├─> List backup directories
   │   ├─> Read backup.json or cluster-backup.json
   │   ├─> Parse creationTimestamp
   │   └─> Return most recent backup
   │
   └─> Create ScanInstance CR (TODO)

5. Cleanup
   └─> Unmount /triliodata
```

## Data Structures

### DiscoveryResult
```python
@dataclass
class DiscoveryResult:
    success: bool = False
    new_backups_found: int = 0
    scan_instances_created: int = 0
    backupplans_processed: List[str] = field(default_factory=list)
    failed_creations: List[str] = field(default_factory=list)
    error: Optional[str] = None
```

## Implementation Status by Backup Type

### ✅ TVK (TrilioVault for Kubernetes) - Fully Implemented

**Implemented in `tvk_handler.py`**:
- ✅ `get_backupplans_with_new_backups()` - Detects new TVK backups using S3 API or NFS find
- ✅ `get_latest_backup_for_backupplan()` - Reads TVK metadata (backup.json/cluster-backup.json)
- ✅ Parses TVK directory structure: `backupplan-uid/backup-uid/`
- ✅ Handles TVK-specific metadata format and timestamp fields

### ❌ TVO (TrilioVault for OpenStack) - Not Implemented

**Placeholder in `tvo_handler.py`**:
- ❌ `get_backupplans_with_new_backups()` - Returns empty list with warning
- ❌ `get_latest_backup_for_backupplan()` - Returns None with warning
- ❌ TVO directory structure unknown (workload-id/snapshot-id?)
- ❌ TVO metadata format unknown (snapshot.json, vm-metadata.json?)

**Why TVO is not implemented**:
- TVO directory structure differs from TVK
- TVO metadata file names and formats are different
- TVO timestamp field locations need to be determined
- Will be implemented separately when TVO requirements are clear

## Pending Work

1. **S3 Mounting**: Implement `_mount_s3_to_triliodata()` using s3fuse logic from datastore-attacher
2. **ScanInstance Creation**: Implement actual CR creation in `perform_discovery()`
3. **scanEnabled Flag**: Check BackupPlan's `scanEnabled` flag before creating ScanInstance
4. **scanOldBackups Flag**: Handle `scanOldBackups` flag for initial backupplan discovery
5. **TVO Discovery**: Implement TVO-specific discovery methods when directory structure is known

## Testing Considerations

1. **Time Handling**: Ensure timezone-aware datetime comparisons
2. **Mount Point Cleanup**: Verify `/triliodata` is properly unmounted on errors
3. **CronJob Status**: Test behavior when CronJob has no successful runs
4. **Empty Results**: Test behavior when no new backups are found
5. **S3 Pagination**: Verify handling of large S3 buckets with pagination

## Error Handling

- Discovery phase failures are logged but don't prevent cleanup phase from succeeding
- Mount failures are propagated as exceptions
- Individual backupplan processing failures are tracked in `failed_creations`
- Unmount is always attempted in finally block

## Performance Optimizations

1. **S3 Detection Without Mount**: For S3 targets, we detect new backups using API first and only mount if new backups are found
2. **Reuse Handler**: Handler instance is reused between cleanup and discovery phases
3. **Single S3 Client**: S3 client is created once and reused for all operations
4. **Efficient Filtering**: Use S3 API filtering and NFS find flags instead of post-processing

## Logging

Discovery phase provides detailed logging:
- Start/end of discovery phase
- Last successful run time (or default)
- Number of backupplans with new backups
- Latest backup for each backupplan
- ScanInstance creation attempts
- Success/failure summary with statistics

