# Poller Cleanup Implementation Summary

## Overview

Successfully implemented the cleanup phase of the Threat Scanning Poller inside the `datastore-attacher/poller` directory. The implementation follows clean architecture principles with abstract base classes and concrete implementations for different backup types (TVK/TVO).

## What Was Implemented

### 1. Directory Structure

```
datastore-attacher/poller/
├── main.py                    # Main entry point with cleanup orchestration
├── cleanup/                   # Cleanup module
│   ├── __init__.py
│   ├── base_handler.py       # Abstract base class
│   ├── tvk_handler.py        # TVK-specific implementation
│   ├── tvo_handler.py        # TVO-specific skeleton
│   └── factory.py            # Handler factory
├── k8s/                      # Kubernetes client module
│   ├── __init__.py
│   └── client.py             # K8s API operations
├── requirements.txt          # Python dependencies
├── README.md                 # Documentation
└── test_cleanup_simple.py    # Unit tests
```

### 2. Core Components

#### BaseBackupTargetHandler (Abstract Class)
- **Purpose**: Defines common interface and shared logic for all backup target types
- **Key Methods**:
  - `perform_cleanup()`: Main orchestration method (template method pattern)
  - `get_target_data()`: Retrieves directory structure from S3/NFS
  - `_list_s3_structure()`: Single S3 API call to list all backups
  - `_list_nfs_structure()`: Single find command to list all backups
  - `_mount_nfs()` / `_unmount_nfs()`: NFS mount operations
- **Abstract Methods** (implemented by subclasses):
  - `detect_backup_type()`: Detect TVK/TVO from sample structure
  - `parse_directory_structure()`: Parse target structure into backupplan->backups map

#### TVKBackupTargetHandler
- **Purpose**: TVK-specific implementation
- **Directory Structure**: `<backupplan-uid>/<backup-uid>/`
- **Detection**: Looks for `backup.json`, `backupplan.json`, `metadata.qcow2`, etc.
- **Status**: ✅ Fully implemented and tested

#### TVOBackupTargetHandler
- **Purpose**: TVO-specific implementation
- **Status**: ⚠️ Skeleton implementation (needs TVO-specific logic)

#### BackupTargetHandlerFactory
- **Purpose**: Creates appropriate handler based on target type
- **Detection Strategy**:
  1. Check annotation: `trilio.io/backup-type`
  2. Default to TVK if no annotation

#### K8sClient
- **Purpose**: Kubernetes API operations
- **Methods**:
  - `list_scan_instances()`: List ScanInstances with label selector
  - `delete_scan_instance()`: Delete ScanInstance by name
  - `get_target()`: Get Target CR by name
  - `list_targets()`: List Target CRs

### 3. Cleanup Logic

#### Aggressive Cleanup Approach
The implementation uses an **aggressive cleanup** strategy:

1. **Stale Backup Detection**: Delete ScanInstances for backups that no longer exist
2. **Deleted Backupplan Detection**: Delete ALL ScanInstances for backupplans that are deleted from target

#### Cleanup Flow
```
1. Check ReportingTarget availability
   ↓
2. Get BackupTarget CR
   ↓
3. Get target data (SINGLE operation)
   - S3: Single list_objects_v2 call
   - NFS: Single find command
   ↓
4. Parse directory structure (SINGLE pass)
   - Build map: {backupplan-uid: {backup-uids}}
   ↓
5. List ALL ScanInstances for target (SINGLE K8s call)
   - Group by backupplan-uid
   ↓
6. Compare and delete stale ScanInstances
   - For existing backupplans: Check each backup
   - For deleted backupplans: Delete all ScanInstances
   ↓
7. Cleanup (unmount if NFS)
```

### 4. Performance Optimization

#### Minimized Operations
- **S3 Target**: 1 API call + N K8s calls (N = backupplans)
- **NFS Target**: 1 mount + 1 find + 1 unmount + N K8s calls
- **Time Complexity**: O(B + N) where B = total backups, N = backupplans
- **Space Complexity**: O(B) for storing backup structure

#### No Redundant Operations
- ✅ Single S3 list operation (not per backupplan)
- ✅ Single NFS find command (not per backupplan)
- ✅ Label selectors for efficient K8s queries
- ✅ Set-based membership checks (O(1))

### 5. Code Reuse

Leverages existing `mount_utility` code from datastore-attacher:
- ✅ `triliodata_crd_parser.py`: Target CR parsing
- ✅ `kube_utilities.py`: Secret/ConfigMap fetching
- ✅ `utilities.py`: Retry logic, SSL handling
- ✅ `constants.py`: Constants
- ✅ `logger.py`: Logging

**Benefits**:
- No duplicate credential parsing logic
- Consistent behavior with datastore-attacher
- Battle-tested utilities
- Less code to maintain

## Testing

### Unit Tests (`test_cleanup_simple.py`)
All tests passing ✅:
- S3 structure parsing
- NFS structure parsing
- Stale detection logic
- Edge cases (empty target, malformed paths, duplicates)

```
======================================================================
                    CLEANUP UNIT TESTS
======================================================================

Testing S3 structure parsing...
  ✓ S3 parsing test passed!

Testing NFS structure parsing...
  ✓ NFS parsing test passed!

Testing stale detection logic...
  ✓ Stale detection test passed!

Testing edge cases...
  ✓ Empty target handled correctly
  ✓ Malformed paths handled correctly
  ✓ Duplicates handled correctly

======================================================================
                    ALL TESTS PASSED!
======================================================================
```

## Usage

### Environment Variables
- `BACKUP_TARGET_NAME` (required): Name of the BackupTarget CR
- `LOG_LEVEL` (optional): Logging level

### Running Locally
```bash
export BACKUP_TARGET_NAME=my-backup-target
cd datastore-attacher/poller
python3 main.py
```

### Running in Kubernetes
Deploy as a CronJob (see README.md for example manifest)

## What's Next

### Phase 2: Discovery (TODO)
- Discover new backups since last run
- Create ScanInstance CRs for unscanned backups
- Handle `scanOldBackups` scenarios
- Implement time-based filtering

### Phase 3: Monitoring (TODO)
- Add Prometheus metrics
- Update status and health checks
- Implement retry logic

## Key Design Decisions

### 1. Abstract Base Class Pattern
- **Why**: Polymorphism, code reuse, extensibility
- **Benefit**: Easy to add new backup types (e.g., TVK-Enterprise)

### 2. Template Method Pattern
- **Why**: Cleanup flow is same for all types
- **Benefit**: Consistency, customization at specific points

### 3. Factory Pattern
- **Why**: Centralized type detection
- **Benefit**: Flexible, easy to extend

### 4. Single Main Entry Point
- **Why**: User requested all phases in one script
- **Benefit**: Simple deployment, easy to extend with new phases

### 5. Aggressive Cleanup
- **Why**: Prevents orphaned ScanInstances
- **Benefit**: Clean state, no resource leaks

## Files Created

1. `poller/main.py` - Main entry point (235 lines)
2. `poller/cleanup/base_handler.py` - Base handler (475 lines)
3. `poller/cleanup/tvk_handler.py` - TVK handler (105 lines)
4. `poller/cleanup/tvo_handler.py` - TVO skeleton (110 lines)
5. `poller/cleanup/factory.py` - Factory (50 lines)
6. `poller/k8s/client.py` - K8s client (180 lines)
7. `poller/requirements.txt` - Dependencies
8. `poller/README.md` - Documentation (220 lines)
9. `poller/test_cleanup_simple.py` - Unit tests (230 lines)
10. `poller/__init__.py` - Package init
11. `poller/cleanup/__init__.py` - Module init
12. `poller/k8s/__init__.py` - Module init

**Total**: ~1,600 lines of production code + tests + documentation

## Success Criteria ✅

- [x] Cleanup implemented inside datastore-attacher/poller
- [x] Single main.py with cleanup phase
- [x] Reuses existing mount_utility code
- [x] Abstract class for TVK/TVO support
- [x] Aggressive cleanup (deleted backupplans)
- [x] Optimized for minimal S3/NFS operations
- [x] Label-based ScanInstance queries
- [x] Unit tests passing
- [x] Documentation complete
- [x] Ready for discovery phase implementation

## Notes

- TVO handler is a skeleton - needs TVO-specific implementation
- Discovery phase is stubbed out - ready for implementation
- All core cleanup logic is working and tested
- Code follows Go-style clean architecture principles adapted for Python

