# Admission Webhooks Implementation

This document describes the admission webhooks implemented for the Threat Scanning Architecture.

## Overview

The threat scanning system uses Kubernetes admission webhooks to validate and mutate Target and ScanInstance resources. This ensures data integrity, prevents invalid configurations, and enforces business rules at the API level.

## Architecture

### Webhook Types

1. **Validating Webhooks**: Validate resource creation, updates, and deletions
2. **Mutating Webhooks**: Apply default values and transformations to resources

### Registered Webhooks

#### Target Webhooks

1. **Validating Webhook**: `/validate-threatscanning-trilio-io-v1-target`
   - Operations: CREATE, UPDATE, DELETE
   - Handler: `target.TargetValidator`

2. **Mutating Webhook**: `/mutate-threatscanning-trilio-io-v1-target`
   - Operations: CREATE
   - Handler: `target.TargetMutator`

#### ScanInstance Webhooks

1. **Validating Webhook**: `/validate-threatscanning-trilio-io-v1-scaninstance`
   - Operations: CREATE, UPDATE, DELETE
   - Handler: `scaninstance.ScanInstanceValidator`

2. **Mutating Webhook**: `/mutate-threatscanning-trilio-io-v1-scaninstance`
   - Operations: CREATE
   - Handler: `scaninstance.ScanInstanceMutator`

## Target Webhooks

### Validating Webhook

#### CREATE Validation

1. **Credential Validation**
   - NFS targets must have `nfsCredentials` specified
   - ObjectStore targets must have `objectStoreCredentials` specified
   - Mutual exclusivity: Cannot specify both NFS and ObjectStore credentials

2. **ObjectStore Specific Validation**
   - `credentialSecret` must be specified
   - `credentialSecret.namespace` must be specified (Target is cluster-scoped)
   - `bucketName` must be specified
   - Credential secret must exist in the specified namespace
   - Credential secret must contain `accessKey` and `secretKey`
   - URL must be specified for non-AWS/Azure vendors
   - URL must be valid (proper scheme and host)

3. **SSL Certificate Validation**
   - If `sslCertConfig` is provided:
     - `certKey` must be specified
     - `certConfigMap` reference must be specified
     - `certConfigMap.namespace` must be specified
     - ConfigMap must exist in the specified namespace
     - ConfigMap must contain the specified `certKey`

4. **Reporting Target Validation**
   - Only one Available reporting target is allowed
   - Validation checks for existing reporting targets with status `Available`

5. **Target Type Validation**
   - `targetType` (TVK/TVO) must be specified for non-reporting targets

#### UPDATE Validation

1. **All CREATE validations apply**
2. **Spec Immutability**
   - Spec updates are blocked if target is referenced by active (InProgress or Queued) ScanInstances
   - Status and metadata updates are allowed

3. **Reporting Target Constraint**
   - When converting a target to a reporting target, validates single reporting target constraint

#### DELETE Validation

1. **Active ScanInstance Check**
   - Deletion is blocked if target is referenced by any active (InProgress) or queued (Queued) ScanInstances
   - Deletion is allowed if only Completed or Failed ScanInstances reference the target

### Mutating Webhook

#### CREATE Mutations

1. **Default Vendor**
   - Sets `vendor` to "Other" for non-cloud ObjectStore targets if not specified

2. **Default Skip Cert Verification**
   - Sets `skipCertVerification` to `false` if not specified

**Important**: No secret cloning or namespace mutation is performed. Validation will fail if namespace is not specified.

## ScanInstance Webhooks

### Validating Webhook

#### CREATE Validation

1. **Backup Reference Validation**
   - `backupRef.path` must not be empty

2. **Target Reference Validation**
   - Referenced target must exist
   - Target status must be `Available`
   - Target must have completed validation (`IsValidationCompleted()`)

3. **Duplicate ScanInstances**
   - **Allowed**: Multiple ScanInstances can reference the same backup path and target
   - This enables rescanning of backups

#### UPDATE Validation

1. **Spec Immutability**
   - Spec updates are blocked after creation
   - Only status updates are allowed

2. **Phase Transition Validation**
   - Validates logical status transitions:
     - `Queued` → `InProgress`, `Failed`
     - `InProgress` → `Completed`, `Failed`
     - `Completed` → (terminal state)
     - `Failed` → (terminal state)

#### DELETE Validation

1. **InProgress Warning**
   - If scan is `InProgress`, a warning is returned but deletion is allowed
   - Warning message: "Warning: Deleting scan instance '{name}' which is in progress (status: {status})"

### Mutating Webhook

#### CREATE Mutations

1. **BackupTarget Reference**
   - Auto-populates `backupTarget.apiVersion` to "threatscanning.trilio.io/v1" if not provided
   - Auto-populates `backupTarget.kind` to "Target" if not provided

**Important**: 
- Status initialization is handled by the controller, not the webhook
- Label management is done by the prescan job after mounting the target

## Design Decisions

### Why No Secret Cloning?

Target is cluster-scoped, but credential secrets are namespaced. Rather than auto-cloning secrets or auto-populating namespaces, we require explicit namespace specification. This:
- Makes configuration explicit and clear
- Prevents unexpected behavior
- Ensures security boundaries are explicit

### Why Allow Duplicate ScanInstances?

Allowing multiple ScanInstances for the same backup enables:
- **Rescanning**: Run a new scan on the same backup after updates to scanner
- **Audit Trail**: Keep historical scan results
- **Comparison**: Compare scan results over time

### Why Controller Handles Status Initialization?

Status initialization in the controller (not webhook) ensures:
- Proper state management with error handling
- Consistent status updates with conditions
- Ability to retry on failures
- Better observability through controller logs

### Why Prescan Handles Label Management?

Labels are added by the prescan job because:
- Requires mounting the target to detect backup metadata
- Needs backup detection logic (TVK vs TVO)
- Extracting UIDs and paths requires target access
- Keeps webhook lightweight and fast

## Setup and Configuration

### 1. Generate TLS Certificates

```bash
./hack/generate-webhook-certs.sh
```

This generates self-signed certificates for development. For production, use cert-manager or your organization's PKI.

### 2. Create Kubernetes Secret

```bash
kubectl create secret tls threat-scanning-webhook-certs \
  --cert=config/webhook/certs/tls.crt \
  --key=config/webhook/certs/tls.key \
  -n threat-scanning-system
```

### 3. Update CA Bundle in Webhook Configurations

```bash
export CA_BUNDLE=$(cat config/webhook/certs/ca.crt | base64 | tr -d '\n')

# Update validating webhook configuration
kubectl patch validatingwebhookconfiguration threat-scanning-validating-webhook-configuration \
  --type='json' -p="[{'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}]"

# Update mutating webhook configuration  
kubectl patch mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration \
  --type='json' -p="[{'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}]"
```

### 4. Deploy Webhook Server

```bash
# Build and deploy with webhooks enabled
make docker-build docker-push deploy-webhook
```

### 5. Enable Webhooks in Manager

Start the manager with webhook support:

```bash
./bin/manager --enable-webhook=true --webhook-port=9443
```

## Testing

### Manual Testing

#### Test Target Validation

```bash
# Test 1: Create target without namespace in credentialSecret (should fail)
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-target-fail
spec:
  type: ObjectStore
  vendor: MinIO
  targetType: TVK
  objectStoreCredentials:
    url: http://minio.minio-system.svc:9000
    bucketName: test-bucket
    credentialSecret:
      name: minio-creds
      # namespace not specified - should fail
EOF

# Test 2: Create target with non-existent secret (should fail)
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-target-fail-2
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

# Test 3: Create valid target (should succeed)
kubectl apply -f config/samples/minio-target.yaml
```

#### Test ScanInstance Validation

```bash
# Test 1: Create ScanInstance with non-existent target (should fail)
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-si-fail
spec:
  backupTarget:
    name: non-existent-target
  backupRef:
    path: /test/path
EOF

# Test 2: Create ScanInstance with empty path (should fail)
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-si-fail-2
spec:
  backupTarget:
    name: test-target
  backupRef:
    path: ""
EOF

# Test 3: Create valid ScanInstance (should succeed)
kubectl apply -f config/samples/scaninstance.yaml
```

### Unit Tests

Unit tests should be added in:
- `pkg/webhook/target/target_validator_test.go`
- `pkg/webhook/target/target_mutator_test.go`
- `pkg/webhook/scaninstance/scaninstance_validator_test.go`
- `pkg/webhook/scaninstance/scaninstance_mutator_test.go`

### Integration Tests

Integration tests using envtest should be added to verify:
- Webhook registration and discovery
- Certificate validation
- End-to-end validation flows
- Mutation application

## Troubleshooting

### Common Issues

#### 1. Webhook Not Responding

**Symptom**: Timeout errors when creating resources

**Solution**:
- Check webhook service is running: `kubectl get svc -n threat-scanning-system`
- Check manager pod is running: `kubectl get pods -n threat-scanning-system`
- Check webhook server logs: `kubectl logs -n threat-scanning-system <manager-pod>`

#### 2. Certificate Validation Errors

**Symptom**: x509 certificate errors

**Solution**:
- Verify CA bundle is correctly set in webhook configurations
- Regenerate certificates if expired
- Check certificate SANs match service DNS name

#### 3. Webhook Configuration Not Found

**Symptom**: Webhook not being called

**Solution**:
- Verify webhook configurations are deployed: 
  ```bash
  kubectl get validatingwebhookconfigurations
  kubectl get mutatingwebhookconfigurations
  ```
- Check webhook rules match resource operations

## Monitoring and Observability

### Metrics

The webhook server exposes Prometheus metrics on the `/metrics` endpoint:
- `webhook_validation_total`: Total validations performed
- `webhook_validation_errors_total`: Total validation errors
- `webhook_mutation_total`: Total mutations performed
- `webhook_duration_seconds`: Webhook processing duration

### Logging

Webhook operations are logged with structured logging:
- Validation failures include detailed error messages
- Mutation operations log applied patches
- Performance metrics for slow operations

## Security Considerations

1. **TLS Certificates**: Use cert-manager or proper PKI for production
2. **RBAC**: Webhook service account needs appropriate RBAC permissions
3. **Failure Policy**: Set to `Fail` to prevent invalid resources from being created
4. **Timeout**: Configure appropriate timeout values for webhook calls
5. **Resource Validation**: Always validate referenced resources exist before use

## Future Enhancements

1. **Dry-run Validation**: Support dry-run mode for testing
2. **Audit Logging**: Enhanced audit logging for compliance
3. **Custom Validators**: Plugin architecture for custom validations
4. **Batch Operations**: Optimize validation for batch creates
5. **Caching**: Cache target and secret lookups for performance
