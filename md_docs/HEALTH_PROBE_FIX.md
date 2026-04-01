# Health Probe Fix - Deployment Guide

## What Was Fixed

### Issue
Pod was not reaching Ready state because health probes were failing.

### Root Cause
1. Controller-runtime binds health probes to `localhost` by default
2. Kubernetes probes can't reach `localhost` from outside the container
3. Probes were too aggressive (short delays)

### Solution
1. **Bound health probes to all interfaces**: `HealthProbeBindAddress: ":8081"`
2. **Increased probe delays**:
   - Liveness: 30s initial delay (was 15s)
   - Readiness: 10s initial delay (was 5s)
   - Added timeouts and failure thresholds

## Changes Made

### 1. Manager Configuration (`cmd/manager/main.go`)

```go
mgrOptions := ctrl.Options{
    Scheme:                 scheme,
    LeaderElection:         enableLeaderElection,
    LeaderElectionID:       "target-controller-leader-election",
    HealthProbeBindAddress: ":8081", // ← Bind to all interfaces
}
```

### 2. Deployment Probes (`config/webhook/deployment.yaml`)

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8081
  initialDelaySeconds: 30      # ← Increased from 15s
  periodSeconds: 20
  timeoutSeconds: 5            # ← Added timeout
  failureThreshold: 3          # ← Added failure threshold

readinessProbe:
  httpGet:
    path: /readyz
    port: 8081
  initialDelaySeconds: 10      # ← Increased from 5s
  periodSeconds: 10
  timeoutSeconds: 5            # ← Added timeout
  failureThreshold: 3          # ← Added failure threshold
```

## Deployment Steps

### Quick Deploy

```bash
# 1. Build the image with the fix
export IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest
make docker-build docker-push IMG=${IMG}

# 2. Deploy everything
./deploy-webhook.sh

# Or manually:
kubectl apply -f config/crd/bases
kubectl apply -f config/rbac/
kubectl apply -f config/webhook/manifests-no-cert-manager.yaml
```

### Watch Deployment

```bash
# Watch pod creation
kubectl get pods -n threat-scanning-system -w

# Check init container logs (certificate generation)
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c webhook-cert-init -f

# Check main container logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c manager -f

# Check pod events
kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning
```

## Verify Health Probes

### Check Pod Status

```bash
# Should show 1/1 READY
kubectl get pods -n threat-scanning-system
```

Expected output:
```
NAME                                         READY   STATUS    RESTARTS   AGE
threat-scanning-controller-xxxxx-xxxxx      1/1     Running   0          2m
```

### Test Health Endpoints Directly

```bash
# Port-forward to test locally
kubectl port-forward -n threat-scanning-system deployment/threat-scanning-controller 8081:8081

# In another terminal, test health endpoint
curl http://localhost:8081/healthz
curl http://localhost:8081/readyz
```

Both should return: `ok`

### Check Service Endpoints

```bash
# Service should have endpoints
kubectl get svc -n threat-scanning-system threat-scanning-webhook-service
kubectl get endpoints -n threat-scanning-system threat-scanning-webhook-service
```

Expected output:
```
NAME                               ENDPOINTS          AGE
threat-scanning-webhook-service    10.244.0.5:9443    2m
```

## Troubleshooting

### Pod Still Not Ready

```bash
# 1. Check pod status
kubectl get pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning

# 2. Check events
kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning | grep -A 20 Events

# 3. Check readiness probe
kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning | grep -A 5 Readiness

# 4. Check logs for errors
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c manager --tail=50
```

### Init Container Fails

```bash
# Check init container logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c webhook-cert-init

# Common issues:
# - RBAC permissions missing
# - Webhook configurations don't exist
# - Namespace doesn't exist
```

### Health Probe Returns 404

```bash
# Port-forward and test
kubectl port-forward -n threat-scanning-system deployment/threat-scanning-controller 8081:8081
curl -v http://localhost:8081/healthz

# If 404, check:
# 1. Manager is binding to correct port
# 2. Health checks are registered
# 3. No port conflicts
```

### CrashLoopBackOff

```bash
# Check why it's crashing
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c manager --previous

# Common causes:
# - Certificate secret missing (init container should create it)
# - RBAC permissions issue
# - Configuration error
```

## Testing the Webhook

Once pod is Ready and Running:

```bash
# This should be denied by webhook
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-target
spec:
  type: ObjectStore
  vendor: MinIO
  targetType: TVK
  objectStoreCredentials:
    bucketName: test
    credentialSecret:
      name: test-secret
      # namespace missing - webhook should deny
EOF
```

Expected:
```
Error from server: admission webhook "vtarget.threatscanning.trilio.io" denied the request: 
[spec.objectStoreCredentials.credentialSecret.namespace] namespace must be specified for credential secret (target is cluster-scoped)
```

## Quick Status Check Script

```bash
#!/bin/bash
echo "=== Pod Status ==="
kubectl get pods -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning

echo -e "\n=== Service and Endpoints ==="
kubectl get svc,endpoints -n threat-scanning-system threat-scanning-webhook-service

echo -e "\n=== Certificate Secret ==="
kubectl get secret threat-scanning-webhook-certs -n threat-scanning-system

echo -e "\n=== Webhook Configurations ==="
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration
kubectl get mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration

echo -e "\n=== Recent Pod Events ==="
kubectl get events -n threat-scanning-system --sort-by='.lastTimestamp' | grep threat-scanning | tail -10
```

## Next Steps After Deployment

1. **Verify pod is Running and Ready**:
   ```bash
   kubectl get pods -n threat-scanning-system
   ```

2. **Check certificate was created**:
   ```bash
   kubectl get secret threat-scanning-webhook-certs -n threat-scanning-system
   ```

3. **Verify CA bundle was injected**:
   ```bash
   kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | base64 -d | openssl x509 -text -noout | head -20
   ```

4. **Test webhooks**:
   ```bash
   # See WEBHOOK_QUICK_TEST_GUIDE.md for test scenarios
   ```

## Summary

The health probe fix ensures:
- ✅ Probes can reach the container from Kubernetes
- ✅ Enough time for init container to complete
- ✅ Enough time for webhook server to start
- ✅ Proper timeouts and failure thresholds
- ✅ Pod reaches Ready state

Now rebuild and redeploy:
```bash
./deploy-webhook.sh --build
```
