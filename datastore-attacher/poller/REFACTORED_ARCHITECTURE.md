# Refactored Discovery Architecture

## Overview

This document describes the refactored discovery architecture that separates concerns into distinct phases: discovery, filtering, and selection.

## Motivation

The previous implementation had several limitations:

1. **Mixed concerns**: Discovery and status verification were tightly coupled
2. **Limited data**: Only returned backupplan UIDs, losing context about individual backups
3. **No separation**: Couldn't easily distinguish between "discovered" vs "available" backups
4. **Hard to extend**: Difficult to add features like event-based processing

## New Architecture

### Data Models (`cleanup/models.py`)

#### `BackupMetadataType` Enum

Represents the type of backup metadata file:

```python
class BackupMetadataType(Enum):
    BACKUP = "backup"
    CLUSTER_BACKUP = "cluster-backup"
    SNAPSHOT = "snapshot"
    CLUSTER_SNAPSHOT = "cluster-snapshot"
```

#### `BackupInfo` Dataclass

Contains complete information about a discovered backup:

```python
@dataclass
class BackupInfo:
    backupplan_uid: str           # BackupPlan UID
    backup_uid: str                # Backup UID
    metadata_type: BackupMetadataType  # Type of backup
    last_modified: datetime        # Last modification time
    metadata_file_path: str        # Full path or S3 key to metadata file
```

#### `DiscoveredBackups` Dataclass

Collection of backups grouped by backupplan:

```python
@dataclass
class DiscoveredBackups:
    backups_by_plan: Dict[str, List[BackupInfo]]
    
    @property
    def total_backups(self) -> int
    
    @property
    def total_backupplans(self) -> int
    
    def add_backup(self, backup_info: BackupInfo)
    def get_backups_for_plan(self, backupplan_uid: str) -> List[BackupInfo]
```

### Three-Phase Discovery Process

#### Phase 1: Discovery (`get_backups_with_new_activity`)

**Purpose**: Find all backups with activity since a given time

**What it does**:
- Scans S3 bucket or NFS mount for backup metadata files
- Filters by modification time (`since_time`)
- Creates `BackupInfo` objects for each discovered backup
- Returns `DiscoveredBackups` with all discovered backups

**What it does NOT do**:
- Does NOT read metadata file contents
- Does NOT verify backup status
- Does NOT filter by availability

**Example output**:
```
Discovered 42 backups in 12 backupplans (since 2026-01-09 02:00:00)
```

#### Phase 2: Filtering (`filter_available_backups`)

**Purpose**: Verify which discovered backups are actually available

**What it does**:
- Takes `DiscoveredBackups` from Phase 1
- For each backup, constructs path: `/triliodata/{backupplan_uid}/{backup_uid}/{metadata_type}.json`
- Reads metadata file (handles both NFS and s3fuse manifest formats)
- Checks `status.status == "Available"`
- Returns new `DiscoveredBackups` with only available backups

**Example output**:
```
Filtering complete: 38/42 backups are available
Available backups: 38 backups in 12 backupplans
```

#### Phase 3: Selection (`get_latest_backup_per_plan`)

**Purpose**: Select the latest backup for each backupplan

**What it does**:
- Takes `DiscoveredBackups` from Phase 2 (available backups only)
- For each backupplan, reads `creationTimestamp` from metadata
- Sorts backups by creation time
- Returns `Dict[backupplan_uid, BackupInfo]` with latest backup per plan

**Example output**:
```
Latest backup for backupplan abc123: def456 (created at 2026-01-09 08:00:00)
Found latest backups for 12 backupplans
```

### Overall Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ perform_discovery()                                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Get last successful run time                               │
│     └─> since_time = 2026-01-09 02:00:00                      │
│                                                                 │
│  2. Discover backups with new activity                         │
│     └─> discovered_backups = get_backups_with_new_activity()  │
│         Result: 42 backups in 12 backupplans                   │
│                                                                 │
│  3. Mount target (if S3 and backups found)                     │
│     └─> mount_target_for_discovery()                          │
│                                                                 │
│  4. Filter to available backups                                │
│     └─> available_backups = filter_available_backups()        │
│         Result: 38 backups in 12 backupplans                   │
│                                                                 │
│  5. Get latest backup per backupplan                           │
│     └─> latest_backups = get_latest_backup_per_plan()         │
│         Result: 12 backupplans -> BackupInfo                   │
│                                                                 │
│  6. Process each backupplan (FUTURE: Create ScanInstances)    │
│     └─> For each (backupplan_uid, backup_info):               │
│         • Log backup details                                   │
│         • TODO: Create ScanInstance CR                         │
│         • TODO: Publish to event queue                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Benefits

### 1. Separation of Concerns

Each phase has a single responsibility:
- **Discovery**: Find backups by timestamp
- **Filtering**: Verify backup status
- **Selection**: Choose latest per backupplan

### 2. Rich Data Structures

`BackupInfo` contains:
- Backupplan UID
- Backup UID
- Metadata type (backup/cluster-backup/snapshot/cluster-snapshot)
- Last modified time
- Full path to metadata file

### 3. Testability

Each phase can be tested independently:
```python
# Test discovery
discovered = handler.get_backups_with_new_activity(since_time)
assert discovered.total_backups == 42

# Test filtering
available = handler.filter_available_backups(discovered)
assert available.total_backups == 38

# Test selection
latest = handler.get_latest_backup_per_plan(available)
assert len(latest) == 12
```

### 4. Observability

Clear logging at each phase:
```
Discovered 42 backups in 12 backupplans
Filtering 42 discovered backups to find available ones...
Filtering complete: 38/42 backups are available
Finding latest backup for each of 12 backupplans...
Found latest backups for 12 backupplans
Processing 12 backupplans for ScanInstance creation...
```

### 5. Extensibility

Easy to add new features:
- **Parallel filtering**: Process multiple backups concurrently
- **Caching**: Cache backup status to avoid re-reading
- **Event-based processing**: Publish `BackupInfo` to queue for async ScanInstance creation
- **Custom selection**: Different strategies (oldest, newest, specific timestamp)

## Constants

All mount paths use the constant:

```python
TRILIODATA_MOUNT_PATH = '/triliodata'
```

This is defined in `base_handler.py` and imported wherever needed.

## Implementation Details

### S3 Discovery

Uses regex to match metadata files:
```python
backup_metadata_pattern = re.compile(
    r'^(.*?)/(backup|snapshot|cluster-backup|cluster-snapshot)\.json\.manifest\.([0-9a-f]{8})$'
)
```

### NFS Discovery

Uses `find` command to search for specific files:
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

### Metadata File Reading

Handles both formats:
1. **NFS**: `backup.json`
2. **S3 (s3fuse)**: `backup.json.manifest.<8-hex-digits>`

```python
# Try exact match first (NFS)
exact_path = os.path.join(backup_base_path, backup_info.metadata_type.filename)
if os.path.exists(exact_path):
    metadata_file = exact_path
else:
    # Try manifest format (S3)
    for filename in os.listdir(backup_base_path):
        if filename.startswith(backup_info.metadata_type.filename + '.manifest.'):
            metadata_file = os.path.join(backup_base_path, filename)
            break
```

## Future: Event-Based Architecture

The refactored architecture is designed to support event-based ScanInstance creation:

```python
# Phase 6: Publish backups for async processing
publisher = ScanInstancePublisher()
publisher.start()

for backupplan_uid, backup_info in latest_backups.items():
    publisher.publish(backup_info)  # Non-blocking

publisher.queue.join()  # Wait for all to be processed
publisher.stop()
```

This will be implemented later using Python's `queue.Queue` or `asyncio.Queue`.

## Backward Compatibility

The old method `get_latest_backup_for_backupplan()` is kept but marked as deprecated:

```python
@abstractmethod
def get_latest_backup_for_backupplan(
    self,
    backupplan_uid: str
) -> Optional[str]:
    """
    DEPRECATED: Use get_latest_backup_per_plan() instead.
    This method is kept for backward compatibility.
    """
    pass
```

## TVO Support

TVO handler implements all new abstract methods with stub implementations:

```python
def get_backups_with_new_activity(...) -> DiscoveredBackups:
    self.logger.warning("TVO discovery is not yet implemented.")
    return DiscoveredBackups()

def filter_available_backups(...) -> DiscoveredBackups:
    self.logger.warning("TVO discovery is not yet implemented.")
    return DiscoveredBackups()

def get_latest_backup_per_plan(...) -> Dict:
    self.logger.warning("TVO discovery is not yet implemented.")
    return {}
```

## Testing

To test the refactored architecture:

```bash
# Set environment variables
export TARGET_NAME=your-target
export TARGET_NAMESPACE=trilio-system
export LOG_LEVEL=DEBUG

# Run the poller
python3 datastore-attacher/poller/main.py
```

Look for these log patterns:
1. `Discovered X backups in Y backupplans`
2. `Filtering X discovered backups to find available ones...`
3. `Filtering complete: X/Y backups are available`
4. `Finding latest backup for each of X backupplans...`
5. `Found latest backups for X backupplans`
6. `Processing X backupplans for ScanInstance creation...`

## Summary

The refactored architecture provides:

✅ **Clear separation of concerns**: Discovery → Filtering → Selection
✅ **Rich data structures**: Full context about each backup
✅ **Better observability**: Detailed logging at each phase
✅ **Improved testability**: Each phase can be tested independently
✅ **Extensibility**: Easy to add event-based processing
✅ **Consistent constants**: `TRILIODATA_MOUNT_PATH` used everywhere
✅ **Backward compatibility**: Old methods still available

This sets the foundation for implementing ScanInstance creation with event-based architecture in the future.


