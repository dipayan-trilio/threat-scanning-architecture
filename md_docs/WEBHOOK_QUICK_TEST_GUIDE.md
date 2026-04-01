# Webhook Quick Test Guide

This guide provides quick commands to test the admission webhooks.

## Prerequisites

1. Webhooks are deployed and running
2. Manager is running with `--enable-webhook=true`
3. Webhook certificates are properly configured

## Test Scenarios

### Target Validation Tests

#### Test 1: Missing Namespace in Credential Secret (Should FAIL)
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-fail-no-namespace
spec:
  type: ObjectStore
  vendor: MinIO
  targetType: TVK
  objectStoreCredentials:
    url: http://minio.minio-system.svc:9000
    bucketName: test-bucket
    credentialSecret:
      name: minio-creds
      # Missing namespace - should fail
EOF
```

**Expected**: Admission webhook denies with error about missing namespace

#### Test 2: Non-existent Secret (Should FAIL)
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-fail-no-secret
spec:
  type: ObjectStore
  vendor: MinIO
  targetType: TVK
  objectStoreCredentials:
    url: http://minio.minio-system.svc:9000
    bucketName: test-bucket
    credentialSecret:
      name: non-existent-secret
      namespace: default
EOF
```

**Expected**: Admission webhook denies with error about secret not found

#### Test 3: Valid Target (Should SUCCEED)
```bash
# First create the secret
kubectl create secret generic test-minio-creds \
  --from-literal=accessKey=minioadmin \
  --from-literal=secretKey=minioadmin \
  -n default

# Then create the target
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-valid-target
spec:
  type: ObjectStore
  vendor: MinIO
  targetType: TVK
  objectStoreCredentials:
    url: http://minio.minio-system.svc:9000
    bucketName: test-bucket
    credentialSecret:
      name: test-minio-creds
      namespace: default
EOF
```

**Expected**: Target created successfully

#### Test 4: Second Reporting Target (Should FAIL)
```bash
# Assume one reporting target already exists and is Available
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-second-reporting
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  vendor: MinIO
  objectStoreCredentials:
    url: http://minio.minio-system.svc:9000
    bucketName: reports
    credentialSecret:
      name: test-minio-creds
      namespace: default
EOF
```

**Expected**: Admission webhook denies with error about existing reporting target

#### Test 5: Update Target Spec with Active Scan (Should FAIL)
```bash
# First create a target
kubectl apply -f config/samples/minio-target.yaml

# Create a scan instance referencing this target
kubectl apply -f config/samples/scaninstance.yaml

# Try to update the target spec while scan is active
kubectl patch target minio-target --type='json' -p='[{"op": "replace", "path": "/spec/vendor", "value": "AWS"}]'
```

**Expected**: Admission webhook denies with error about active scan instances

### ScanInstance Validation Tests

#### Test 6: Non-existent Target (Should FAIL)
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-fail-no-target
spec:
  backupTarget:
    name: non-existent-target
  backupRef:
    path: /backup/path
EOF
```

**Expected**: Admission webhook denies with error about target not found

#### Test 7: Empty Backup Path (Should FAIL)
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-fail-empty-path
spec:
  backupTarget:
    name: test-valid-target
  backupRef:
    path: ""
EOF
```

**Expected**: Admission webhook denies with error about empty backup path

#### Test 8: Target Not Available (Should FAIL)
```bash
# Assuming test-valid-target is not Available yet (validation not completed)
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-fail-target-unavailable
spec:
  backupTarget:
    name: test-valid-target
  backupRef:
    path: /backup/path
EOF
```

**Expected**: Admission webhook denies with error about target not available

#### Test 9: Valid ScanInstance (Should SUCCEED)
```bash
# Assuming test-valid-target is Available
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-valid-scaninstance
spec:
  backupTarget:
    name: test-valid-target
  backupRef:
    path: /backup/test/path
EOF
```

**Expected**: ScanInstance created successfully with auto-populated apiVersion and kind

#### Test 10: Duplicate ScanInstance (Should SUCCEED - Rescan)
```bash
# Create another ScanInstance for the same backup
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-rescan-scaninstance
spec:
  backupTarget:
    name: test-valid-target
  backupRef:
    path: /backup/test/path  # Same path as Test 9
EOF
```

**Expected**: ScanInstance created successfully (rescans are allowed)

#### Test 11: Update ScanInstance Spec (Should FAIL)
```bash
# Try to update the spec after creation
kubectl patch scaninstance test-valid-scaninstance --type='json' \
  -p='[{"op": "replace", "path": "/spec/backupRef/path", "value": "/new/path"}]'
```

**Expected**: Admission webhook denies with error about spec immutability

#### Test 12: Invalid Status Transition (Should FAIL)
```bash
# Assuming scan is Completed, try to set it back to Queued
kubectl patch scaninstance test-valid-scaninstance --type='json' \
  -p='[{"op": "replace", "path": "/status/status", "value": "Queued"}]'
```

**Expected**: Admission webhook denies with error about invalid status transition

#### Test 13: Delete InProgress ScanInstance (Should SUCCEED with Warning)
```bash
# Assuming scan is InProgress
kubectl delete scaninstance test-valid-scaninstance
```

**Expected**: ScanInstance deleted with warning message about InProgress status

## Mutation Tests

### Test 14: Auto-populate BackupTarget Reference
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-auto-populate
spec:
  backupTarget:
    name: test-valid-target
    # apiVersion and kind not specified
  backupRef:
    path: /backup/path
EOF

# Verify the mutation
kubectl get scaninstance test-auto-populate -o yaml | grep -A 3 backupTarget
```

**Expected**: 
- `apiVersion: threatscanning.trilio.io/v1`
- `kind: Target`

### Test 15: Default Vendor for Target
```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-default-vendor
spec:
  type: ObjectStore
  targetType: TVK
  # vendor not specified
  objectStoreCredentials:
    url: http://minio.local:9000
    bucketName: test
    credentialSecret:
      name: test-minio-creds
      namespace: default
EOF

# Verify the mutation
kubectl get target test-default-vendor -o yaml | grep vendor
```

**Expected**: `vendor: Other`

## Cleanup

```bash
# Delete test resources
kubectl delete scaninstance test-valid-scaninstance test-rescan-scaninstance test-auto-populate --ignore-not-found
kubectl delete target test-valid-target test-default-vendor --ignore-not-found
kubectl delete secret test-minio-creds -n default --ignore-not-found
```

## Debugging

### Check Webhook Logs
```bash
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning-controller --tail=100
```

### Check Webhook Configuration
```bash
# Check validating webhooks
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration -o yaml

# Check mutating webhooks
kubectl get mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration -o yaml

# Check webhook service
kubectl get svc -n threat-scanning-system threat-scanning-webhook-service
```

### Verify Certificates
```bash
# Check if secret exists
kubectl get secret threat-scanning-webhook-certs -n threat-scanning-system

# Verify certificate
kubectl get secret threat-scanning-webhook-certs -n threat-scanning-system -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout
```

### Test Webhook Connectivity
```bash
# Port-forward to webhook service
kubectl port-forward -n threat-scanning-system svc/threat-scanning-webhook-service 9443:443

# In another terminal, test connectivity (self-signed cert warning is expected)
curl -k https://localhost:9443/validate-threatscanning-trilio-io-v1-target
```

## Common Issues

### Issue 1: Connection Refused
**Symptom**: `connection refused` when creating resources

**Solution**:
- Check manager pod is running: `kubectl get pods -n threat-scanning-system`
- Check webhook service exists: `kubectl get svc -n threat-scanning-system`
- Check manager is started with `--enable-webhook=true`

### Issue 2: x509 Certificate Error
**Symptom**: x509 certificate validation errors

**Solution**:
- Verify CA bundle is set in webhook configurations
- Regenerate certificates if expired
- Ensure certificate SANs match service DNS name

### Issue 3: Webhook Not Called
**Symptom**: Resources created without validation

**Solution**:
- Check webhook configurations are deployed
- Verify webhook rules match resource operations
- Check failure policy is set to `Fail`
