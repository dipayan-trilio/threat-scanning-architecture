# Testing Guide: Enhanced Validation with Pod Status Checking

## Quick Start

### Prerequisites

1. **Create the namespace**:
```bash
kubectl create namespace threat-scanning-system
```

2. **Build the controller**:
```bash
cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture
make build
```

3. **Run the controller**:
```bash
make run
```

## Test Scenario 1: Successful Validation (Default)

### Expected Behavior
- Validation job runs `sleep 60` 
- Pod completes successfully after 60 seconds
- Target status changes: `InProgress` → `Available`

### Steps

```bash
# 1. Apply a target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# 2. Watch target status
watch kubectl get target test-s3-target

# Expected output (first 60 seconds):
# NAME             TYPE          VENDOR   STATUS       AGE
# test-s3-target   ObjectStore   AWS      InProgress   10s

# 3. Check the validation job
kubectl get jobs -n threat-scanning-system

# Expected:
# NAME                                      COMPLETIONS   DURATION   AGE
# threat-scan-target-validation-<hash>      0/1           30s        30s

# 4. Check the pod
kubectl get pods -n threat-scanning-system -l trilio.io/component=target-validator

# Expected (while running):
# NAME                                          READY   STATUS    RESTARTS   AGE
# threat-scan-target-validation-<hash>-<xxx>    1/1     Running   0          30s

# 5. Check pod logs
kubectl logs -n threat-scanning-system -l trilio.io/component=target-validator

# Expected output:
# Starting validation for target: test-s3-target
# (60 seconds later)
# Validation completed successfully

# 6. After ~65 seconds, check target status again
kubectl get target test-s3-target -o yaml | grep -A 5 status:

# Expected:
# status:
#   status: Available
#   conditions:
#   - type: Validation
#     status: Succeeded
```

### Controller Logs

```
INFO	Creating a new validation job: threat-scan-target-validation-<hash>
DEBUG	Found target validation job with name: threat-scan-target-validation-<hash> and status: InProgress
INFO	Target test-s3-target validation state: InProgress
DEBUG	Found target validation job with name: threat-scan-target-validation-<hash> and status: Completed
DEBUG	Target status updated to: Available
INFO	Target test-s3-target validation state: Succeeded
```

## Test Scenario 2: Failed Validation (Invalid Image)

### Expected Behavior
- Validation job tries to pull invalid image
- Pod enters `ImagePullBackOff` state
- Controller detects error **immediately**
- Target status: `Unavailable`

### Steps

```bash
# 1. Set invalid image
export RELATED_IMAGE_VALIDATOR="invalid-registry/nonexistent-image:v999"

# 2. Stop and restart controller
# (Ctrl+C to stop, then `make run` to restart with new env var)

# 3. Apply target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# 4. Watch pod status
watch kubectl get pods -n threat-scanning-system -l trilio.io/component=target-validator

# Expected (within 30 seconds):
# NAME                                          READY   STATUS             RESTARTS   AGE
# threat-scan-target-validation-<hash>-<xxx>    0/1     ImagePullBackOff   0          25s

# 5. Check target status
kubectl get target test-s3-target -o jsonpath='{.status.status}'

# Expected:
# Unavailable

# 6. Check target conditions
kubectl get target test-s3-target -o jsonpath='{.status.conditions}' | jq

# Expected:
# [
#   {
#     "type": "Validation",
#     "status": "Failed",
#     "reason": "ValidationFailed"
#   }
# ]

# 7. Describe the pod to see the error
kubectl describe pod -n threat-scanning-system -l trilio.io/component=target-validator

# Expected in Events:
# Warning  Failed     25s   kubelet  Failed to pull image "invalid-registry/nonexistent-image:v999"
# Warning  Failed     25s   kubelet  Error: ImagePullBackOff
```

### Controller Logs

```
INFO	Creating a new validation job: threat-scan-target-validation-<hash>
DEBUG	Found target validation job with name: threat-scan-target-validation-<hash> and status: Failed
INFO	Target test-s3-target validation state: Failed
DEBUG	Target status updated to: Unavailable
```

## Test Scenario 3: Container Crash (Exit Code ≠ 0)

### Expected Behavior
- Container exits with non-zero exit code
- Controller detects failure from exit code
- Target status: `Unavailable`

### Steps

This requires modifying the code temporarily:

```go
// In pkg/helpers/job_helper.go, change:
validationCmd = "echo 'Starting validation' && exit 1"  // Force exit with error
```

```bash
# 1. Rebuild controller
make build

# 2. Run controller
make run

# 3. Apply target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# 4. Watch pod
kubectl get pods -n threat-scanning-system -l trilio.io/component=target-validator -w

# Expected:
# threat-scan-target-validation-<hash>-<xxx>   0/1   ContainerCreating  0     1s
# threat-scan-target-validation-<hash>-<xxx>   0/1   Error              0     3s
# threat-scan-target-validation-<hash>-<xxx>   0/1   Completed          0     4s

# 5. Check target status
kubectl get target test-s3-target -o jsonpath='{.status.status}'

# Expected:
# Unavailable

# 6. Check pod exit code
kubectl get pod -n threat-scanning-system -l trilio.io/component=target-validator -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.exitCode}'

# Expected:
# 1
```

### Controller Logs

```
INFO	Creating a new validation job: threat-scan-target-validation-<hash>
DEBUG	Found target validation job with name: threat-scan-target-validation-<hash> and status: Failed
INFO	Target test-s3-target validation state: Failed
DEBUG	Target status updated to: Unavailable
```

## Test Scenario 4: CrashLoopBackOff

### Expected Behavior
- Container crashes repeatedly
- Kubernetes puts it in `CrashLoopBackOff`
- Controller detects the crash loop
- Target status: `Unavailable`

### Steps

Modify the validation command to crash:

```go
// In pkg/helpers/job_helper.go:
validationCmd = "while true; do echo 'Crashing...'; sleep 1; exit 1; done"
```

```bash
# 1. Rebuild and run
make build && make run

# 2. Apply target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# 3. Watch pod status
watch kubectl get pods -n threat-scanning-system -l trilio.io/component=target-validator

# Expected progression:
# 0-5s:   Running
# 5-10s:  Error
# 10-20s: CrashLoopBackOff
# 20s+:   CrashLoopBackOff (with increasing backoff)

# 4. Check target status
kubectl get target test-s3-target -o jsonpath='{.status.status}'

# Expected (once CrashLoopBackOff is detected):
# Unavailable
```

## Test Scenario 5: NFS Target Validation

### Expected Behavior
- NFS mount created
- Validation runs `sleep 60`
- Target becomes `Available`

### Steps

```bash
# 1. Create NFS target sample (if not exists)
cat > config/samples/threatscanning_v1_target_nfs.yaml <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-nfs-target
spec:
  type: NFS
  vendor: Other
  nfsCredentials:
    nfsExport: "192.168.1.100:/exports/backups"
EOF

# 2. Apply target
kubectl apply -f config/samples/threatscanning_v1_target_nfs.yaml

# 3. Check NFS PV and PVC
kubectl get pv,pvc -n threat-scanning-system | grep nfs

# Expected:
# persistentvolume/threat-scan-target-nfs-pv-<hash>    10Gi   RWX  Retain  Bound  threat-scanning-system/threat-scan-target-nfs-pvc-<hash>
# persistentvolumeclaim/threat-scan-target-nfs-pvc-<hash>   Bound   threat-scan-target-nfs-pv-<hash>   10Gi   RWX

# 4. Check validation job
kubectl get jobs -n threat-scanning-system

# 5. Wait for target to become available
kubectl get target test-nfs-target -w
```

## Test Scenario 6: Poller CronJob Creation

### Expected Behavior
- After target becomes `Available`
- If target is **not** a reporting target
- Poller cronjob is created

### Steps

```bash
# 1. Apply a non-reporting target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# 2. Wait for target to become Available
kubectl wait --for=jsonpath='{.status.status}'=Available target/test-s3-target --timeout=120s

# 3. Check for poller cronjob
kubectl get cronjobs -n threat-scanning-system

# Expected:
# NAME                              SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
# test-s3-target-poller-<random>    0 */6 * * *   False     0        <none>          5s

# 4. Check cronjob details
kubectl get cronjob -n threat-scanning-system -o yaml | grep -A 10 spec:

# Expected schedule:
# schedule: "0 */6 * * *"  # Every 6 hours (default)

# 5. Check cronjob labels
kubectl get cronjob -n threat-scanning-system -o jsonpath='{.items[0].metadata.labels}' | jq

# Expected:
# {
#   "trilio.io/component": "target-poller",
#   "trilio.io/managed-by": "threat-scanning-controller",
#   "trilio.io/resource-creator-kind": "Target",
#   "trilio.io/target-name": "test-s3-target"
# }
```

## Cleanup

### Remove a Target

```bash
# Delete target
kubectl delete target test-s3-target

# Verify cleanup
kubectl get jobs,cronjobs,pv,pvc -n threat-scanning-system

# Expected: No resources (all cleaned up by controller)
```

### Reset Environment

```bash
# Delete namespace
kubectl delete namespace threat-scanning-system

# Recreate namespace
kubectl create namespace threat-scanning-system

# Restart controller
make run
```

## Environment Variables Testing

### Test Custom Namespace

```bash
# 1. Create custom namespace
kubectl create namespace my-threat-scan

# 2. Set environment variable
export INSTALL_NAMESPACE="my-threat-scan"

# 3. Run controller
make run

# 4. Apply target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# 5. Verify resources in custom namespace
kubectl get jobs,cronjobs -n my-threat-scan

# Expected: Jobs and cronjobs created in my-threat-scan
```

### Test Custom Validator Image

```bash
# 1. Set custom image
export RELATED_IMAGE_VALIDATOR="busybox:1.35"

# 2. Restart controller
make run

# 3. Apply target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# 4. Check pod image
kubectl get pod -n threat-scanning-system -l trilio.io/component=target-validator -o jsonpath='{.items[0].spec.containers[0].image}'

# Expected:
# busybox:1.35
```

### Test Custom Poller Schedule

```bash
# 1. Set custom schedule (every 4 hours)
export POLLER_SCHEDULE="0 */4 * * *"

# 2. Restart controller
make run

# 3. Apply target and wait for Available
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml
kubectl wait --for=jsonpath='{.status.status}'=Available target/test-s3-target --timeout=120s

# 4. Check cronjob schedule
kubectl get cronjob -n threat-scanning-system -o jsonpath='{.items[0].spec.schedule}'

# Expected:
# 0 */4 * * *
```

## Debugging Tips

### Check Controller Logs

```bash
# If running with make run, logs appear in terminal

# If running as deployment:
kubectl logs -n threat-scanning-system deployment/threat-scanning-controller -f
```

### Check Target Events

```bash
kubectl describe target test-s3-target

# Look for Events section:
# Events:
#   Type    Reason              Message
#   ----    ------              -------
#   Normal  JobCreateSuccess    Target validation job threat-scan-target-validation-<hash> created
#   Normal  ValidationFailed    Target test-s3-target validation state: Failed
```

### Check Validation ConfigMap

```bash
kubectl get configmap threat-scan-target-validation-config -n threat-scanning-system -o yaml

# Shows cached validation results:
# data:
#   <credential-hash>: "Succeeded"  # or "Failed"
```

### Force Re-validation

```bash
# Update target spec to trigger re-validation
kubectl patch target test-s3-target --type=merge -p '{"spec":{"objectStoreCredentials":{"region":"us-west-2"}}}'

# This creates a new credential hash, triggering new validation job
```

## Common Issues

### Issue: "namespaces 'threat-scanning-system' not found"

**Solution**: Create the namespace first
```bash
kubectl create namespace threat-scanning-system
```

### Issue: Jobs not being created

**Check**:
```bash
# 1. Controller logs for errors
# 2. RBAC permissions
kubectl auth can-i create jobs --as=system:serviceaccount:threat-scanning-system:threat-scanning-controller -n threat-scanning-system

# Expected: yes
```

### Issue: Target stuck in InProgress

**Debug**:
```bash
# Check job status
kubectl get jobs -n threat-scanning-system

# Check pod status
kubectl get pods -n threat-scanning-system -l trilio.io/component=target-validator

# Check pod logs
kubectl logs -n threat-scanning-system -l trilio.io/component=target-validator

# Check pod events
kubectl describe pod -n threat-scanning-system -l trilio.io/component=target-validator
```

### Issue: Poller cronjob not created

**Check**:
```bash
# 1. Is target Available?
kubectl get target <target-name> -o jsonpath='{.status.status}'

# 2. Is it a reporting target?
kubectl get target <target-name> -o jsonpath='{.spec.reporting}'

# 3. Check controller logs for errors
```

## Summary

✅ Test successful validation (sleep 60)  
✅ Test failed validation (ImagePullBackOff)  
✅ Test container crashes (exit code ≠ 0)  
✅ Test CrashLoopBackOff detection  
✅ Test NFS target validation  
✅ Test poller cronjob creation  
✅ Test environment variable configuration  

All tests verify that the controller properly detects pod states and sets target status to `Available` or `Unavailable` based on actual pod conditions!

