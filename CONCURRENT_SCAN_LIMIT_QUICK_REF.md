# Concurrent Scan Limit - Quick Reference

## Feature Overview
Limits the number of scan jobs running concurrently to prevent resource exhaustion.

## Configuration

### Environment Variable
```yaml
MAX_CONCURRENT_SCANS: "5"  # Default: 5, Set to 0 for unlimited
```

### Location
- File: `config/manager/manager.yaml`
- Line: 43-44

## Behavior

### When Limit is NOT Reached
- Scan jobs are created immediately after prescan completes
- Log: `Starting scan job (active scans: X, max: Y)`

### When Limit is Reached
- ScanInstance is queued (not failed)
- Requeued after 1 minute to check again
- Event: `ScanQueued - Waiting for scan slot (concurrent limit: X, active: Y)`
- Log: `Concurrent scan limit reached (X/Y active). Requeuing after 1 minute...`
- ScanInstance status remains `InProgress`

### When Slot Becomes Available
- Queued ScanInstance automatically starts when reconciled
- Normal scan flow continues

## Examples

### Serial Execution (One at a time)
```yaml
- name: MAX_CONCURRENT_SCANS
  value: "1"
```

### Moderate Concurrency
```yaml
- name: MAX_CONCURRENT_SCANS
  value: "5"
```

### Unlimited (No Limit)
```yaml
- name: MAX_CONCURRENT_SCANS
  value: "0"
```

## Implementation Details

### Files Changed
1. `internal/constants.go` - Added constants and getter function
2. `controllers/scaninstance/controller_helper.go` - Added concurrency check logic
3. `config/manager/manager.yaml` - Added environment variable

### Key Functions
- `GetMaxConcurrentScans()` - Returns configured limit
- `countActiveScanJobs()` - Counts currently running scan jobs
- `canStartNewScan()` - Checks if new scan can start
- `reconcileScanPhase()` - Modified to check concurrency before creating scan job

### How It Works
1. Before creating a scan job, controller lists all scan jobs with:
   - Label: `app.kubernetes.io/managed-by=threat-scanning-controller`
   - Label: `app.kubernetes.io/component=scan`
2. Counts jobs with status `InProgress`
3. If count < limit: proceeds with scan job creation
4. If count >= limit: requeues ScanInstance after 1 minute

## Monitoring

### Check Active Scans
```bash
kubectl get jobs -l app.kubernetes.io/component=scan,app.kubernetes.io/managed-by=threat-scanning-controller
```

### Check Queued ScanInstances
```bash
kubectl get events --field-selector reason=ScanQueued
```

### View ScanInstance Status
```bash
kubectl get scaninstance <name> -o yaml
```

Look for:
- Events with reason `ScanQueued`
- Status: Should be `InProgress` (not `Failed`)

## Troubleshooting

### ScanInstances Stuck in Queue
**Symptom**: Multiple ScanInstances showing `ScanQueued` events but not starting

**Check**:
1. Are there scan jobs stuck in `InProgress`?
   ```bash
   kubectl get jobs -l app.kubernetes.io/component=scan
   ```
2. Check pod status of running scan jobs:
   ```bash
   kubectl get pods -l app.kubernetes.io/component=scan
   ```
3. If jobs are stuck, they may need manual cleanup

**Solution**:
- Fix or delete stuck scan jobs
- Queued ScanInstances will automatically start on next reconciliation (within 1 minute)

### Change Concurrency Limit
```bash
kubectl edit deployment threat-scanning-controller-manager -n threat-scanning-system
# Edit MAX_CONCURRENT_SCANS value
# Pods will restart with new limit
```

## Notes

- Default limit: 5 concurrent scans
- Requeue interval: 1 minute
- Setting to 0 = unlimited (backward compatible)
- Limit applies cluster-wide (all ScanInstances)
- PreScan jobs are NOT affected by this limit (only scan jobs)
