# Webhook Deployment Guide

This guide provides step-by-step instructions to build, dockerize, and deploy the threat-scanning controller with webhooks enabled.

## Prerequisites

1. **Docker** installed and configured
2. **kubectl** configured with access to your cluster
3. **cert-manager** installed in the cluster (for TLS certificate management)
4. **Access to GCR** (Google Container Registry) for pushing images

## Quick Start

### 1. Install cert-manager (if not already installed)

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
```

Wait for cert-manager to be ready:
```bash
kubectl wait --for=condition=Ready pods --all -n cert-manager --timeout=300s
```

### 2. Build and Push Docker Image

Set your environment variables (as provided):
```bash
export RELATED_IMAGE_JANITOR=eu.gcr.io/amazing-chalice-243510/threatscanning/janitor:v1.2
export RELATED_IMAGE_SCANNER=eu.gcr.io/amazing-chalice-243510/threatscanning/scan-engine:v1.6
export RELATED_IMAGE_VALIDATOR='eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v9.5'
export RELATED_IMAGE_POLLER='eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v9.5'
export PRODUCTION=false
export TARGET_POLLING_DISABLED=true
export TARGET_POLLING_CRON="2 * * * *"
export INSTALL_NAMESPACE=default
```

Build the controller image:
```bash
# Set the image name
export IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest

# Build the Docker image
make docker-build IMG=${IMG}

# Push to registry
docker push ${IMG}
```

Or use the shorthand:
```bash
IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest make docker-build docker-push
```

### 3. Install CRDs

```bash
kubectl apply -f config/crd/bases
```

### 4. Create RBAC Resources

```bash
kubectl apply -f config/rbac/service_account.yaml
kubectl apply -f config/rbac/role.yaml
kubectl apply -f config/rbac/role_binding.yaml
kubectl apply -f config/rbac/leader_election_role.yaml
kubectl apply -f config/rbac/leader_election_role_binding.yaml
```

### 5. Deploy Webhook with All Resources

Deploy everything at once:
```bash
kubectl apply -f config/webhook/manifests.yaml
```

This will create:
- Namespace (`threat-scanning-system`)
- Service (`threat-scanning-webhook-service`)
- Cert-manager Issuer and Certificate
- Deployment with webhook enabled
- ValidatingWebhookConfiguration
- MutatingWebhookConfiguration

### 6. Verify Deployment

Check that the certificate is ready:
```bash
kubectl get certificate -n threat-scanning-system
kubectl describe certificate threat-scanning-webhook-cert -n threat-scanning-system
```

Check that the webhook pod is running:
```bash
kubectl get pods -n threat-scanning-system
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -f
```

Check webhook configurations:
```bash
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration
kubectl get mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration
```

## Alternative: Manual Certificate Generation (Without cert-manager)

If you don't want to use cert-manager, you can generate self-signed certificates manually:

### 1. Generate Certificates

```bash
./hack/generate-webhook-certs.sh
```

### 2. Create TLS Secret

```bash
kubectl create namespace threat-scanning-system
kubectl create secret tls threat-scanning-webhook-certs \
  --cert=config/webhook/certs/tls.crt \
  --key=config/webhook/certs/tls.key \
  -n threat-scanning-system
```

### 3. Update CA Bundle in Webhook Configurations

```bash
export CA_BUNDLE=$(cat config/webhook/certs/ca.crt | base64 | tr -d '\n')

# Update validating webhook
kubectl patch validatingwebhookconfiguration threat-scanning-validating-webhook-configuration \
  --type='json' \
  -p="[
    {'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'},
    {'op': 'add', 'path': '/webhooks/1/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}
  ]"

# Update mutating webhook
kubectl patch mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration \
  --type='json' \
  -p="[
    {'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'},
    {'op': 'add', 'path': '/webhooks/1/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}
  ]"
```

### 4. Deploy Without cert-manager

```bash
# Deploy namespace and service
kubectl apply -f config/webhook/namespace.yaml
kubectl apply -f config/webhook/service.yaml

# Deploy RBAC
kubectl apply -f config/rbac/

# Deploy controller
kubectl apply -f config/webhook/deployment.yaml

# Deploy webhook configurations
kubectl apply -f config/webhook/validating_webhook_configuration.yaml
kubectl apply -f config/webhook/mutating_webhook_configuration.yaml
```

## Customizing Environment Variables

To customize environment variables in the deployment, edit `config/webhook/deployment.yaml` and modify the `env` section:

```yaml
env:
- name: INSTALL_NAMESPACE
  value: "your-namespace"  # Change this
- name: PRODUCTION
  value: "true"  # Set to true for production
- name: RELATED_IMAGE_VALIDATOR
  value: "your-registry/validator:tag"
# ... add more as needed
```

Then redeploy:
```bash
kubectl apply -f config/webhook/deployment.yaml
```

## Testing the Webhooks

### Test Target Validation

```bash
# This should fail (no namespace in credentialSecret)
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
    url: http://minio.default.svc:9000
    bucketName: test
    credentialSecret:
      name: test-secret
      # namespace missing - should fail
EOF
```

Expected: Webhook denies with error about missing namespace.

### Test ScanInstance Validation

```bash
# This should fail (target doesn't exist)
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-scan-fail
spec:
  backupTarget:
    name: non-existent-target
  backupRef:
    path: /test/path
EOF
```

Expected: Webhook denies with error about target not found.

## Troubleshooting

### 1. Certificate Not Ready

**Symptom**: Certificate stuck in "False" ready state

**Solution**:
```bash
# Check certificate status
kubectl describe certificate threat-scanning-webhook-cert -n threat-scanning-system

# Check cert-manager logs
kubectl logs -n cert-manager -l app=cert-manager
```

### 2. Webhook Pod CrashLoopBackOff

**Symptom**: Pod keeps restarting

**Solution**:
```bash
# Check pod logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning

# Check pod events
kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning

# Common issues:
# - Certificate secret not ready
# - RBAC permissions missing
# - Image pull errors
```

### 3. Webhook Not Being Called

**Symptom**: Resources created without validation

**Solution**:
```bash
# Check if webhook configurations exist
kubectl get validatingwebhookconfiguration
kubectl get mutatingwebhookconfiguration

# Check if CA bundle is injected
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration -o yaml | grep caBundle

# Check webhook service
kubectl get svc -n threat-scanning-system threat-scanning-webhook-service
```

### 4. Connection Refused Errors

**Symptom**: "connection refused" when creating resources

**Solution**:
```bash
# Check pod is running
kubectl get pods -n threat-scanning-system

# Check service endpoints
kubectl get endpoints -n threat-scanning-system threat-scanning-webhook-service

# Test connectivity to webhook
kubectl run -it --rm debug --image=busybox --restart=Never -- \
  wget -O- https://threat-scanning-webhook-service.threat-scanning-system.svc:443/validate-threatscanning-trilio-io-v1-target
```

## Updating the Deployment

### Update Image

```bash
# Build new image with new tag
export IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:v1.1
make docker-build docker-push IMG=${IMG}

# Update deployment
kubectl set image deployment/threat-scanning-controller \
  manager=${IMG} \
  -n threat-scanning-system

# Watch rollout
kubectl rollout status deployment/threat-scanning-controller -n threat-scanning-system
```

### Update Environment Variables

```bash
# Edit deployment
kubectl edit deployment threat-scanning-controller -n threat-scanning-system

# Or update from file
kubectl apply -f config/webhook/deployment.yaml
```

## Cleanup

To remove all webhook resources:

```bash
# Delete webhook configurations
kubectl delete validatingwebhookconfiguration threat-scanning-validating-webhook-configuration
kubectl delete mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration

# Delete deployment and resources
kubectl delete -f config/webhook/manifests.yaml

# Delete RBAC
kubectl delete -f config/rbac/

# Delete CRDs
kubectl delete -f config/crd/bases

# Delete namespace (this will delete everything in the namespace)
kubectl delete namespace threat-scanning-system
```

## Production Considerations

### 1. Use Production Certificates

For production, use proper certificates:
- Use cert-manager with a trusted CA issuer (e.g., Let's Encrypt, internal CA)
- Or use your organization's PKI/certificate management system

### 2. High Availability

For production, run multiple replicas:
```yaml
spec:
  replicas: 3  # Multiple replicas for HA
```

Enable leader election (already enabled in the deployment):
```bash
--leader-elect=true
```

### 3. Resource Limits

Adjust resource limits based on your workload:
```yaml
resources:
  limits:
    cpu: 1000m      # Increase as needed
    memory: 1Gi     # Increase as needed
  requests:
    cpu: 200m
    memory: 256Mi
```

### 4. Monitoring

Set up monitoring for:
- Webhook latency
- Validation/mutation success rates
- Certificate expiration
- Pod health and restarts

### 5. Failure Policy

For critical production systems, consider using `Ignore` failure policy for non-critical validations to prevent webhook outages from blocking API operations.

## Makefile Targets

The Makefile provides convenient targets:

```bash
# Build webhook image
make webhook-docker-build

# Build and push webhook image
make webhook-docker-push

# Deploy webhook
make webhook-deploy

# Full workflow: build, push, and deploy
make webhook-build-deploy

# View webhook logs
make webhook-logs

# Remove webhook
make webhook-undeploy
```

## Next Steps

1. **Test webhooks thoroughly** using the test guide: `WEBHOOK_QUICK_TEST_GUIDE.md`
2. **Set up monitoring** for webhook metrics
3. **Configure alerts** for certificate expiration
4. **Document custom validation rules** specific to your environment
5. **Set up CI/CD** for automated builds and deployments
