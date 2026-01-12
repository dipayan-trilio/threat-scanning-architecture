# Threat Scanning Poller

The Threat Scanning Poller is a Kubernetes CronJob that manages ScanInstance CRs for backup scanning operations.

## Features

### 1. Cleanup Phase (Implemented)
- Removes stale ScanInstance CRs for deleted backups
- Removes ALL ScanInstances for deleted backupplans (aggressive cleanup)
- Supports both S3 and NFS backup targets
- Optimized for minimal API calls and operations

### 2. Discovery Phase (TODO)
- Discovers new backups since last run
- Creates ScanInstance CRs for unscanned backups
- Handles both `scanOldBackups=true` and `scanOldBackups=false` scenarios

### 3. Monitoring Phase (TODO)
- Updates metrics
- Reports status

## Architecture

```
poller/
├── main.py                    # Entry point - orchestrates all phases
├── cleanup/                   # Cleanup phase implementation
│   ├── base_handler.py       # Abstract base class
│   ├── tvk_handler.py        # TVK-specific implementation
│   ├── tvo_handler.py        # TVO-specific implementation
│   └── factory.py            # Handler factory
├── k8s/                      # Kubernetes client
│   └── client.py             # K8s API operations
└── requirements.txt          # Python dependencies
```

## Usage

### Environment Variables

- `BACKUP_TARGET_NAME` (required): Name of the BackupTarget CR to process
- `LOG_LEVEL` (optional): Logging level (DEBUG, INFO, WARN, ERROR)

### Running Locally

```bash
# Set environment variables
export BACKUP_TARGET_NAME=my-backup-target
export LOG_LEVEL=DEBUG

# Run poller
cd datastore-attacher/poller
python3 main.py
```

### Running in Kubernetes

The poller is designed to run as a CronJob. Example manifest:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: threat-scanning-poller
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
            image: threat-scanning-poller:latest
            env:
            - name: BACKUP_TARGET_NAME
              value: "my-backup-target"
            - name: LOG_LEVEL
              value: "INFO"
          restartPolicy: OnFailure
```

## Cleanup Logic

### Stale ScanInstance Detection

A ScanInstance is considered **stale** when:
1. The backup it references no longer exists in the BackupTarget, OR
2. The entire backupplan has been deleted from the BackupTarget

### Cleanup Flow

1. **Get Target Data** (single operation)
   - S3: Single `list_objects_v2` call with pagination
   - NFS: Single `find` command

2. **Parse Structure** (single pass)
   - Build map: `{backupplan-uid: {backup-uids}}`

3. **List ScanInstances** (single K8s call)
   - Get all ScanInstances for this target
   - Group by backupplan-uid

4. **Compare and Delete**
   - For existing backupplans: Delete ScanInstances for missing backups
   - For deleted backupplans: Delete ALL ScanInstances (aggressive)

### Performance

- **S3 Target**: 1 API call to list structure + N K8s calls (N = number of backupplans)
- **NFS Target**: 1 mount + 1 find command + 1 unmount + N K8s calls
- **Time Complexity**: O(B + N) where B = total backups, N = backupplans
- **Space Complexity**: O(B) for storing backup structure in memory

## Supported Backup Types

### TVK (TrilioVault for Kubernetes)
- ✅ Fully implemented
- Directory structure: `<backupplan-uid>/<backup-uid>/`
- Supports both Backup and ClusterBackup

### TVO (TrilioVault for OpenStack)
- ⚠️ Skeleton implementation
- Needs TVO-specific directory structure and parsing logic

## Code Reuse

The poller leverages existing code from `datastore-attacher/mount_utility`:
- `triliodata_crd_parser.py` - Target CR parsing
- `kube_utilities.py` - Secret and ConfigMap fetching
- `utilities.py` - Retry logic, SSL handling
- `constants.py` - Constants
- `logger.py` - Logging

## Development

### Adding a New Backup Type

1. Create handler in `cleanup/` (e.g., `new_type_handler.py`)
2. Inherit from `BaseBackupTargetHandler`
3. Implement abstract methods:
   - `detect_backup_type()`
   - `parse_directory_structure()`
4. Update `factory.py` to create your handler
5. Add annotation support: `trilio.io/backup-type: "NEW_TYPE"`

### Testing

```bash
# Run with debug logging
export LOG_LEVEL=DEBUG
python3 main.py

# Check logs
tail -f /tmp/s3_log.txt
```

## Future Enhancements

- [ ] Implement discovery phase
- [ ] Add Prometheus metrics
- [ ] Add retry logic for failed operations
- [ ] Support for incremental cleanup (process subset of backupplans)
- [ ] Dry-run mode for testing
- [ ] Webhook notifications for cleanup events

