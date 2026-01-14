# Target Poller

**Redesigned** polling architecture for threat scanning with queue-based worker processing.

## Overview

The Target Poller manages ScanInstance CRs through three phases:

1. **Initialization**: Detect backup type, populate storage state, start worker threads
2. **Cleanup**: Remove stale ScanInstance CRs for deleted backups/backupplans
3. **Discovery**: Find new backups and create ScanInstance CRs

## Key Features

### Storage State Management
- In-memory representation of entire backup target structure
- Maintained throughout all phases for efficient lookups
- Automatically filters out backups updated within last 5 minutes (still in progress)

### Queue-Based Architecture
- **Cleanup Queue**: Holds ScanInstance names to delete
- **Creation Queue**: Holds backup paths for ScanInstance creation
- **Worker Pool**: Up to 3 worker threads per queue for parallel processing

### Backup Type Support
- **TVK (TrilioVault for Kubernetes)**: ✅ Fully implemented
- **TVO (TrilioVault for OpenStack)**: ⚠️ Stub implementation (to be added later)

## Architecture

```
targetPoller/
├── main.py                     # Entry point and orchestration
├── models/
│   └── storage_state.py       # Data models (StorageState, BackupObject, etc.)
├── handlers/
│   ├── base_handler.py        # Base handler with common logic
│   ├── tvk_handler.py         # TVK-specific implementation
│   ├── tvo_handler.py         # TVO stub implementation
│   └── factory.py             # Handler factory
├── workers/
│   └── queue_workers.py       # Worker threads for queue processing
├── k8s/
│   └── client.py              # Extended Kubernetes client
└── requirements.txt
```

## Phases

### 1. Initialization Phase

**Steps:**
1. Detect backup type (TVK/TVO) by looking for marker files
   - TVK: `tvk-meta.json` (NFS) or `tvk-meta.json.manifest.<hex>` (S3)
2. Populate storage state:
   - Scan target for all backupplans and backups
   - Extract backup metadata (UID, path, timestamp, type)
   - Filter out backups updated within last 5 minutes
3. Start worker threads (3 cleanup + 3 creation workers)

**Storage State Structure:**
```python
{
    "backupplan-uid-1": [
        BackupObject(
            backup_uid="backup-uid-1",
            json_path="backupplan-uid/backup-uid/backup.json",
            last_updated_timestamp=datetime(...),
            type=BackupType.BACKUP
        ),
        ...
    ],
    ...
}
```

### 2. Cleanup Phase

**Steps:**
1. List all ScanInstances for this target (using label selector)
2. Group ScanInstances by backupplan UID
3. For each ScanInstance:
   - Extract `backupplan_uid` and `backup_uid` from labels
   - If backupplan not in storage state → Queue ALL ScanInstances of that backupplan for deletion
   - If backup not in storage state → Queue this ScanInstance for deletion
4. Worker threads consume cleanup queue and delete ScanInstances
5. Wait for all cleanup tasks to complete

**Aggressive Cleanup:**
When a backupplan is deleted from the target, ALL ScanInstances for that backupplan are deleted (not just specific backups).

### 3. Discovery Phase

**Steps:**
1. Refresh storage state (get any new backups created since initialization)
2. For each backupplan:
   a. Get latest backup (sorted by `last_updated_timestamp`)
   b. Check if backup is Available (read `status.status` from backup.json)
   c. Check if ScanInstance already exists
   d. Read `backupplan.json` to get `scanConfig`
   e. Process based on `scanEnabled` and `scanOldBackups` flags

**Scenario 1: scanOldBackups=false (Process Latest Only)**
```
For latest backup:
  - If scanEnabled=false → Stop processing this backupplan
  - If scanEnabled=true and no ScanInstance → Queue for creation
  
Walk backwards through previous backups:
  - If scanEnabled=true and no ScanInstance → Queue for creation
  - If scanEnabled=false or ScanInstance exists → Stop
```

**Scenario 2: scanOldBackups=true (Process All Unprocessed)**
```
For latest backup with scanOldBackups=true:
  - List all backups in storage state
  - List all existing ScanInstances
  - Compare and find unprocessed backups
  - Queue all unprocessed Available backups for creation
```

3. Worker threads consume creation queue and create ScanInstances
4. Wait for all creation tasks to complete

## Differences from Old Poller

| Aspect | Old Poller | Target Poller |
|--------|-----------|---------------|
| Storage State | Temporary, per-phase | Persistent, in-memory |
| Processing | Sequential | Parallel (3 workers per queue) |
| Cleanup Logic | Delete during iteration | Queue for async deletion |
| Creation Logic | Placeholder | Queue for async creation |
| Mount Strategy | Mount/unmount per phase | Mount once, reuse |
| Recent Backups | No filtering | Ignore backups updated <5 min |
| Discovery | Time-based filtering | State-based processing |

## Environment Variables

### Required
- `TARGET_NAME`: Name of the BackupTarget CR

### Optional
- `TARGET_NAMESPACE`: Namespace (default: `trilio-system`)
- `LOG_LEVEL`: Logging level (default: `INFO`)

## Usage

### Testing Discovery (Dry-Run)

Before running the full poller, test backup discovery without creating ScanInstances:

```bash
cd datastore-attacher/targetPoller
./TEST_DISCOVERY.sh my-backup-target
```

This will show all detected backups with their status and timestamps. See `TESTING_GUIDE.md` for details.

### Local Testing (Full Poller)

```bash
# Set environment variables
export TARGET_NAME=my-backup-target
export TARGET_NAMESPACE=trilio-system
export LOG_LEVEL=DEBUG

# Run target poller
cd datastore-attacher/targetPoller
python3 main.py
```

### In Kubernetes

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: target-poller
  namespace: threat-scanning-system
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: threat-scanning-poller
          containers:
          - name: poller
            image: target-poller:latest
            env:
            - name: TARGET_NAME
              value: "my-backup-target"
            - name: TARGET_NAMESPACE
              value: "trilio-system"
            - name: LOG_LEVEL
              value: "INFO"
          restartPolicy: OnFailure
```

## Data Models

### BackupObject
Represents a single backup in storage state:
```python
@dataclass
class BackupObject:
    backup_uid: str
    json_path: str  # Path to backup.json/cluster-backup.json/etc.
    last_updated_timestamp: datetime
    type: BackupType  # BACKUP, CLUSTER_BACKUP, SNAPSHOT, CLUSTER_SNAPSHOT
    status: Optional[str] = None  # Cached from backup.json
    completion_timestamp: Optional[datetime] = None  # Cached
```

### StorageState
In-memory map of backupplans to backups:
```python
@dataclass
class StorageState:
    backupplans: Dict[str, List[BackupObject]]
    
    # Helper methods
    def has_backupplan(backupplan_uid: str) -> bool
    def has_backup(backupplan_uid: str, backup_uid: str) -> bool
    def get_backup(backupplan_uid: str, backup_uid: str) -> BackupObject
```

### Queue Messages
```python
@dataclass
class CleanupMessage:
    scaninstance_name: str
    backupplan_uid: str
    backup_uid: str

@dataclass
class CreationMessage:
    backupplan_uid: str
    backup_uid: str
    backup_path: str
    backup_type: BackupType
```

## Worker Threads

### CleanupWorker
- Consumes `CleanupMessage` from cleanup queue
- Deletes ScanInstance CRs using K8s API
- Tracks: `processed_count`, `error_count`

### CreationWorker
- Consumes `CreationMessage` from creation queue
- Creates ScanInstance CRs using K8s API
- Includes backupTarget reference and backupRef in spec
- Tracks: `processed_count`, `error_count`

### WorkerPool
Manages worker lifecycle:
```python
pool = WorkerPool(num_workers=3)
pool.start_all_workers(k8s_client, target_cr)
pool.wait_for_all_completion()
pool.stop_all_workers()
stats = pool.get_stats()  # Get worker statistics
```

## TVK Implementation Details

### Detection
- **S3**: Look for `tvk-meta.json.manifest.<8-hex-digits>` pattern
- **NFS**: Look for `tvk-meta.json` in backup directories

### Storage State Population
- **S3**: Use boto3 `list_objects_v2` with regex filtering
  - Filters out data segments directory (`80bc80ff-0c51-4534-86a2-ec5e719643c2/`)
  - Filters out segment subdirectories (containing `-segments`)
  - Filters out backups updated within last 5 minutes
- **NFS**: Use `find` command to locate metadata files
  - Filters out backups updated within last 5 minutes
  - No segment filtering needed (segments are S3/s3fuse specific)

### File Formats
- **NFS**: `backup.json`, `cluster-backup.json`, etc. (plain JSON files)
- **S3 (s3fuse)**: `backup.json.manifest.<hex>`, `cluster-backup.json.manifest.<hex>`, etc.
  - Manifest format is due to s3fuse's write mechanism
  - Segment directories (`-segments`) are also s3fuse specific
  - NFS does not use manifest or segment formats

## Performance Considerations

### Storage State
- **Memory**: O(B) where B = total backups
- **Lookup**: O(1) for backupplan/backup existence checks

### Worker Parallelism
- **Cleanup**: Up to 3 ScanInstances deleted in parallel
- **Creation**: Up to 3 ScanInstances created in parallel
- **Throughput**: ~10-30 operations per second (depends on K8s API latency)

### Target Scanning
- **S3**: ~3-8 seconds for 1000 backups (API pagination)
- **NFS**: ~2-5 seconds for 1000 backups (find command)

## Error Handling

### Cleanup Errors
- Failed deletions are logged but don't stop processing
- 404 errors (already deleted) are treated as success

### Creation Errors
- Failed creations are logged but don't stop processing
- Errors are tracked in worker statistics

### Fatal Errors
- ReportingTarget unavailable → Exit immediately
- BackupTarget not found → Exit immediately
- Unknown backup type → Exit immediately
- Mount failures → Exit immediately

## Logging

### Log Levels
- **DEBUG**: Detailed operations, individual backups
- **INFO**: Phase transitions, summary statistics, worker activity
- **WARNING**: Recoverable issues, missing data
- **ERROR**: Critical failures, exceptions

### Suppressed Logs
- `boto3`, `botocore`, `urllib3`: Set to WARNING
- `kubernetes`: Set to INFO

### Example Output
```
======================================================================
TARGET POLLER - Starting
======================================================================
Target: my-s3-target
Namespace: trilio-system
...
=== INITIALIZATION PHASE ===
Detecting backup type...
Found TVK marker: backupplan-xyz/backup-abc/tvk-meta.json.manifest.12345678
Detected backup type: TVK
Populating storage state...
S3 scan complete: found 1000 backups, filtered 5 recent, added 995 to storage state
✓ Storage state populated: 50 backupplans, 995 backups
Starting worker threads...
CleanupWorker-1 started
CleanupWorker-2 started
CleanupWorker-3 started
CreationWorker-1 started
CreationWorker-2 started
CreationWorker-3 started
✓ Initialization complete

=== CLEANUP PHASE ===
Found 120 ScanInstances for this target
Grouped ScanInstances into 45 backupplans
Queued 15 stale ScanInstances for cleanup
[Worker-1] Deleting ScanInstance: abc-123-def-456
[Worker-2] Deleting ScanInstance: ghi-789-jkl-012
...
✓ Cleanup complete: 15 deleted, 0 errors

=== DISCOVERY PHASE ===
Refreshing storage state...
✓ Storage state refreshed: 50 backupplans, 1005 backups
Processing 50 backupplans...

Processing backupplan 1/50: abc-123
  Latest backup: def-456
  Queueing backup def-456 for ScanInstance creation
[Worker-1] Creating ScanInstance for backup: def-456
[Worker-1] ✓ Created ScanInstance: uuid-123 for backup def-456
...

✓ Discovery complete: 45 backupplans processed, 5 skipped, 42 ScanInstances created, 0 errors

======================================================================
TARGET POLLER - Summary
======================================================================
Cleanup:
  - Processed: 15
  - Errors: 0
Discovery:
  - Processed: 42
  - Errors: 0

✓ Target poller completed successfully
======================================================================
```

## Future Enhancements

- [ ] TVO implementation
- [ ] Parallel backupplan processing (currently sequential)
- [ ] Metrics export (Prometheus)
- [ ] Retry logic with exponential backoff
- [ ] Dry-run mode
- [ ] Incremental storage state updates (delta sync)
- [ ] Configurable worker pool size
- [ ] Configurable recent backup filter duration

## Migration from Old Poller

The old `poller/` directory remains intact as a backup. To switch to targetPoller:

1. Update CronJob manifest to use `targetPoller/main.py`
2. Test in staging environment
3. Monitor logs for any issues
4. Once stable, can remove old `poller/` directory

Both implementations can coexist for gradual migration.


