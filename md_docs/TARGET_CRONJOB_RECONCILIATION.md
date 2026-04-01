# Target Poller CronJob Reconciliation

## Overview

The target controller now properly reconciles existing CronJobs to match the desired state when environment variables change. This ensures that configuration changes (like `TARGET_POLLING_DISABLED` or `TARGET_POLLING_CRON`) are automatically applied to existing CronJobs.

## Reconciliation Logic

The controller compares the following fields between existing and desired CronJob specs and updates if differences are detected:

### 1. **Schedule**
- Environment Variable: `TARGET_POLLING_CRON`
- Default: `0 */6 * * *` (every 6 hours)
- Reconciliation: Updates schedule if changed
- Example: Changing from `0 */6 * * *` to `0 */12 * * *`

### 2. **Suspend State**
- Environment Variable: `TARGET_POLLING_DISABLED`
- Default: `false`
- Reconciliation: Updates suspend field if changed
- Example: Setting `TARGET_POLLING_DISABLED=true` suspends all polling CronJobs

### 3. **Concurrency Policy**
- Value: `Forbid` (prevents concurrent polling jobs)
- Reconciliation: Updates if changed from default
- Ensures only one polling job runs at a time per target

### 4. **Image**
- Environment Variable: `RELATED_IMAGE_VALIDATOR`
- Default: `registry.example.com/datastore-attacher:latest`
- Reconciliation: Updates if image changed
- Example: Updating to a new version of datastore-attacher

### 5. **Command Args**
- Contains target name and backup type
- Reconciliation: Updates if args changed
- Example: Target spec changes trigger command update

## Workflow

```
Target Reconciliation Triggered
    ↓
Build Desired CronJob Spec (from current env vars)
    ↓
Check if CronJob Exists
    ↓
Compare: Schedule, Suspend, ConcurrencyPolicy, Image, Args
    ↓
If Differences Detected → Update CronJob
    ↓
Log Update Reason
```

## Update Behavior

When the controller detects differences:

1. **Logs the change**: Records what changed and why
2. **Preserves metadata**: Keeps ResourceVersion, UID, Generation
3. **Updates the resource**: Applies the desired spec
4. **Records event**: Creates Kubernetes event for audit trail

### Example Update Log

```
Updating poller cronjob target-poller-abc123: suspend changed from false to true; schedule changed from 0 */6 * * * to 0 */12 * * *
```

## Environment Variable Changes

### Enabling/Disabling Polling

```bash
# Disable polling (suspends all CronJobs)
kubectl set env deployment/threat-scanning-controller TARGET_POLLING_DISABLED=true

# Re-enable polling (resumes all CronJobs)
kubectl set env deployment/threat-scanning-controller TARGET_POLLING_DISABLED=false
```

The controller will automatically:
- Detect the env var change on next reconciliation
- Update all target poller CronJobs' `suspend` field
- Resume or suspend based on the new value

### Changing Polling Schedule

```bash
# Change from every 6 hours to every 12 hours
kubectl set env deployment/threat-scanning-controller TARGET_POLLING_CRON="0 */12 * * *"
```

The controller will:
- Validate the cron expression
- Update all CronJobs with the new schedule
- Existing jobs continue, new jobs follow new schedule

## Reconciliation Triggers

The controller reconciles CronJobs when:

1. **Target is created/updated**: Creates or updates CronJob
2. **Target credentials change**: New credential hash triggers reconciliation
3. **Controller restart**: Reconciles all targets on startup
4. **Periodic resync**: Controller-runtime periodic reconciliation (default: 10 hours)

## Code Changes

### Files Modified

**controllers/target/controller_helper.go**
- Added suspend state comparison
- Added concurrency policy comparison
- Enhanced update reason logging
- Proper field ordering for clarity

### Comparison Logic

```go
// Compare suspend state (for TARGET_POLLING_DISABLED)
existingSuspend := existingCronJob.Spec.Suspend != nil && *existingCronJob.Spec.Suspend
desiredSuspend := desiredCronJob.Spec.Suspend != nil && *desiredCronJob.Spec.Suspend
if existingSuspend != desiredSuspend {
    needsUpdate = true
    updateReason += fmt.Sprintf("suspend changed from %v to %v", existingSuspend, desiredSuspend)
}

// Compare concurrency policy
if existingCronJob.Spec.ConcurrencyPolicy != desiredCronJob.Spec.ConcurrencyPolicy {
    needsUpdate = true
    updateReason += fmt.Sprintf("concurrency policy changed from %s to %s", ...)
}
```

## Benefits

1. **Automatic Reconciliation**: No manual intervention needed when env vars change
2. **Declarative Management**: Desired state in env vars, controller ensures actual state matches
3. **Audit Trail**: All updates logged and recorded as events
4. **Idempotent**: Safe to reconcile multiple times, no-op if already up to date
5. **Incremental Updates**: Only changed fields trigger updates

## Testing

To test the reconciliation:

1. Create a target with default settings
2. Verify CronJob created with default schedule (`0 */6 * * *`) and `suspend: false`
3. Change env var: `TARGET_POLLING_DISABLED=true`
4. Trigger reconciliation (update target annotation or wait for periodic resync)
5. Verify CronJob updated with `suspend: true`
6. Check controller logs for update reason

## Important Notes

- **Metadata Preservation**: Controller preserves ResourceVersion, UID, and Generation during updates
- **No Disruption**: Updating CronJob spec doesn't affect running jobs
- **Suspend Behavior**: When suspended, no new jobs are created, but running jobs complete
- **Schedule Changes**: Apply to new jobs only, existing jobs complete with old schedule

## Related Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TARGET_POLLING_CRON` | `0 */6 * * *` | Cron schedule for polling |
| `TARGET_POLLING_DISABLED` | `false` | Disable all polling |
| `RELATED_IMAGE_VALIDATOR` | (default image) | Datastore-attacher image |

## Monitoring

Check if CronJobs are reconciling correctly:

```bash
# View CronJob status
kubectl get cronjobs -n <namespace> -l app=target-poller

# Check suspend state
kubectl get cronjobs -n <namespace> -o jsonpath='{.items[*].spec.suspend}'

# View controller logs
kubectl logs -n <namespace> deployment/threat-scanning-controller | grep "Updating poller cronjob"
```
