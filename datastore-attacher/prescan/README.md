# Prescan CLI

Prescan validation CLI for the threat scanning service. This tool validates backup targets and paths, detects backup types (TVK/TVO), checks for VM workloads, and updates ScanInstance CRs with appropriate labels and annotations.

## Overview

The prescan job is executed by the ScanInstance controller before creating the actual scan job. It performs validation and enrichment of the ScanInstance CR.

## Features

- ✅ Validates backup path exists (target already mounted by controller)
- ✅ Detects backup type (TVK/TVO)
- ✅ Uses type-specific handlers for VM detection and metadata extraction
- ✅ Detects VM workloads (mounts metadata-snapshot.qcow2 for TVK)
- ✅ Reads backup metadata (tvk-meta.json for TVK, etc.)
- ✅ Updates ScanInstance CR with labels, annotations, and status

## Usage

```bash
python3 prescan/cli.py \
  --target-name=backup-target \
  --backup-path=backupplan-uid/backup-uid \
  --backup-uid=backup-uid \
  --scaninstance-name=scan-instance-123
```

### Arguments

- `--target-name`: Name of the Target CR (required)
- `--backup-path`: Relative path to backup directory (required)
- `--backup-uid`: Backup UID (required)
- `--scaninstance-name`: Name of ScanInstance CR to update (required)

## Workflow

### 1. Path Validation

**Note**: Target is already mounted to `/triliodata` by the controller before running prescan.

```python
# Validates backup path exists and is accessible
full_backup_path = os.path.join(mount_path, backup_path)
validate_backup_path(full_backup_path)
```

### 2. Backup Type Detection

```python
# Detects TVK or TVO using shared detector
backup_type, detector = detect_backup_type(
    parsed_target, target_type, logger, mount_path
)
# Returns: 'TVK', 'TVO', or 'UNKNOWN'
# detector is the type-specific detector instance
```

### 3. VM Workload Detection & Metadata Extraction

Uses type-specific detector methods:

**For TVK:**
```python
# Detector mounts metadata-snapshot.qcow2 and checks for KubeVirt resources
is_vm_workload = detector.detect_vm_workload(full_backup_path)

# Detector reads tvk-meta.json and parses path structure
metadata = detector.extract_metadata(full_backup_path, backup_uid)
# Returns: {instance_id, backupplan_uid, backup_uid}
```

**For TVO:**
```python
# TVO-specific implementation (stub for now)
is_vm_workload = detector.detect_vm_workload(full_backup_path)
metadata = detector.extract_metadata(full_backup_path, backup_uid)
```

### 4. ScanInstance Update

```python
# Update CR with labels, annotations, and status
labels = {
    'trilio.io/instance-id': instance_id,
    'trilio.io/backup-target': target_name,  # Uses target name, not UID
    'trilio.io/backupplan': backupplan_uid,
    'trilio.io/backup': backup_uid
}

annotations = {
    'trilio.io/vm-workload': 'true' or 'false'
}

status = {
    'type': 'TVK' or 'TVO'
}

k8s_client.patch_scan_instance(scaninstance_name, labels, annotations, status)
```

## Components

### `cli.py`

Main CLI entry point. Orchestrates the entire prescan workflow.

**Key responsibilities:**
- Validates backup path exists
- Detects backup type using shared detectors
- Calls type-specific methods for VM detection and metadata extraction
- Updates ScanInstance CR

### `validator.py`

Backup path validation utilities.

```python
from prescan.validator import validate_backup_path

validate_backup_path('/triliodata/backupplan-uid/backup-uid')
# Raises: FileNotFoundError, NotADirectoryError, PermissionError
```

### Type-Specific Detectors (in `shared/backup_detection/`)

VM workload detection and metadata extraction are implemented in type-specific detector classes:

**TVK Detector (`TVKBackupDetector`):**
- `detect_vm_workload()`: Mounts metadata-snapshot.qcow2, checks for KubeVirt resources
- `extract_metadata()`: Reads tvk-meta.json, parses path structure

**TVO Detector (`TVOBackupDetector`):**
- `detect_vm_workload()`: TVO-specific implementation (stub)
- `extract_metadata()`: TVO-specific implementation (stub)

## Dependencies

- `mount_utility`: Target mounting
- `shared.backup_detection`: Backup type detection
- `shared.k8s.client`: Kubernetes operations
- `shared.metadata.tvk_metadata`: TVK metadata parsing
- `qemu-nbd`: For mounting qcow2 files
- `sudo`: Required for mount operations

## Exit Codes

- `0`: Success
- `1`: Failure (validation error, detection error, update error)

## Example Output

```
INFO: Validating target backup-target...
INFO: ✓ Target backup-target is available
INFO: Mounting target backup-target...
INFO: ✓ Successfully mounted backup-target at /triliodata
INFO: Validating backup path: /triliodata/abc-123/xyz-789
INFO: ✓ Backup path exists
INFO: Detecting TVK backup type...
INFO: ✓ Detected backup type: TVK
INFO: ✓ Extracted metadata: instance_id=tvk-123, backupplan_uid=abc-123
INFO: ✓ VM workload detection: True
INFO: Updating ScanInstance scan-instance-123...
INFO: ✓ Successfully updated ScanInstance scan-instance-123
INFO: ✓ Prescan validation completed successfully
```

## Integration with ScanInstance Controller

The Go controller creates a Kubernetes Job that runs this CLI:

```go
job := &batchv1.Job{
    Spec: batchv1.JobSpec{
        Template: corev1.PodTemplateSpec{
            Spec: corev1.PodSpec{
                Containers: []corev1.Container{
                    {
                        Name:  "prescan",
                        Image: "prescan:latest",
                        Command: []string{
                            "python3",
                            "/prescan/cli.py",
                            "--target-name=" + targetName,
                            "--backup-path=" + backupPath,
                            "--backup-uid=" + backupUID,
                            "--scaninstance-name=" + scanInstanceName,
                        },
                    },
                },
            },
        },
    },
}
```

## Error Handling

The CLI handles various error scenarios:

- **Target not found**: Exits with error
- **Target not available**: Exits with error
- **Mount failure**: Exits with error
- **Path not found**: Exits with error
- **Backup type unknown**: Exits with error
- **Metadata missing**: Exits with error
- **VM detection failure**: Logs warning, continues with `is_vm_workload=False`
- **CR update failure**: Exits with error

## Future Enhancements

- [ ] Support TVO backups
- [ ] Add retry logic for transient failures
- [ ] Support encrypted qcow2 files
- [ ] Add metrics/telemetry
- [ ] Support dry-run mode

