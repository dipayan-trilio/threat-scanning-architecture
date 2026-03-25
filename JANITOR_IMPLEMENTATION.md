# Janitor Service Implementation Summary

## Overview

This document summarizes the implementation of the Janitor CLI service for the threat-scanning architecture. The janitor service is responsible for cleaning up resources associated with ScanInstances to prevent resource accumulation in the Kubernetes cluster.

## Implementation Details

### 1. Janitor CLI (`cmd/janitor/main.go`)

A standalone Go binary that performs cleanup operations on ScanInstance resources.

**Key Features:**
- Command-line flags for flexible operation
- Support for both specific and bulk cleanup
- Dry-run mode for testing
- Structured JSON logging
- Kubernetes client integration

**Flags:**
- `--scan-instance`: Target specific ScanInstance (optional)
- `--status`: Filter by status (Failed/Available, default: Failed)
- `--dry-run`: Test mode without actual deletion (default: false)

**Cleanup Logic:**

For **Completed ScanInstances** (`--status=Available`):
- Deletes: Pre-scan Job, Scan Job, Redis Deployment, Redis Service, Scan ConfigMap
- Preserves: ScanInstance object (audit trail)
- Usage: Triggered by controller after scan completion

For **Failed ScanInstances** (`--status=Failed`):
- Immediate: Redis Deployment, Redis Service (all failed ScanInstances)
- Delayed (>3 days): Pre-scan Job, Scan Job, Scan ConfigMap
- Preserves: Recent failures (<3 days) for debugging
- Usage: Periodic CronJob (every 6 hours)

### 2. Controller Integration

**File:** `controllers/scaninstance/controller_helper.go`

**Function:** `createJanitorJob()`
- Creates janitor job when scan completes successfully
- Sets owner reference to ScanInstance
- Idempotent (checks for existing job)
- Logs warnings on failure (non-blocking)

**Trigger Point:**
- After `Scanning` phase reaches `Completed` status
- Before updating final condition
- Job has 5-minute TTL for automatic cleanup

### 3. Helper Functions

**File:** `pkg/helpers/job_helper.go`

**Function:** `GetJanitorJob()`
- Generates Job spec for janitor
- Configures resource limits
- Sets appropriate labels and annotations
- Uses centralized naming convention

### 4. Constants

**File:** `internal/constants.go`

Added:
- `ScanInstanceJanitorJobPrefix`: "threat-scan-janitor"
- `RelatedImageJanitor`: Environment variable for image
- `DefaultJanitorImage`: "threat-scan-janitor:latest"
- `GetJanitorImage()`: Image resolver function

### 5. CronJob Manifest

**File:** `config/manager/janitor-cronjob.yaml`

**Configuration:**
- Schedule: `0 */6 * * *` (every 6 hours)
- Concurrency: `Forbid` (prevents overlap)
- History: 3 successful, 3 failed jobs
- TTL: 1 hour after completion
- Backoff: 2 retries

### 6. Build System

**Files Modified:**
- `Dockerfile`: Now builds both manager and janitor binaries
- `Dockerfile.janitor`: Standalone janitor image build
- `Makefile`: Added janitor build targets

**New Make Targets:**
- `make build-janitor`: Build janitor binary
- `make build-all`: Build all binaries
- `make docker-build-janitor`: Build janitor Docker image
- `make docker-build-all`: Build all Docker images
- `make docker-push-janitor`: Push janitor image
- `make docker-push-all`: Push all images
- `make run-janitor`: Run janitor locally

### 7. Kustomization

**File:** `config/manager/kustomization.yaml`

Updated to include:
- `janitor-cronjob.yaml` resource
- Janitor image reference for kustomize

## Architecture Diagrams

### On-Demand Cleanup Flow

```
┌─────────────────┐
│  ScanInstance   │
│    Completes    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Controller    │
│  Reconcile()    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│ processScanJobStatus()      │
│ - Detects Completed status  │
│ - Updates ScanInstance      │
│ - Calls createJanitorJob()  │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Create Janitor Job         │
│  --scan-instance=<name>     │
│  --status=Available         │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Janitor Pod Runs           │
│  - Deletes Pre-scan Job     │
│  - Deletes Scan Job         │
│  - Deletes Redis Deploy     │
│  - Deletes Redis Service    │
│  - Deletes Scan ConfigMap   │
└─────────────────────────────┘
```

### Periodic Cleanup Flow

```
┌─────────────────┐
│   CronJob       │
│  Every 6 hours  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  Janitor Job                │
│  --status=Failed            │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  List All ScanInstances     │
│  Filter: status=Failed      │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  For Each Failed SI:        │
│  1. Delete Redis (always)   │
│  2. Check age               │
│  3. If >3 days, delete jobs │
└─────────────────────────────┘
```

## File Structure

```
threat-scanning-architecture/
├── cmd/
│   ├── janitor/
│   │   └── main.go                 # NEW: Janitor CLI entry point
│   └── manager/
│       └── main.go
├── controllers/
│   └── scaninstance/
│       ├── controller.go
│       └── controller_helper.go    # MODIFIED: Added createJanitorJob()
├── pkg/
│   └── helpers/
│       └── job_helper.go           # MODIFIED: Added GetJanitorJob()
├── internal/
│   └── constants.go                # MODIFIED: Added janitor constants
├── config/
│   └── manager/
│       ├── janitor-cronjob.yaml    # NEW: CronJob manifest
│       └── kustomization.yaml      # MODIFIED: Added janitor resources
├── Dockerfile                      # MODIFIED: Builds both binaries
├── Dockerfile.janitor              # NEW: Standalone janitor image
├── Makefile                        # MODIFIED: Added janitor targets
├── JANITOR_CLI.md                  # NEW: Comprehensive documentation
├── JANITOR_QUICKSTART.md           # NEW: Quick reference guide
└── test-janitor.sh                 # NEW: Test script
```

## Testing

### Manual Testing

```bash
# 1. Build the janitor
make build-janitor

# 2. Run in dry-run mode
./bin/janitor --scan-instance=test-scan --status=Available --dry-run

# 3. Run actual cleanup
./bin/janitor --scan-instance=test-scan --status=Available

# 4. Test periodic cleanup
./bin/janitor --status=Failed --dry-run
```

### Automated Testing

```bash
# Run the test script
./test-janitor.sh
```

The test script:
1. Creates test ScanInstances
2. Creates associated resources
3. Tests dry-run mode
4. Tests actual cleanup
5. Tests failed ScanInstance cleanup
6. Verifies resource deletion

## Deployment

### Option 1: Include in Main Deployment

The janitor CronJob is included in the kustomize configuration:

```bash
kubectl apply -k config/default
```

### Option 2: Deploy Separately

```bash
# Deploy CronJob only
kubectl apply -f config/manager/janitor-cronjob.yaml

# Deploy with RBAC
kubectl apply -f config/rbac/service_account.yaml
kubectl apply -f config/rbac/role.yaml
kubectl apply -f config/rbac/role_binding.yaml
kubectl apply -f config/manager/janitor-cronjob.yaml
```

## RBAC Requirements

The janitor uses the `trilio-threat-scanning` service account with permissions to:
- List and Get ScanInstances
- Delete Jobs, Deployments, Services, ConfigMaps

All required permissions are already present in `config/rbac/role.yaml`.

## Environment Variables

The janitor image can be configured via environment variable:

```yaml
env:
- name: RELATED_IMAGE_JANITOR
  value: "my-registry/threat-scan-janitor:v1.0.0"
```

## Design Decisions

### Why Two Cleanup Modes?

1. **On-Demand (Available):** Immediate cleanup after successful scans prevents resource accumulation
2. **Periodic (Failed):** Delayed cleanup for failures preserves debugging information while eventually cleaning up old failures

### Why 3-Day Retention?

- Balances debugging needs with resource management
- Typical incident response timeframe
- Configurable via code modification if needed

### Why Not Delete ScanInstances?

- ScanInstances serve as audit/history records
- Status and conditions provide valuable information
- Deletion should be user-controlled or policy-driven
- Kubernetes garbage collection handles owned resources

### Why Separate Janitor Binary?

- Independent scaling and resource limits
- Can run outside controller lifecycle
- Easier testing and development
- Follows single-responsibility principle

## Monitoring and Observability

### Logs

Janitor outputs structured JSON logs:

```json
{
  "component": "janitor",
  "scan-instance": "my-scan",
  "status": "Available",
  "dry-run": false,
  "level": "info",
  "msg": "Starting janitor service"
}
```

### Metrics to Monitor

- Janitor job success/failure rate
- Cleanup duration
- Number of resources deleted per run
- Failed cleanup attempts

### Alerts to Configure

- Janitor job failures (3+ consecutive)
- Cleanup taking too long (>10 minutes)
- High number of failed ScanInstances
- Resource accumulation despite janitor runs

## Future Enhancements

Potential improvements for future iterations:

1. **Configurable Retention Period:** Environment variable for 3-day threshold
2. **Metrics Endpoint:** Prometheus metrics for monitoring
3. **Selective Cleanup:** Flags to cleanup specific resource types
4. **Webhook Integration:** Notify on cleanup completion
5. **Batch Processing:** Parallel cleanup for multiple ScanInstances
6. **Cleanup Policies:** Custom cleanup rules per namespace/label

## Troubleshooting

### Janitor Not Running

**Check CronJob:**
```bash
kubectl get cronjob threat-scan-janitor -n threat-scanning-system
kubectl describe cronjob threat-scan-janitor -n threat-scanning-system
```

**Manual Trigger:**
```bash
kubectl create job --from=cronjob/threat-scan-janitor manual-test -n threat-scanning-system
```

### Resources Not Deleted

**Check Logs:**
```bash
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scan-janitor
```

**Verify RBAC:**
```bash
kubectl auth can-i delete jobs --as=system:serviceaccount:threat-scanning-system:trilio-threat-scanning -n threat-scanning-system
```

### Controller Not Creating Janitor Jobs

**Check Controller Logs:**
```bash
kubectl logs -n threat-scanning-system -l app.kubernetes.io/component=controller -f | grep janitor
```

**Verify ScanInstance Status:**
```bash
kubectl get scaninstance <name> -o jsonpath='{.status.condition}' | jq
```

## References

- Main Documentation: `JANITOR_CLI.md`
- Quick Start Guide: `JANITOR_QUICKSTART.md`
- Test Script: `test-janitor.sh`
- CronJob Manifest: `config/manager/janitor-cronjob.yaml`
- Janitor CLI: `cmd/janitor/main.go`

## Conclusion

The janitor service provides a robust, automated solution for resource cleanup in the threat-scanning architecture. It balances the need for debugging capabilities with resource management, operates both on-demand and periodically, and integrates seamlessly with the existing controller workflow.
