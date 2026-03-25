# Threshold Minutes Feature

## Overview

The `--threshold-minutes` flag allows you to configure how long failed ScanInstances are retained before their jobs and configmaps are cleaned up. This provides flexibility for debugging without accumulating resources indefinitely.

## Flag Details

### `--threshold-minutes`
- **Type:** Integer
- **Default:** 4320 (3 days)
- **Applies to:** `--status=Failed` only
- **Units:** Minutes
- **Range:** >= 0 (0 means immediate cleanup)

## Behavior

### For Failed ScanInstances (`--status=Failed`)

#### Immediate Cleanup (all failed ScanInstances):
- Redis Deployment (always deleted)
- Redis Service (always deleted)

#### Threshold-Based Cleanup:
- Pre-scan Job (deleted if older than threshold)
- Scan Job (deleted if older than threshold)
- Scan ConfigMap (deleted if older than threshold)

### For Completed ScanInstances (`--status=Available`)
The threshold is **ignored**. All resources are cleaned up immediately:
- Pre-scan Job
- Scan Job
- Redis Deployment
- Redis Service
- Scan ConfigMap

## Common Threshold Values

| Duration | Minutes | Use Case |
|----------|---------|----------|
| 1 hour | 60 | Quick cleanup, minimal debugging |
| 6 hours | 360 | Short debugging window |
| 1 day | 1440 | Daily cleanup cycle |
| 3 days | 4320 | **Default** - Standard debugging window |
| 7 days | 10080 | Extended debugging for complex issues |
| 14 days | 20160 | Long-term retention |
| 30 days | 43200 | Maximum retention |

## Usage Examples

### Default Behavior (3 days)
```bash
janitor --status=Failed
# Equivalent to:
janitor --status=Failed --threshold-minutes=4320
```

### Aggressive Cleanup (1 day)
```bash
janitor --status=Failed --threshold-minutes=1440
```

### Extended Debugging (7 days)
```bash
janitor --status=Failed --threshold-minutes=10080
```

### Immediate Cleanup (no retention)
```bash
janitor --status=Failed --threshold-minutes=0
```

### Specific ScanInstance with Custom Threshold
```bash
janitor --scan-instance=my-failed-scan --status=Failed --threshold-minutes=2880
```

## CronJob Configuration

Update the CronJob to use a different threshold:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: threat-scan-janitor
spec:
  schedule: "0 */6 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: janitor
            image: janitor:latest
            command: ["/app/janitor"]
            args:
            - --status=Failed
            - --threshold-minutes=10080  # 7 days instead of default 3 days
```

## Environment Variable Alternative

You can also set the threshold via environment variable (future enhancement):

```yaml
env:
- name: JANITOR_THRESHOLD_MINUTES
  value: "7200"  # 5 days
```

## Logging

The janitor logs include the threshold value:

```json
{
  "component": "janitor",
  "status": "Failed",
  "threshold-minutes": 4320,
  "level": "info",
  "msg": "Starting janitor service"
}
```

When processing a ScanInstance:

```json
{
  "level": "info",
  "msg": "ScanInstance is newer than threshold (created: 2026-02-26T10:00:00Z, threshold: 4320 minutes). Skipping job/configmap cleanup"
}
```

Or:

```json
{
  "level": "info",
  "msg": "ScanInstance is older than threshold (created: 2026-02-20T10:00:00Z, threshold: 4320 minutes). Proceeding with full cleanup"
}
```

## Design Rationale

### Why Minutes Instead of Days?

1. **Precision:** Allows fine-grained control (e.g., 90 minutes)
2. **Flexibility:** Easy to express any duration (hours, days, weeks)
3. **No Ambiguity:** Clear unit of measurement
4. **Standard Practice:** Many systems use minutes/seconds for duration

### Why Default to 3 Days?

1. **Balance:** Enough time for debugging, but not too long
2. **Incident Response:** Typical incident investigation window
3. **Resource Management:** Prevents long-term accumulation
4. **Adjustable:** Can be changed per deployment needs

### Why Redis is Always Deleted?

Redis resources consume significant cluster resources (CPU, memory) and don't contain debugging information. The actual debugging data is in job logs, which are preserved based on the threshold.

## Validation

The janitor validates the threshold value:

```bash
# Invalid: negative value
janitor --status=Failed --threshold-minutes=-100
# Error: Invalid threshold-minutes: -100. Must be >= 0
```

Valid values: 0 or any positive integer

## Migration from Hardcoded 3 Days

**Before:**
```go
threeDaysAgo := time.Now().Add(-72 * time.Hour)
```

**After:**
```go
thresholdDuration := time.Duration(thresholdMinutes) * time.Minute
thresholdTime := time.Now().Add(-thresholdDuration)
```

## Best Practices

1. **Production:** Use default 3 days (4320 minutes) or longer
2. **Development:** Use shorter thresholds (1-2 days) for faster cleanup
3. **Testing:** Use very short thresholds (60-360 minutes) or 0 for immediate cleanup
4. **Long-term Issues:** Increase to 7-14 days when investigating complex problems
5. **Monitor Trends:** Track how often you need to extend debugging windows

## Troubleshooting

### Threshold Not Working

**Check logs:**
```bash
kubectl logs <janitor-pod> | grep threshold
```

**Verify flag is passed:**
```bash
kubectl describe job <janitor-job> | grep args
```

### Resources Still Present

**Check ScanInstance age:**
```bash
kubectl get scaninstance <name> -o jsonpath='{.metadata.creationTimestamp}'
```

**Calculate age manually:**
```bash
# Compare with threshold
# If created less than threshold minutes ago, jobs won't be deleted
```

## Future Enhancements

Potential improvements:

1. **Environment Variable Support:** `JANITOR_THRESHOLD_MINUTES`
2. **Per-Namespace Thresholds:** Different thresholds for different namespaces
3. **Label-Based Thresholds:** Set threshold via ScanInstance labels
4. **Metrics:** Track average age of cleaned up resources
5. **Auto-Adjust:** Dynamically adjust based on cluster resource pressure
