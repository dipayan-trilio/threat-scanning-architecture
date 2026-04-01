# Quick Reference: Scan Job Timeout

## TL;DR

Set the scan job timeout via environment variable in the controller manager:

```yaml
env:
- name: SCAN_JOB_TIMEOUT_SECONDS
  value: "1500"  # Default: 25 minutes
```

## Quick Setup

```bash
# Edit deployment
kubectl edit deployment threat-scanning-controller-manager -n threat-scanning-system

# Add or update the SCAN_JOB_TIMEOUT_SECONDS env var
# Save and exit - controller will restart automatically
```

## Common Timeouts

| VM Size | Recommended Timeout | Value |
|---------|-------------------|-------|
| Small (< 50GB) | 25 minutes | `"1500"` |
| Medium (50-200GB) | 60 minutes | `"3600"` |
| Large (200GB+) | 120 minutes | `"7200"` |
| Very Large (500GB+) | 180 minutes | `"10800"` |

## Verification

```bash
# Check current timeout setting
kubectl get deployment threat-scanning-controller-manager -n threat-scanning-system \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SCAN_JOB_TIMEOUT_SECONDS")].value}'

# Check if a scan timed out
kubectl get events -n threat-scanning-system --field-selector reason=ScanTimeout
```

## Implementation Summary

### Changes Made

1. **Added constant** (`internal/constants.go`):
   - `ScanJobTimeoutEnvVar = "SCAN_JOB_TIMEOUT_SECONDS"`
   - `DefaultScanJobTimeoutSeconds = 1500`
   - `GetScanJobTimeoutSeconds()` helper function

2. **Updated job helper** (`pkg/helpers/job_helper.go`):
   - `IsJobPendingDeadlineExceeded(job, timeoutSeconds)` - now accepts timeout parameter

3. **Updated controllers**:
   - Scan job: Uses `internal.GetScanJobTimeoutSeconds()` (dynamic)
   - Pre-scan job: Uses `0` for default 900s timeout (fixed)
   - Validation job: Uses `0` for default 900s timeout (fixed)

4. **Updated deployment** (`config/manager/manager.yaml`):
   - Added `SCAN_JOB_TIMEOUT_SECONDS` environment variable

### Why Different Timeouts?

- **Scan Job**: Highly variable duration (depends on VM size, disk contents) → **Dynamic timeout**
- **Pre-scan Job**: Fast validation step (< 5 minutes typical) → **Fixed 15-minute timeout**
- **Validation Job**: Fast mount check (< 2 minutes typical) → **Fixed 15-minute timeout**

## Troubleshooting

### Timeout Event
```
Warning  ScanTimeout  Scan job timed out for ScanInstance: <uuid>
```

**Fix**: Increase `SCAN_JOB_TIMEOUT_SECONDS` or check job logs for issues.

### Check Job Status
```bash
# Find the scan job
kubectl get jobs -n threat-scanning-system -l app.kubernetes.io/component=scan

# Check pod status
kubectl get pods -n threat-scanning-system -l app.kubernetes.io/component=scan

# View logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/component=scan
```

## Related Files

- Full Documentation: `SCAN_JOB_TIMEOUT_CONFIG.md`
- Constants: `internal/constants.go`
- Job Helper: `pkg/helpers/job_helper.go`
- ScanInstance Controller: `controllers/scaninstance/controller_helper.go`
- Deployment Config: `config/manager/manager.yaml`
