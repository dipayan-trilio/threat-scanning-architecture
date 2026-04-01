# Janitor CLI

The Janitor CLI is a cleanup utility for managing resources associated with ScanInstances in the threat-scanning architecture. It runs in two modes:

## Overview

The janitor service handles cleanup of resources created during the scanning lifecycle:
- Pre-scan Jobs
- Scan Jobs
- Redis Deployments and Services
- Scan ConfigMaps

## Modes of Operation

### 1. On-Demand Cleanup (Triggered by Controller)

When a ScanInstance completes successfully, the controller automatically creates a janitor job to clean up resources:

```bash
janitor --scan-instance <name> --status Available
```

**What it cleans:**
- Pre-scan Job
- Scan Job
- Redis Deployment
- Redis Service
- Scan ConfigMap

**Note:** The ScanInstance object itself is NOT deleted.

### 2. Periodic Cleanup (CronJob)

A CronJob runs every 6 hours to clean up resources from failed ScanInstances:

```bash
janitor --status Failed
```

**What it cleans:**

For **all** failed ScanInstances:
- Redis Deployment (immediately)
- Redis Service (immediately)

For failed ScanInstances **older than threshold** (default: 3 days / 4320 minutes):
- Pre-scan Job
- Scan Job
- Scan ConfigMap

The threshold retention period allows for debugging of recent failures while cleaning up old resources.

## CLI Flags

### `--scan-instance`
- **Type:** String
- **Default:** Empty (processes all ScanInstances)
- **Description:** Name of a specific ScanInstance to cleanup. If not provided, all ScanInstances matching the status filter are processed.

### `--status`
- **Type:** String
- **Default:** `Failed`
- **Valid Values:** `Failed`, `Available`
- **Description:** Status filter for cleanup operations
  - `Available`: Targets completed ScanInstances (used by on-demand cleanup)
  - `Failed`: Targets failed ScanInstances (used by periodic cleanup)

### `--threshold-minutes`
- **Type:** Integer
- **Default:** `4320` (3 days)
- **Description:** Threshold in minutes for cleaning up failed ScanInstances. Only applies when `--status=Failed`. ScanInstances older than this threshold will have their jobs and configmaps deleted. Redis resources are always deleted immediately regardless of age.

### `--dry-run`
- **Type:** Boolean
- **Default:** `false`
- **Description:** When enabled, logs what would be deleted without actually performing deletions. Useful for testing.

## Usage Examples

### Clean up a specific completed ScanInstance
```bash
janitor --scan-instance my-scan-123 --status Available
```

### Clean up all failed ScanInstances (periodic mode)
```bash
janitor --status Failed
```

### Dry run to see what would be deleted
```bash
janitor --status Failed --dry-run
```

### Clean up a specific failed ScanInstance
```bash
janitor --scan-instance failed-scan-456 --status Failed
```

### Use custom threshold (1 day instead of 3 days)
```bash
janitor --status Failed --threshold-minutes 1440
```

### Use custom threshold (7 days)
```bash
janitor --status Failed --threshold-minutes 10080
```

## Deployment

### CronJob Deployment

The janitor CronJob is deployed via the manifest at `config/manager/janitor-cronjob.yaml`:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: threat-scan-janitor
  namespace: threat-scanning-system
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  ...
```

Deploy with:
```bash
kubectl apply -f config/manager/janitor-cronjob.yaml
```

### On-Demand Jobs

On-demand janitor jobs are automatically created by the ScanInstance controller when scans complete. No manual intervention is required.

## Building

### Build Binary
```bash
make build-janitor
```

### Build Docker Image
```bash
make docker-build-janitor
```

### Build and Push
```bash
make docker-build-janitor docker-push-janitor
```

## RBAC Requirements

The janitor requires the following permissions:
- Read access to ScanInstances (list, get)
- Delete access to Jobs, Deployments, Services, and ConfigMaps

These permissions are granted via the `trilio-threat-scanning` service account.

## Environment Variables

None required. The janitor uses in-cluster Kubernetes configuration.

## Logging

The janitor outputs structured JSON logs with the following fields:
- `component`: Always set to "janitor"
- `scan-instance`: Name of the ScanInstance being processed
- `status`: Status filter being used
- `dry-run`: Whether dry-run mode is enabled

## Error Handling

- If a specific ScanInstance is not found, the janitor logs a warning and exits successfully
- If resource deletion fails, the error is logged but the janitor continues processing other resources
- Failed deletions do not cause the janitor to fail entirely

## Integration with Controller

The ScanInstance controller creates janitor jobs at the following points:

1. **After Successful Scan Completion:**
   - Condition: `Scanning` phase reaches `Completed` status
   - Action: Creates janitor job with `--scan-instance <name> --status Available`
   - Owner Reference: Set to the ScanInstance (cleaned up when ScanInstance is deleted)

The janitor job has a TTL of 5 minutes after completion, allowing for log inspection while preventing resource accumulation.

## Design Decisions

### Why 3-Day Retention for Failed Jobs?

Failed scan jobs and their associated resources are kept for 3 days to allow debugging:
- Inspect job logs
- Review ConfigMap contents
- Analyze failure patterns

After 3 days, these resources are assumed to be old enough that debugging is complete.

### Why Separate Redis Cleanup?

Redis deployments and services are cleaned up immediately for failed ScanInstances because:
- They consume cluster resources (CPU, memory)
- They don't contain debugging information (logs are in jobs)
- Failed scans don't need active Redis instances

### Why Not Delete ScanInstance Objects?

ScanInstance objects serve as audit trails and history. They contain:
- Status and conditions showing what happened
- Timestamps for tracking
- Annotations with error details

These should be managed by users or external lifecycle policies, not the janitor.
