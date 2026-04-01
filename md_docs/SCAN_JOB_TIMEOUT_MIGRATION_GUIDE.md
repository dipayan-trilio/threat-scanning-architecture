# Migration Guide: Scan Job Timeout Update

## Overview

This guide helps you update existing threat-scanning deployments to use the new dynamic scan job timeout feature.

## What Changed?

The scan job timeout is now configurable via environment variable instead of being hardcoded.

- **Before**: Fixed 15-minute timeout for all jobs
- **After**: Configurable timeout for scan jobs (default: 25 minutes), fixed timeout for other jobs

## Migration Steps

### Step 1: Check Current Deployment

```bash
# Check if controller is running
kubectl get deployment threat-scanning-controller-manager -n threat-scanning-system

# Check current environment variables
kubectl get deployment threat-scanning-controller-manager -n threat-scanning-system \
  -o yaml | grep -A 20 "env:"
```

### Step 2: Update Controller Image

If you built the updated controller image:

```bash
# Update the image
kubectl set image deployment/threat-scanning-controller-manager \
  manager=<your-registry>/threat-scanning-controller:latest \
  -n threat-scanning-system
```

Or if using the manifest:

```bash
# Apply updated manifests
cd threat-scanning-architecture
make deploy
```

### Step 3: Add Environment Variable (Optional)

If you want a custom timeout (different from the 25-minute default):

```bash
# Edit the deployment
kubectl edit deployment threat-scanning-controller-manager -n threat-scanning-system
```

Add or update under `spec.template.spec.containers[0].env`:

```yaml
env:
- name: SCAN_JOB_TIMEOUT_SECONDS
  value: "3600"  # 60 minutes for example
```

Save and exit. The controller will restart automatically.

### Step 4: Verify the Update

```bash
# Run the verification script
./verify_scan_job_timeout.sh

# Or manually check
kubectl get deployment threat-scanning-controller-manager -n threat-scanning-system \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SCAN_JOB_TIMEOUT_SECONDS")].value}'
```

## No Changes Required If...

You **don't need to do anything** if:

1. The default 25-minute timeout works for your VMs
2. You're okay with automatic updates via the deployment manifest

The controller will use the default timeout (1500 seconds = 25 minutes) if `SCAN_JOB_TIMEOUT_SECONDS` is not explicitly set.

## Recommended Timeout Values

Based on your typical VM sizes:

| Your VM Size | Recommended Value | Command |
|--------------|------------------|---------|
| Small (< 50GB) | Keep default | No action needed |
| Medium (50-200GB) | 60 minutes | Set to `"3600"` |
| Large (200GB+) | 120 minutes | Set to `"7200"` |
| Very Large (500GB+) | 180 minutes | Set to `"10800"` |

## Rollback Plan

If you encounter issues after the update:

### Option 1: Adjust Timeout

If scans are timing out too quickly:

```bash
kubectl edit deployment threat-scanning-controller-manager -n threat-scanning-system
# Increase SCAN_JOB_TIMEOUT_SECONDS value
```

### Option 2: Remove Custom Timeout

To revert to the default:

```bash
kubectl edit deployment threat-scanning-controller-manager -n threat-scanning-system
# Remove the SCAN_JOB_TIMEOUT_SECONDS line entirely
```

### Option 3: Roll Back Image

If you need to roll back to the previous controller version:

```bash
# Check deployment history
kubectl rollout history deployment/threat-scanning-controller-manager -n threat-scanning-system

# Roll back to previous version
kubectl rollout undo deployment/threat-scanning-controller-manager -n threat-scanning-system
```

## Monitoring After Migration

### 1. Check for Timeout Events

```bash
# Watch for ScanTimeout events
kubectl get events -n threat-scanning-system --field-selector reason=ScanTimeout --watch
```

### 2. Monitor Scan Job Duration

```bash
# Check active scan jobs
kubectl get jobs -n threat-scanning-system -l app.kubernetes.io/component=scan

# Check scan job pods
kubectl get pods -n threat-scanning-system -l app.kubernetes.io/component=scan
```

### 3. Review Logs

```bash
# Controller logs
kubectl logs -n threat-scanning-system -l control-plane=controller-manager --tail=100

# Scan job logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/component=scan --tail=100
```

## Troubleshooting

### Problem: Scans Still Timing Out

**Symptoms:**
- `ScanTimeout` events in Kubernetes
- ScanInstance status shows `ScanFailed`

**Solutions:**
1. Increase the timeout:
   ```bash
   kubectl edit deployment threat-scanning-controller-manager -n threat-scanning-system
   # Set SCAN_JOB_TIMEOUT_SECONDS to a higher value
   ```

2. Check if scans are actually progressing:
   ```bash
   kubectl logs -n threat-scanning-system -l app.kubernetes.io/component=scan
   ```

3. Verify sufficient resources:
   ```bash
   kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/component=scan
   ```

### Problem: Environment Variable Not Applied

**Symptoms:**
- Verification script shows timeout not set
- Deployment shows the variable but pods don't have it

**Solutions:**
1. Force pod restart:
   ```bash
   kubectl rollout restart deployment/threat-scanning-controller-manager -n threat-scanning-system
   ```

2. Wait for automatic rollout:
   ```bash
   kubectl rollout status deployment/threat-scanning-controller-manager -n threat-scanning-system
   ```

### Problem: Invalid Timeout Value

**Symptoms:**
- Controller using default timeout despite setting a value
- Unusual timeout behavior

**Solutions:**
1. Verify the value is a positive integer:
   ```yaml
   - name: SCAN_JOB_TIMEOUT_SECONDS
     value: "3600"  # Must be quoted string containing a number
   ```

2. Check controller logs for warnings:
   ```bash
   kubectl logs -n threat-scanning-system -l control-plane=controller-manager | grep -i timeout
   ```

## Testing the Migration

### Test 1: Verify Environment Variable

```bash
# Should return the timeout value (or empty for default)
kubectl get deployment threat-scanning-controller-manager -n threat-scanning-system \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SCAN_JOB_TIMEOUT_SECONDS")].value}'
```

### Test 2: Create a Test ScanInstance

```bash
# Create a test ScanInstance
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-timeout-scan
  namespace: threat-scanning-system
spec:
  backupTarget:
    name: your-target-name
  backupUID: your-backup-uid
  backupPath: your-backup-path
EOF

# Watch the scan job
kubectl get jobs -n threat-scanning-system -l trilio.io/scaninstance-name=test-timeout-scan --watch

# Clean up
kubectl delete scaninstance test-timeout-scan -n threat-scanning-system
```

### Test 3: Run Verification Script

```bash
cd threat-scanning-architecture
./verify_scan_job_timeout.sh
```

## Deployment Strategies

### Strategy 1: Gradual Rollout (Recommended)

1. Deploy to test/staging environment first
2. Monitor for 24-48 hours
3. Verify timeout behavior with real scans
4. Deploy to production

### Strategy 2: Immediate Deployment

1. Backup current deployment config
2. Apply new manifest with `make deploy`
3. Monitor closely for first few hours
4. Be ready to rollback if needed

### Strategy 3: Blue-Green Deployment

1. Deploy new controller in parallel namespace
2. Route new ScanInstances to new controller
3. Gradually migrate existing scans
4. Decommission old controller

## Post-Migration Checklist

- [ ] Controller deployment updated with new image
- [ ] `SCAN_JOB_TIMEOUT_SECONDS` environment variable set (if needed)
- [ ] Controller pod is running
- [ ] No unexpected timeout events
- [ ] Active scan jobs complete successfully
- [ ] Verification script passes
- [ ] Documentation reviewed by team
- [ ] Monitoring alerts updated (if any)

## Support Resources

- **Quick Reference**: `SCAN_JOB_TIMEOUT_QUICK_REF.md`
- **Full Documentation**: `SCAN_JOB_TIMEOUT_CONFIG.md`
- **Implementation Details**: `SCAN_JOB_TIMEOUT_IMPLEMENTATION_SUMMARY.md`
- **Verification Script**: `verify_scan_job_timeout.sh`

## FAQ

**Q: Do I need to restart existing scan jobs?**
A: No, the timeout applies to new scan jobs. Existing jobs continue with their original timeout.

**Q: Will this affect pre-scan or validation jobs?**
A: No, only scan jobs use the configurable timeout. Pre-scan and validation jobs keep the fixed 15-minute timeout.

**Q: Can I set different timeouts for different ScanInstances?**
A: Not currently. The timeout is global for all scan jobs. This is a potential future enhancement.

**Q: What happens if I set an invalid timeout value?**
A: The controller will use the default value (1500 seconds) and continue operating normally.

**Q: Do I need to rebuild my scanner image?**
A: No, only the controller image needs to be updated. Scanner images are unchanged.

## Contact

For issues or questions about this migration:
1. Check the troubleshooting section above
2. Review the comprehensive documentation
3. Run the verification script for diagnostics
4. Check Kubernetes events and logs
