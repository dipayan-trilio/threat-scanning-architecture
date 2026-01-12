# Local Testing Guide for Threat Scanning Poller

## Overview

This guide explains how to test the poller locally without deploying to Kubernetes.

## Prerequisites

1. **Python 3.8+** installed
2. **kubectl** configured with access to your Kubernetes cluster
3. **Python dependencies** installed (see below)
4. **Access to a BackupTarget** (NFS or S3) with TVK backups

## Setup

### 1. Install Python Dependencies

```bash
cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture/datastore-attacher

# Install required packages
pip install kubernetes boto3 python-dateutil
```

### 2. Set Up Kubeconfig

The poller uses the `VM_MOUNT` environment variable to detect local development mode:

```bash
# Enable local development mode (uses kubeconfig instead of in-cluster config)
export VM_MOUNT=true
```

### 3. Configure Environment Variables

Create a test script or export these variables:

```bash
#!/bin/bash

# Required variables
export BACKUP_TARGET_NAME="your-target-name"
export CRONJOB_NAME="your-cronjob-name"

# Optional variables
export CRONJOB_NAMESPACE="default"
export DISCOVERY_LOOKBACK_HOURS="24"  # For testing: look back 24 hours instead of 6
export LOG_LEVEL="DEBUG"              # Enable debug logging
export VM_MOUNT="true"                # Enable local development mode

# Run the poller
python3 poller/main.py
```

## Configuring Discovery Lookback Time

### Default Behavior (6 Hours)

By default, if the CronJob has no successful run history, the poller looks back **6 hours** for new backups.

**Location in code**: `cleanup/base_handler.py`, line 608 and 614

### For Testing: Increase Lookback Time

To test with older backups, set the `DISCOVERY_LOOKBACK_HOURS` environment variable:

```bash
# Look back 24 hours for testing
export DISCOVERY_LOOKBACK_HOURS="24"

# Look back 7 days for testing
export DISCOVERY_LOOKBACK_HOURS="168"

# Look back 30 days for testing
export DISCOVERY_LOOKBACK_HOURS="720"
```

### After Testing: Revert to Default

Simply unset the environment variable or set it back to 6:

```bash
# Unset (will use default of 6)
unset DISCOVERY_LOOKBACK_HOURS

# Or explicitly set to 6
export DISCOVERY_LOOKBACK_HOURS="6"
```

**Note**: In production (Kubernetes CronJob), you don't need to set this variable unless you want to override the default.

## Complete Test Script

Create a file `test_poller.sh`:

```bash
#!/bin/bash

# Exit on error
set -e

echo "=========================================="
echo "Threat Scanning Poller - Local Test"
echo "=========================================="
echo ""

# Configuration
export BACKUP_TARGET_NAME="my-backup-target"
export CRONJOB_NAME="poller-my-backup-target"
export CRONJOB_NAMESPACE="default"
export DISCOVERY_LOOKBACK_HOURS="24"  # Test with 24 hours lookback
export LOG_LEVEL="DEBUG"
export VM_MOUNT="true"

echo "Configuration:"
echo "  Target: $BACKUP_TARGET_NAME"
echo "  CronJob: $CRONJOB_NAME"
echo "  Namespace: $CRONJOB_NAMESPACE"
echo "  Lookback: $DISCOVERY_LOOKBACK_HOURS hours"
echo "  Log Level: $LOG_LEVEL"
echo ""

# Verify kubectl access
echo "Verifying kubectl access..."
kubectl get targets $BACKUP_TARGET_NAME &> /dev/null
if [ $? -eq 0 ]; then
    echo "✓ Target '$BACKUP_TARGET_NAME' found"
else
    echo "✗ Target '$BACKUP_TARGET_NAME' not found"
    exit 1
fi
echo ""

# Run the poller
echo "Running poller..."
echo "=========================================="
cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture/datastore-attacher
python3 poller/main.py

echo ""
echo "=========================================="
echo "Test completed"
echo "=========================================="
```

Make it executable:

```bash
chmod +x test_poller.sh
./test_poller.sh
```

## Testing Different Scenarios

### Scenario 1: Test Cleanup Only (No Discovery)

Temporarily disable discovery by commenting out the call in `main.py`:

```python
# Step 4: Run discovery phase (reuse handler from cleanup)
# discovery_success = run_discovery_phase(k8s_client, backup_target, handler, cronjob_name)
discovery_success = True  # Skip discovery for testing
```

### Scenario 2: Test with Very Old Backups

Set a large lookback window:

```bash
export DISCOVERY_LOOKBACK_HOURS="8760"  # 1 year
```

### Scenario 3: Test with Fresh Backups Only

Set a small lookback window:

```bash
export DISCOVERY_LOOKBACK_HOURS="1"  # Last 1 hour only
```

### Scenario 4: Test Without CronJob Status

If you don't have a CronJob created yet, the poller will automatically fall back to the lookback hours:

```bash
export CRONJOB_NAME="non-existent-cronjob"
export DISCOVERY_LOOKBACK_HOURS="24"
```

The poller will log:
```
Failed to get CronJob status: ..., defaulting to 24 hours ago
```

## Dry Run Mode (Optional Enhancement)

For safer testing, you can add a dry-run mode. Create a file `test_poller_dryrun.sh`:

```bash
#!/bin/bash

# Dry run: Don't actually delete or create CRs
export DRY_RUN="true"
export BACKUP_TARGET_NAME="my-backup-target"
export CRONJOB_NAME="poller-my-backup-target"
export DISCOVERY_LOOKBACK_HOURS="24"
export LOG_LEVEL="DEBUG"
export VM_MOUNT="true"

cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture/datastore-attacher
python3 poller/main.py
```

**Note**: You'll need to implement dry-run logic in the code to respect this flag.

## Troubleshooting

### Issue: "Failed to load Kubernetes config"

**Solution**: Make sure `VM_MOUNT=true` is set and your kubeconfig is valid:

```bash
export VM_MOUNT=true
kubectl cluster-info
```

### Issue: "Target not found"

**Solution**: Verify the target name and that it exists:

```bash
kubectl get targets
kubectl get target $BACKUP_TARGET_NAME -o yaml
```

### Issue: "Permission denied" when mounting NFS

**Solution**: Run with sudo or ensure your user has mount permissions:

```bash
sudo -E python3 poller/main.py
```

The `-E` flag preserves environment variables.

### Issue: S3 credentials not found

**Solution**: Verify the target has valid credentials:

```bash
kubectl get target $BACKUP_TARGET_NAME -o jsonpath='{.spec.objectStoreCredentials}'
```

### Issue: "No module named 'kubernetes'"

**Solution**: Install dependencies:

```bash
pip install kubernetes boto3 python-dateutil
```

## Monitoring Test Output

### Expected Output Structure

```
======================================================================
               THREAT SCANNING POLLER
======================================================================

Target: my-backup-target
CronJob: poller-my-backup-target (namespace: default)

✓ ReportingTarget 'reporting-target' is available
✓ BackupTarget 'my-backup-target' fetched successfully

======================================================================
                     CLEANUP PHASE
======================================================================
Step 1: Detecting backup type from target structure...
Backup type: TVK

Step 2: Creating handler...

Step 3: Performing cleanup...
Found 5 backupplans with total 20 backups
Found 15 total ScanInstances for target
STALE: ScanInstance scan-backup-xyz references backup xyz which no longer exists

----------------------------------------------------------------------
✓ CLEANUP COMPLETED SUCCESSFULLY
  - Backup type: TVK
  - Backupplans processed: 5
  - Total backups found: 20
  - Stale ScanInstances deleted: 3
  - Failed deletions: 0
----------------------------------------------------------------------

======================================================================
                    DISCOVERY PHASE
======================================================================
Looking for backups created since: 2024-12-29 06:00:00
Found 2 backupplans with new backups
Latest backup for backupplan abc-123: backup-xyz-456 (created at 2024-12-30 08:00:00)

----------------------------------------------------------------------
✓ DISCOVERY COMPLETED SUCCESSFULLY
  - New backups found: 2
  - Backupplans processed: 2
  - ScanInstances created: 2
  - Failed creations: 0
----------------------------------------------------------------------

======================================================================
                         SUMMARY
======================================================================
  Cleanup Phase:    ✓ SUCCESS
  Discovery Phase:  ✓ SUCCESS
======================================================================
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BACKUP_TARGET_NAME` | Yes | - | Name of the BackupTarget CR |
| `CRONJOB_NAME` | Yes | - | Name of the CronJob |
| `CRONJOB_NAMESPACE` | No | `default` | Namespace of the CronJob |
| `DISCOVERY_LOOKBACK_HOURS` | No | `6` | Hours to look back for new backups |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARN, ERROR) |
| `VM_MOUNT` | No | - | Set to `true` for local development |

## Testing Checklist

Before running in production, test these scenarios locally:

- [ ] Cleanup phase with stale ScanInstances
- [ ] Cleanup phase with deleted BackupPlan (aggressive cleanup)
- [ ] Discovery phase with new backups (within lookback window)
- [ ] Discovery phase with no new backups
- [ ] Discovery phase with very old backups (outside lookback window)
- [ ] S3 target (if applicable)
- [ ] NFS target (if applicable)
- [ ] CronJob with no successful run history
- [ ] CronJob with successful run history
- [ ] Invalid target name (error handling)
- [ ] ReportingTarget unavailable (error handling)

## Reverting Changes After Testing

After testing with modified lookback hours, revert to production settings:

```bash
# Remove test-specific environment variables
unset DISCOVERY_LOOKBACK_HOURS
unset LOG_LEVEL
unset VM_MOUNT

# Or set to production values
export DISCOVERY_LOOKBACK_HOURS="6"
export LOG_LEVEL="INFO"
```

In production (Kubernetes CronJob), the default values will be used unless explicitly overridden in the CronJob spec.

## Next Steps

Once local testing is complete:

1. Build Docker image with the poller code
2. Deploy as Kubernetes CronJob
3. Configure CronJob environment variables
4. Monitor CronJob execution logs
5. Verify ScanInstance CRs are created/deleted correctly

