# Webhook Configuration

This directory contains Kubernetes webhook configurations for the Threat Scanning Architecture.

## Overview

The threat scanning system uses admission webhooks to validate and mutate Target and ScanInstance resources before they are persisted to etcd. This ensures data integrity and enforces business rules at the API level.

## Files

### Webhook Configurations

- **`validating_webhook_configuration.yaml`**: Validating webhook definitions
  - Target validation (CREATE, UPDATE, DELETE)
  - ScanInstance validation (CREATE, UPDATE, DELETE)

- **`mutating_webhook_configuration.yaml`**: Mutating webhook definitions
  - Target mutation (CREATE)
  - ScanInstance mutation (CREATE)

- **`service.yaml`**: Kubernetes Service exposing the webhook server
  - Listens on port 443
  - Routes to manager pod on port 9443

### Kustomize Configuration

- **`kustomization.yaml`**: Main kustomization file for webhook resources
- **`kustomizeconfig.yaml`**: Custom transformations for webhook configurations

## Webhook Endpoints

### Target Webhooks

| Type | Endpoint | Operations |
|------|----------|------------|
| Validating | `/validate-threatscanning-trilio-io-v1-target` | CREATE, UPDATE, DELETE |
| Mutating | `/mutate-threatscanning-trilio-io-v1-target` | CREATE |

### ScanInstance Webhooks

| Type | Endpoint | Operations |
|------|----------|------------|
| Validating | `/validate-threatscanning-trilio-io-v1-scaninstance` | CREATE, UPDATE, DELETE |
| Mutating | `/mutate-threatscanning-trilio-io-v1-scaninstance` | CREATE |

## Deployment

### Prerequisites

1. **TLS Certificates**: Generate certificates for the webhook server
   ```bash
   ../../hack/generate-webhook-certs.sh
   ```

2. **Create TLS Secret**:
   ```bash
   kubectl create secret tls threat-scanning-webhook-certs \
     --cert=certs/tls.crt \
     --key=certs/tls.key \
     -n threat-scanning-system
   ```

3. **Update CA Bundle**: Inject CA certificate into webhook configurations
   ```bash
   export CA_BUNDLE=$(cat certs/ca.crt | base64 | tr -d '\n')
   
   # Update validating webhook
   kubectl patch validatingwebhookconfiguration \
     threat-scanning-validating-webhook-configuration \
     --type='json' \
     -p="[{'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'},
         {'op': 'add', 'path': '/webhooks/1/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}]"
   
   # Update mutating webhook
   kubectl patch mutatingwebhookconfiguration \
     threat-scanning-mutating-webhook-configuration \
     --type='json' \
     -p="[{'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'},
         {'op': 'add', 'path': '/webhooks/1/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}]"
   ```

### Deploy Webhook Configurations

```bash
kubectl apply -k .
```

This will create:
- ValidatingWebhookConfiguration
- MutatingWebhookConfiguration
- Service for webhook server

### Verify Deployment

```bash
# Check webhook configurations
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration
kubectl get mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration

# Check webhook service
kubectl get svc -n threat-scanning-system threat-scanning-webhook-service

# Check manager pod (should be running with webhooks enabled)
kubectl get pods -n threat-scanning-system
```

## Configuration

### Failure Policy

Both validating and mutating webhooks use `failurePolicy: Fail`. This means:
- If the webhook server is unavailable, API requests will be rejected
- Ensures no invalid resources are created
- For production, consider using `Ignore` policy for non-critical validations

### Side Effects

All webhooks declare `sideEffects: None`, indicating they:
- Do not cause side effects beyond validation/mutation
- Are safe to call multiple times with the same input
- Do not modify external state

### Admission Review Versions

All webhooks support admission review version `v1`:
```yaml
admissionReviewVersions:
  - v1
```

## Webhook Logic

### Target Validations

**CREATE**:
- Validate credential fields based on type (NFS/ObjectStore)
- Require explicit namespace for credential secret
- Verify referenced resources exist (secrets, configmaps)
- Enforce single available reporting target constraint
- Validate URL format for non-cloud vendors

**UPDATE**:
- All CREATE validations apply
- Block spec updates if target referenced by active scans
- Prevent conversion to reporting target
- Validate reporting target uniqueness

**DELETE**:
- Block deletion if referenced by active/queued scans

### Target Mutations

**CREATE**:
- Set default vendor to "Other" for non-cloud ObjectStore
- Set default `skipCertVerification` to false

### ScanInstance Validations

**CREATE**:
- Validate backup path is not empty
- Verify referenced target exists and is available
- Check target has completed validation

**UPDATE**:
- Enforce spec immutability
- Validate logical status transitions

**DELETE**:
- Allow deletion with warning if scan is in progress

### ScanInstance Mutations

**CREATE**:
- Auto-populate `backupTarget.apiVersion`
- Auto-populate `backupTarget.kind`

## Troubleshooting

### Webhook Not Responding

**Symptoms**:
- Timeout errors when creating resources
- "connection refused" errors

**Solutions**:
1. Check manager pod is running:
   ```bash
   kubectl get pods -n threat-scanning-system
   ```

2. Check manager is started with webhooks enabled:
   ```bash
   kubectl logs -n threat-scanning-system <manager-pod> | grep webhook
   ```

3. Verify webhook service exists:
   ```bash
   kubectl get svc -n threat-scanning-system threat-scanning-webhook-service
   ```

### Certificate Errors

**Symptoms**:
- x509 certificate validation errors
- TLS handshake failures

**Solutions**:
1. Verify CA bundle is set in webhook configurations:
   ```bash
   kubectl get validatingwebhookconfiguration \
     threat-scanning-validating-webhook-configuration \
     -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | base64 -d | openssl x509 -text
   ```

2. Check certificate expiration:
   ```bash
   kubectl get secret threat-scanning-webhook-certs \
     -n threat-scanning-system \
     -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -enddate -noout
   ```

3. Regenerate certificates if expired:
   ```bash
   ../../hack/generate-webhook-certs.sh
   # Then recreate the secret and update CA bundles
   ```

### Webhook Not Called

**Symptoms**:
- Resources created without validation
- Mutations not applied

**Solutions**:
1. Check webhook configurations are registered:
   ```bash
   kubectl get validatingwebhookconfigurations | grep threat-scanning
   kubectl get mutatingwebhookconfigurations | grep threat-scanning
   ```

2. Verify webhook rules match your resources:
   ```bash
   kubectl get validatingwebhookconfiguration \
     threat-scanning-validating-webhook-configuration -o yaml
   ```

3. Check failure policy:
   ```bash
   kubectl get validatingwebhookconfiguration \
     threat-scanning-validating-webhook-configuration \
     -o jsonpath='{.webhooks[*].failurePolicy}'
   ```

## Security Considerations

### TLS Certificates

- **Development**: Use self-signed certificates generated by `hack/generate-webhook-certs.sh`
- **Production**: Use cert-manager or your organization's PKI for certificate management

### RBAC

The webhook service account needs:
- Read access to Secrets (to validate credential secrets)
- Read access to ConfigMaps (to validate SSL cert configmaps)
- Read access to Targets (for validation)
- Read access to ScanInstances (for validation)

### Network Policy

Consider network policies to:
- Allow API server to webhook service (port 9443)
- Deny direct access to webhook from other pods

## Monitoring

### Metrics

The webhook server exposes metrics at `/metrics`:
- `webhook_validation_total`: Total validations performed
- `webhook_validation_errors_total`: Total validation errors
- `webhook_mutation_total`: Total mutations performed
- `webhook_duration_seconds`: Webhook processing duration

### Logging

Webhook operations are logged with structured logging:
```bash
kubectl logs -n threat-scanning-system <manager-pod> | grep webhook
```

## Testing

For comprehensive testing instructions, see:
- `../../WEBHOOK_QUICK_TEST_GUIDE.md` - Quick test scenarios
- `../../WEBHOOK_IMPLEMENTATION.md` - Full implementation details

Quick test:
```bash
# Test validation (should fail - no namespace)
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
      # namespace missing - should fail
EOF
```

## Additional Resources

- **Implementation Guide**: `../../WEBHOOK_IMPLEMENTATION.md`
- **Quick Test Guide**: `../../WEBHOOK_QUICK_TEST_GUIDE.md`
- **Implementation Summary**: `../../WEBHOOK_IMPLEMENTATION_SUMMARY.md`
- **Cert Generation Script**: `../../hack/generate-webhook-certs.sh`

## SupportFor issues or questions:
1. Check the troubleshooting section above
2. Review webhook logs
3. Consult the implementation documentation
4. Check Kubernetes admission webhook documentation
