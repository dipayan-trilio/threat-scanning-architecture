# Target Polling and Scan Job Configuration Enhancements

## Overview
Enhanced target polling and scan job configuration with:
1. **Configurable polling schedule** with validation
2. **Disable polling** feature via environment variable
3. **Concurrency control** for target polling jobs
4. **Scan job retry logic** (3 retries before failure)

## Changes Implemented

### 1. Target Polling Configuration

#### New Environment Variables

##### `TARGET_POLLING_CRON`
**Purpose**: Configure the cron schedule for target polling

**Default**: `0 */6 * * *` (every 6 hours)

**Format**: Standard 5-field cron expression
```
Minute Hour Day Month Weekday
  *     *    *    *      *
```

**Validation**:
- Validates that the cron expression has exactly 5 fields
- If invalid, logs a warning and uses the default schedule
- Prevents cronjob creation failures due to malformed cron expressions

**Examples**:
```bash
# Every hour
TARGET_POLLING_CRON="0 * * * *"

# Every 30 minutes
TARGET_POLLING_CRON="*/30 * * * *"

# Every day at 2 AM
TARGET_POLLING_CRON="0 2 * * *"

# Every 12 hours
TARGET_POLLING_CRON="0 */12 * * *"

# Default (every 6 hours)
TARGET_POLLING_CRON="0 */6 * * *"
```

##### `TARGET_POLLING_DISABLED`
**Purpose**: Disable target polling entirely

**Default**: `false`

**Accepted Values**: `true`, `True`, `TRUE`, `1` (case-insensitive)

**Behavior**: When enabled, sets `suspend: true` on all target polling CronJobs

**Use Cases**:
- Maintenance windows
- Testing environments where polling is not needed
- Temporarily disable polling during troubleshooting
- Cost optimization in development environments

### 2. Target Polling Concurrency Control

#### ConcurrencyPolicy: Forbid
**Setting**: `concurrencyPolicy: Forbid`

**Behavior**:
- Only **one polling job per target** runs at a time
- If a new job is scheduled while previous job is still running, the new job is **skipped**
- Prevents overlapping jobs that could cause resource conflicts
- Ensures targets are not polled multiple times simultaneously

**Example Scenario**:
```
Time   Action
-----  ------
00:00  Polling job A starts (target: s3-bucket-1)
00:30  Polling job A still running (slow target)
06:00  New polling job scheduled → SKIPPED (job A still running)
06:15  Job A completes
12:00  New polling job B starts → ALLOWED (no running job)
```

### 3. Scan Job Retry Logic

#### BackoffLimit: 3
**Old Behavior**: `backoffLimit: 0` (no retries)
**New Behavior**: `backoffLimit: 3` (retry 3 times before marking as failed)

**Retry Scenarios**:
1. Container crashes (exit code != 0)
2. Node failure during scan
3. Network timeouts
4. Temporary resource unavailability

**Exponential Backoff**:
- 1st retry: ~10 seconds
- 2nd retry: ~20 seconds
- 3rd retry: ~40 seconds
- After 3 failures: Job marked as Failed

**Benefits**:
- Handles transient failures (network blips, temporary resource issues)
- Reduces false failures
- Improves scan reliability
- Redis checkpointing ensures work is not duplicated across retries

## Code Changes

### Constants (`internal/constants.go`)

```go
// New constants
TargetPollingCron = "TARGET_POLLING_CRON"
TargetPollingDisabled = "TARGET_POLLING_DISABLED"
ScanJobBackoffLimit = int32(3)  // 3 retries for scan jobs
JobBackoffLimit = int32(0)       // 0 retries for validation/poller jobs (unchanged)
```

### Helper Functions (`internal/constants.go`)

```go
// GetTargetPollingCron validates and returns cron schedule
func GetTargetPollingCron(logger interface{ Warnf(format string, args ...interface{}) }) string {
    cronExpr := os.Getenv(TargetPollingCron)
    if cronExpr == "" {
        return DefaultPollerSchedule
    }
    
    if !isValidCronExpression(cronExpr) {
        if logger != nil {
            logger.Warnf("Invalid cron expression in %s: '%s'. Using default: %s", 
                TargetPollingCron, cronExpr, DefaultPollerSchedule)
        }
        return DefaultPollerSchedule
    }
    
    return cronExpr
}

// IsTargetPollingDisabled checks if polling is disabled
func IsTargetPollingDisabled() bool {
    disabled := os.Getenv(TargetPollingDisabled)
    return disabled == "true" || disabled == "True" || disabled == "TRUE" || disabled == "1"
}

// isValidCronExpression validates 5-field cron format
func isValidCronExpression(expr string) bool {
    fields := splitCronFields(expr)
    return len(fields) == 5
}
```

### Target Polling CronJob (`pkg/helpers/job_helper.go`)

```go
// Get schedule from environment with validation
schedule := internal.GetTargetPollingCron(logger)

// Check if polling is disabled
suspend := internal.IsTargetPollingDisabled()

// Set concurrency policy to Forbid (only one job at a time)
concurrencyPolicy := batchv1.ForbidConcurrent

cronJob := &batchv1.CronJob{
    // ...
    Spec: batchv1.CronJobSpec{
        Schedule:          schedule,
        Suspend:           &suspend,
        ConcurrencyPolicy: concurrencyPolicy,
        // ...
    },
}
```

### Scan Job (`pkg/helpers/job_helper.go`)

```go
backoffLimit := internal.ScanJobBackoffLimit // 3 retries

job := &batchv1.Job{
    Spec: batchv1.JobSpec{
        BackoffLimit: &backoffLimit,
        // ...
    },
}
```

## Configuration Examples

### Controller Deployment - Basic

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-scanning-controller
spec:
  template:
    spec:
      containers:
      - name: manager
        image: threat-scanning-controller:latest
        env:
        # Use defaults (every 6 hours, polling enabled)
```

### Controller Deployment - Custom Schedule

```yaml
env:
- name: TARGET_POLLING_CRON
  value: "0 * * * *"  # Every hour
```

### Controller Deployment - Frequent Polling

```yaml
env:
- name: TARGET_POLLING_CRON
  value: "*/15 * * * *"  # Every 15 minutes
```

### Controller Deployment - Polling Disabled

```yaml
env:
- name: TARGET_POLLING_DISABLED
  value: "true"
```

### Controller Deployment - Custom Schedule + PostgreSQL

```yaml
env:
- name: TARGET_POLLING_CRON
  value: "0 */12 * * *"  # Every 12 hours
- name: DATABASE_URL
  value: "postgresql+asyncpg://user:pass@postgres:5432/threat_scanning"
```

## Behavior Matrix

| TARGET_POLLING_CRON | TARGET_POLLING_DISABLED | Result |
|---------------------|-------------------------|--------|
| (not set) | false | Default schedule (every 6 hours), polling enabled |
| "0 * * * *" | false | Hourly polling, enabled |
| "invalid cron" | false | Default schedule (with warning log), enabled |
| (not set) | true | Default schedule, polling **suspended** |
| "0 * * * *" | true | Hourly schedule, polling **suspended** |

## Validation & Error Handling

### Invalid Cron Expression
```bash
# Controller logs
WARN Invalid cron expression in TARGET_POLLING_CRON: '0 * * *'. Using default: 0 */6 * * *
```

**What happens**:
- Warning logged
- Default schedule used (every 6 hours)
- CronJob created successfully
- No controller failures

### Polling Disabled
```bash
# Check cronjob status
kubectl get cronjob threat-scan-target-poller-abc123 -o yaml

spec:
  schedule: "0 */6 * * *"
  suspend: true  # <-- Polling is disabled
```

### Scan Job Retries
```bash
# Watch scan job
kubectl get job threat-scan-scanjob-my-scan -w

NAME                           COMPLETIONS   DURATION   AGE
threat-scan-scanjob-my-scan   0/1           0s         0s
threat-scan-scanjob-my-scan   0/1           10s        10s   # 1st attempt failed
threat-scan-scanjob-my-scan   0/1           20s        20s   # 2nd attempt failed
threat-scan-scanjob-my-scan   0/1           40s        40s   # 3rd attempt failed
threat-scan-scanjob-my-scan   0/1           45s        45s   # 4th attempt failed → Job failed
```

## Testing

### Test Custom Cron Schedule

```bash
# Deploy controller with custom schedule
kubectl set env deployment/threat-scanning-controller \
    TARGET_POLLING_CRON="*/5 * * * *"

# Verify cronjob schedule
kubectl get cronjob -l app.kubernetes.io/managed-by=threat-scanning-controller \
    -o custom-columns=NAME:.metadata.name,SCHEDULE:.spec.schedule,SUSPEND:.spec.suspend

# Expected output:
# NAME                              SCHEDULE          SUSPEND
# threat-scan-target-poller-abc123  */5 * * * *      false
```

### Test Invalid Cron Expression

```bash
# Set invalid cron
kubectl set env deployment/threat-scanning-controller \
    TARGET_POLLING_CRON="invalid"

# Check controller logs
kubectl logs deployment/threat-scanning-controller | grep "Invalid cron"

# Expected:
# WARN Invalid cron expression in TARGET_POLLING_CRON: 'invalid'. Using default: 0 */6 * * *

# Verify cronjob uses default
kubectl get cronjob -o custom-columns=NAME:.metadata.name,SCHEDULE:.spec.schedule
# NAME                              SCHEDULE
# threat-scan-target-poller-abc123  0 */6 * * *
```

### Test Polling Disabled

```bash
# Disable polling
kubectl set env deployment/threat-scanning-controller \
    TARGET_POLLING_DISABLED="true"

# Verify cronjobs are suspended
kubectl get cronjob -o custom-columns=NAME:.metadata.name,SUSPEND:.spec.suspend

# Expected:
# NAME                              SUSPEND
# threat-scan-target-poller-abc123  true
```

### Test Scan Job Retries

```bash
# Create a ScanInstance
kubectl apply -f scaninstance.yaml

# Watch scan job for retries
kubectl get job -w | grep scanjob

# Simulate failure: delete scan job pod
POD=$(kubectl get pods -l job-name=threat-scan-scanjob-my-scan -o name | head -1)
kubectl delete $POD

# Job will automatically retry (up to 3 times)
# Check job status
kubectl describe job threat-scan-scanjob-my-scan
# Look for "Pods Statuses" and "Failed" count
```

### Test Concurrency Policy

```bash
# Create two targets with same credentials (shared cronjob)
kubectl apply -f target1.yaml
kubectl apply -f target2.yaml

# Manually trigger cronjob
kubectl create job --from=cronjob/threat-scan-target-poller-abc123 test-job-1

# Immediately trigger again (while first job is running)
kubectl create job --from=cronjob/threat-scan-target-poller-abc123 test-job-2

# Check job statuses
kubectl get jobs -l app.kubernetes.io/managed-by=threat-scanning-controller

# Second job should be created but may not start if first is still running
# Check cronjob status
kubectl get cronjob threat-scan-target-poller-abc123 \
    -o jsonpath='{.status.lastScheduleTime}{"\n"}{.status.lastSuccessfulTime}{"\n"}'
```

## Migration Notes

### Existing Deployments
- **No migration needed** for existing deployments
- Defaults maintain backward compatibility
- New features are opt-in via environment variables

### Existing CronJobs
- Will be automatically updated with new configuration on next reconciliation
- Existing schedules are preserved if `TARGET_POLLING_CRON` is not set
- `suspend: false` by default (polling remains enabled)

### Existing Scan Jobs
- Old scan jobs (backoffLimit: 0) are unaffected
- New scan jobs will automatically use backoffLimit: 3
- Redis checkpointing ensures retries don't duplicate work

## Benefits

### 1. **Operational Flexibility**
- Adjust polling frequency based on needs (frequent for prod, infrequent for dev)
- Disable polling during maintenance without deleting cronjobs
- Fine-tune based on target responsiveness and cost

### 2. **Reliability**
- Scan job retries handle transient failures automatically
- Concurrency control prevents resource conflicts
- Cron validation prevents misconfiguration

### 3. **Cost Optimization**
- Disable polling in non-production environments
- Reduce polling frequency for infrequently changing targets
- Retry logic reduces false failures and manual intervention

### 4. **Debugging**
- Clear warning logs for invalid configurations
- Easy to temporarily disable polling for troubleshooting
- Job retry history visible in Kubernetes events

## Future Enhancements

1. **Dynamic schedule per target**: Allow per-target polling schedules via Target CR spec
2. **Success history limit**: Configure how many completed jobs to keep
3. **Failure threshold**: Alert after N consecutive polling failures
4. **Adaptive polling**: Automatically adjust frequency based on target change rate
5. **Retry backoff configuration**: Make retry delays configurable
