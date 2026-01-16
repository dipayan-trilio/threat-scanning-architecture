# Shared Utilities Package

This package contains reusable utilities for the threat scanning service that are shared between the poller and prescan components.

## Package Structure

```
shared/
├── backup_detection/      # Backup type detection (TVK/TVO)
│   ├── base_detector.py   # Abstract detector interface
│   ├── tvk_detector.py    # TVK detection logic
│   └── tvo_detector.py    # TVO detection logic (stub)
├── k8s/                   # Kubernetes client utilities
│   └── client.py          # Base K8s client for CRD operations
└── metadata/              # Metadata parsing utilities
    ├── tvk_metadata.py    # TVK metadata parsing
    └── tvo_metadata.py    # TVO metadata parsing (stub)
```

## Components

### 1. Backup Detection (`shared/backup_detection`)

Provides detectors for identifying backup types (TVK/TVO) from backup targets.

**Usage:**

```python
from shared.backup_detection import detect_backup_type

# Detect backup type
backup_type, detector = detect_backup_type(
    parsed_target=parsed_target,
    target_type='NFS',
    logger=logger,
    mount_path='/triliodata'
)

if backup_type == 'TVK':
    # Handle TVK backup
    pass
elif backup_type == 'TVO':
    # Handle TVO backup
    pass
```

**Detectors:**

- `TVKBackupDetector`: Detects TrilioVault for Kubernetes backups
  - NFS: Looks for `tvk-meta.json` files
  - S3: Looks for `tvk-meta.json.manifest.<hex>` files

- `TVOBackupDetector`: Detects TrilioVault for OpenStack backups (stub)

### 2. Kubernetes Client (`shared/k8s`)

Base Kubernetes client for interacting with threat scanning CRDs.

**Usage:**

```python
from shared.k8s.client import K8sClient

# Initialize client
client = K8sClient()

# Get Target CR
target = client.get_target('backup-target')

# List ScanInstances
scaninstances = client.list_scan_instances(
    label_selector='trilio.io/backup-target=backup-target'
)

# Patch ScanInstance
client.patch_scan_instance(
    name='scan-instance-123',
    labels={'trilio.io/instance-id': 'tvk-123'},
    annotations={'trilio.io/vm-workload': 'true'},
    status={'type': 'TVK'}
)
```

**Operations:**

- Target CR: `get_target()`, `list_targets()`
- ScanInstance CR: `get_scan_instance()`, `list_scan_instances()`, `delete_scan_instance()`, `patch_scan_instance()`

### 3. Metadata Parsing (`shared/metadata`)

Utilities for parsing backup metadata files.

**TVK Metadata (`tvk_metadata`):**

```python
from shared.metadata import tvk_metadata

# Read tvk-meta.json
tvk_meta = tvk_metadata.read_tvk_meta('/path/to/backup')
instance_id = tvk_metadata.get_instance_id(tvk_meta)

# Read backupplan.json
backupplan = tvk_metadata.read_backupplan_json('/path/to/backup')
backupplan_uid = tvk_metadata.get_backupplan_uid(backupplan)

# Check for VM workload in metadata.json
metadata = {...}  # parsed metadata.json
is_vm = tvk_metadata.check_vm_workload_in_metadata(metadata)
```

**TVO Metadata (`tvo_metadata`):**

TVO support is not yet implemented.

## Usage in Components

### TargetPoller

The targetPoller uses shared utilities for:
- Backup type detection (`TVKBackupDetector`)
- K8s operations (extends `shared.k8s.client.K8sClient`)

### Prescan CLI

The prescan CLI uses shared utilities for:
- Backup type detection
- K8s operations (patching ScanInstance CRs)
- Metadata parsing (reading tvk-meta.json, checking VM workloads)

## Benefits

1. **Code Reuse**: Single implementation shared across components
2. **Consistency**: Same detection logic everywhere
3. **Maintainability**: Fix bugs in one place
4. **Testability**: Test utilities independently
5. **Extensibility**: Easy to add TVO support

## Dependencies

- `kubernetes`: Python Kubernetes client
- `boto3`: AWS SDK for S3 operations
- `mount_utility`: Target mounting utilities

## Future Enhancements

- [ ] Implement TVO detection logic
- [ ] Add unit tests for all detectors
- [ ] Add caching for repeated K8s operations
- [ ] Support for additional backup types

