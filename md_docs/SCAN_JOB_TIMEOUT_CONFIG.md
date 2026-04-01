# Scan Job Timeout Configuration

## Overview

The scan job timeout is now configurable via an environment variable, allowing you to adjust the timeout based on your scanning requirements. Large disk images or memory dumps may require longer timeouts.

## Environment Variable

**Name**: `SCAN_JOB_TIMEOUT_SECONDS`

**Default Value**: `1500` (25 minutes)

**Description**: Defines the maximum time in seconds that a scan job can run before being marked as timed out.

## Configuration

### Via Manager Deployment

The timeout is configured in the controller manager deployment:

```yaml
env:
- name: SCAN_JOB_TIMEOUT_SECONDS
  value: "1500"  # 25 minutes (default)
```

### Recommended Values

- **Small VMs (< 50GB)**: 1500 seconds (25 minutes) - Default
- **Medium VMs (50-200GB)**: 3600 seconds (60 minutes)
- **Large VMs (200GB+)**: 7200 seconds (120 minutes)
- **Very Large VMs (500GB+)**: 10800 seconds (180 minutes)

### Updating the Timeout

1. Edit the manager deployment:
   ```bash
   kubectl edit deployment threat-scanning-controller-manager -n threat-scanning-system
   ```

2. Update the `SCAN_JOB_TIMEOUT_SECONDS` value:
   ```yaml
   env:
   - name: SCAN_JOB_TIMEOUT_SECONDS
     value: "3600"  # 60 minutes
   ```

3. Save and the controller will restart automatically with the new timeout.

Alternatively, edit the `config/manager/manager.yaml` file before deployment:

```yaml
env:
- name: SCAN_JOB_TIMEOUT_SECONDS
  value: "3600"
```

Then redeploy:
```bash
make deploy
```

## How It Works

1. **Controller Startup**: The controller reads the `SCAN_JOB_TIMEOUT_SECONDS` environment variable on startup.

2. **Scan Job Creation**: When a scan job is created for a ScanInstance, the job runs with standard Kubernetes job behavior.

3. **Timeout Check**: The controller periodically checks if scan jobs have exceeded the configured timeout:
   - Uses `IsJobPendingDeadlineExceeded(job, timeoutSeconds)` function
   - Checks elapsed time since job start
   - Only applies timeout to jobs that are stuck (not actively running)

4. **Timeout Action**: When a scan job exceeds the timeout:
   - ScanInstance condition is updated to `Scanning: Failed`
   - Event is recorded: `ScanTimeout - Scan job timed out for ScanInstance: <name>`
   - ScanInstance status is updated to `ScanFailed`
   - Job is kept for debugging (not deleted)

## Implementation Details

### Code Changes

1. **Constants** (`internal/constants.go`):
   ```go
   const (
       ScanJobTimeoutEnvVar = "SCAN_JOB_TIMEOUT_SECONDS"
       DefaultScanJobTimeoutSeconds = 1500
   )
   
   func GetScanJobTimeoutSeconds() int64 {
       if timeoutStr := os.Getenv(ScanJobTimeoutEnvVar); timeoutStr != "" {
           var timeout int64
           if _, err := fmt.Sscanf(timeoutStr, "%d", &timeout); err == nil && timeout > 0 {
               return timeout
           }
       }
       return DefaultScanJobTimeoutSeconds
   }
   ```

2. **Job Helper** (`pkg/helpers/job_helper.go`):
   ```go
   func IsJobPendingDeadlineExceeded(job *batchv1.Job, timeoutSeconds int64) bool {
       // Uses custom timeout or default if timeoutSeconds <= 0
       if timeoutSeconds <= 0 {
           timeoutSeconds = internal.JobPendingDeadlineSeconds
       }
       // ... check logic
   }
   ```

3. **Controller Usage** (`controllers/scaninstance/controller_helper.go`):
   ```go
   if helpers.IsJobPendingDeadlineExceeded(scanJob, internal.GetScanJobTimeoutSeconds()) {
       // Handle timeout
   }
   ```

### Different Timeouts for Different Jobs

| Job Type | Timeout Used | Notes |
|----------|--------------|-------|
| **Scan Job** | `SCAN_JOB_TIMEOUT_SECONDS` (configurable) | Dynamic, can be adjusted for large scans |
| **Pre-scan Job** | `JobPendingDeadlineSeconds` (900s = 15 min) | Fixed, prescan is fast validation |
| **Validation Job** | `JobPendingDeadlineSeconds` (900s = 15 min) | Fixed, validation is fast mount check |

## Troubleshooting

### Scan Job Timing Out

**Symptom**: `Warning ScanTimeout: Scan job timed out for ScanInstance: <uuid>`

**Diagnosis**:
1. Check job logs:
   ```bash
   kubectl logs -l trilio.io/scaninstance-name=<scaninstance-name> -n threat-scanning-system
   ```

2. Check if job is actually running or stuck:
   ```bash
   kubectl get pods -l trilio.io/scaninstance-name=<scaninstance-name> -n threat-scanning-system
   ```

**Solutions**:
- **Increase timeout**: If the scan is progressing but needs more time
- **Check resources**: Ensure adequate CPU/memory for scan container
- **Check disk size**: Large disks may need more time
- **Check memory dumps**: Memory analysis can be time-consuming

### Verifying Current Timeout

Check the controller's environment:
```bash
kubectl get deployment threat-scanning-controller-manager -n threat-scanning-system -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SCAN_JOB_TIMEOUT_SECONDS")].value}'
```

### Setting Timeout Per ScanInstance

Currently, the timeout is global for all scan jobs. To implement per-ScanInstance timeouts, you would need to:
1. Add a timeout field to the ScanInstance CRD spec
2. Pass the timeout to the job helper function from the spec
3. Use the global timeout as a fallback if not specified

This is a future enhancement not currently implemented.

## Best Practices

1. **Start with Default**: Use the default 25 minutes unless you have specific needs
2. **Monitor Job Duration**: Track how long your typical scans take
3. **Add Buffer**: Set timeout to 1.5-2x your average scan duration
4. **Don't Set Too High**: Very high timeouts can delay failure detection
5. **Consider Resource Limits**: Timeout should account for CPU/memory constraints

## Related Configuration

- `POSTGRES_*`: Database configuration for scan results
- `PRODUCTION`: Flag for production mode scanning
- `RELATED_IMAGE_SCANNER`: Scanner image to use
- `TARGET_POLLING_CRON`: Frequency of backup discovery

## Example Scenarios

### Scenario 1: Testing Environment
```yaml
env:
- name: SCAN_JOB_TIMEOUT_SECONDS
  value: "600"  # 10 minutes for quick feedback
```

### Scenario 2: Production with Large VMs
```yaml
env:
- name: SCAN_JOB_TIMEOUT_SECONDS
  value: "7200"  # 120 minutes for comprehensive scans
```

### Scenario 3: Mixed Workload
```yaml
env:
- name: SCAN_JOB_TIMEOUT_SECONDS
  value: "3600"  # 60 minutes (balanced)
```

## Summary

The `SCAN_JOB_TIMEOUT_SECONDS` environment variable provides flexibility to adjust scan job timeouts based on your specific scanning requirements. The default of 25 minutes (1500 seconds) works for most scenarios, but can be increased for larger VM disk images or more comprehensive scans.
