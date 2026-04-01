# Scan Job Mount and Scan Implementation

## Overview

The scan job has been updated to mount the target datastore using the `datastore-attacher` utility before running the scan engine. This ensures the target is properly mounted and accessible before scanning begins.

## Implementation Details

### Command Structure

The scan job now executes a two-step command using `bash -c`:

1. **Mount the datastore** using datastore-attacher
2. **Run the scan engine** with the proper configuration files

```bash
python3 /triliovault-datastore-attacher/cli.py --target-name=<target-name> --group=threatscanning.trilio.io --version=v1 && \
python3 /app/main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json --production
```

### Security Configuration

The scan job now runs with elevated privileges required for mounting operations:

- **Privileged Mode**: Enabled (`privileged: true`)
- **User**: Root (`runAsUser: 0`)
- **Command**: `["/bin/bash", "-c"]`
- **Args**: Contains the full mount and scan command

### File Locations

- **minimal_working.json**: Located at `/app/config/minimal_working.json` (bundled with scanner image)
- **vm_artifacts_configuration.json**: Mounted from ConfigMap at `/config/vm_artifacts_configuration.json` (specific file mount using subPath)
- **main.py**: Located at `/app/main.py` (scanner entry point)
- **Target mount**: Mounted at `/triliodata` by datastore-attacher

### Configuration Flow

1. **Controller** creates a ConfigMap with VM artifacts configuration
   - ConfigMap key: `vm_artifacts_configuration.json`
   - VM keys formatted as `{vmname}_{namespace}`
   - `disk_image` paths prefixed with `/triliodata` (where target is mounted)
   - Boot disk filtering (first PVC only)

2. **Scan Job** mounts the ConfigMap as a specific file
   - Volume: ConfigMap mounted to pod
   - VolumeMount: Using `subPath` to mount only the specific file
   - File accessible at: `/config/vm_artifacts_configuration.json`

3. **Datastore Attacher** mounts the target at `/triliodata`
   - Fetches target CR from Kubernetes API
   - Mounts S3/NFS based on target type

4. **Scan Engine** reads configuration and scans VMs
   - Uses `minimal_working.json` for scan rules
   - Uses `vm_artifacts_configuration.json` for VM artifacts
   - Accesses disk images at paths like `/triliodata/backup-uid/namespace/pvc-name/disk.img`

### Environment Variables

The scan job receives the following environment variables:

- `REDIS_URL`: Redis service endpoint for job state management
  - Format: `redis://redis-svc-<scaninstance-name>.<namespace>.svc.cluster.local:6379`
- `DATABASE_URL`: Database endpoint for storing scan results
  - Default: `sqlite+aiosqlite:///./scan_analysis.db`
  - Configurable via controller's `DATABASE_URL` environment variable
- `JOB_NAME`: Job name (from metadata)
- `JOB_NAMESPACE`: Job namespace (from metadata)

### Resource Requirements

- **Requests**:
  - CPU: 500m
  - Memory: 512Mi
- **Limits**:
  - CPU: 2000m
  - Memory: 2Gi

### Retry Logic

- **BackoffLimit**: 3 (job will retry up to 3 times on failure)
- **RestartPolicy**: Never (pod does not restart on failure, job creates new pod)

## Code Changes

### Files Modified

1. **controllers/scaninstance/controller_helper.go**
   - No changes to `createScanJob` function (target name extracted from ScanInstance spec)

2. **pkg/helpers/job_helper.go**
   - Updated `GetScanConfigMapData` to use key `vm_artifacts_configuration.json` instead of `config.json`
   - Updated `GetScanJob` function signature (no change, uses ScanInstance spec)
   - Added target name extraction from `scanInstance.Spec.BackupTarget.Name`
   - Built mount command using datastore-attacher CLI
   - Built scan engine command with proper paths
   - Combined commands with `&&` operator
   - Added `SecurityContext` with `Privileged: true` and `RunAsUser: 0`
   - Updated command to use `bash -c` with args
   - Updated VolumeMount to use `subPath` for specific file mounting:
     ```go
     {
         Name:      "scan-config",
         MountPath: "/config/vm_artifacts_configuration.json",
         SubPath:   "vm_artifacts_configuration.json",
         ReadOnly:  true,
     }
     ```

## Workflow

```
ScanInstance Created
    ↓
PreScan Phase (validates backup, detects VMs)
    ↓
Redis Deployment Phase (creates Redis for job state)
    ↓
ConfigMap Created (with VM artifacts config)
    ↓
Scan Job Created
    ↓
Pod Started (privileged, as root)
    ↓
Mount Target (datastore-attacher)
    ↓
Run Scan Engine (enhanced-soc-analysis)
    ↓
Scan Results → Database (SQLite/PostgreSQL)
    ↓
Job Completes → ScanInstance Status Updated
```

## Target Mounting

The datastore-attacher utility:
- Fetches the target CR using Kubernetes client
- Determines target type (S3/NFS)
- Mounts at `/triliodata`
- Makes backup files accessible to scan engine

## Benefits

1. **Proper Mount**: Target is mounted before scanning begins
2. **Single Container**: No sidecar complexity, single container with privileged access
3. **Error Handling**: If mount fails, entire job fails (clear error state)
4. **Idempotency**: Mount command is idempotent, safe to retry
5. **Security**: Privileged access contained to scan job pod only
6. **Clean Separation**: Mount logic (datastore-attacher) separate from scan logic (enhanced-soc-analysis)

## Production Mode

The scan engine runs with `--production` flag which:
- Enables full security analysis
- Uses production-level scanning rules from `minimal_working.json`
- Stores results in database (SQLite or PostgreSQL)
- Uses Redis for checkpoint/resume functionality
