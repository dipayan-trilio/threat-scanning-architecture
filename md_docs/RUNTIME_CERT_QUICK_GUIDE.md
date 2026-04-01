# Runtime Certificate Generation - Quick Deploy Guide

## Overview

The threat-scanning controller now uses **runtime certificate generation** (just like Trilio k8s-triliovault), eliminating the need for cert-manager or manual certificate management.

## How It Works

1. **Init Container** runs before the main webhook server starts
2. Generates self-signed CA + server certificate using Go crypto libraries
3. Creates/updates Kubernetes Secret with certificates
4. Patches webhook configurations with CA bundle automatically
5. Main container starts and uses the certificates

## Benefits

✅ **No external dependencies** - No cert-manager needed
✅ **Self-contained** - Everything in one image  
✅ **Simple deployment** - Just deploy and go
✅ **Air-gap friendly** - Works in isolated environments
✅ **Production-ready** - Same approach Trilio uses

## Quick Deploy

### Option 1: Automated Deployment (Recommended)

```bash
# Deploy everything (no cert-manager needed!)
./deploy-webhook.sh --build
```

That's it! The init container will:
- Generate certificates automatically
- Create the secret
- Patch webhook configurations  
- Start the webhook server

### Option 2: Manual Deployment

```bash
# 1. Build and push image
export IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest
make docker-build docker-push IMG=${IMG}

# 2. Install CRDs
kubectl apply -f config/crd/bases

# 3. Install RBAC
kubectl apply -f config/rbac/

# 4. Deploy webhook (with runtime cert generation)
kubectl apply -f config/webhook/manifests-no-cert-manager.yaml

# 5. Watch the init container generate certificates
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c webhook-cert-init

# 6. Watch the main container start
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c manager -f
```

## Verify Deployment

```bash
# Check pod status
kubectl get pods -n threat-scanning-system

# Check init container logs (certificate generation)
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c webhook-cert-init

# Check that secret was created
kubectl get secret threat-scanning-webhook-certs -n threat-scanning-system

# Check webhook configurations have CA bundle
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration -o yaml | grep caBundle

# Watch main container logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c manager -f
```

## Environment Variables

All your environment variables are configured in the deployment:

```yaml
INSTALL_NAMESPACE: "default"
PRODUCTION: "false"
RELATED_IMAGE_VALIDATOR: "eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v9.5"
RELATED_IMAGE_POLLER: "eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v9.5"
RELATED_IMAGE_SCANNER: "eu.gcr.io/amazing-chalice-243510/threatscanning/scan-engine:v1.6"
RELATED_IMAGE_JANITOR: "eu.gcr.io/amazing-chalice-243510/threatscanning/janitor:v1.2"
TARGET_POLLING_DISABLED: "true"
TARGET_POLLING_CRON: "2 * * * *"
```

## Test the Webhooks

```bash
# This should fail - webhook will deny it
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-fail
spec:
  type: ObjectStore
  vendor: MinIO
  targetType: TVK
  objectStoreCredentials:
    bucketName: test
    credentialSecret:
      name: test-secret
      # namespace missing - webhook will deny
EOF
```

Expected: `Error from server: admission webhook "vtarget.threatscanning.trilio.io" denied the request`

## Troubleshooting

### Init Container Failed

```bash
# Check init container logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c webhook-cert-init

# Common issues:
# - RBAC permissions missing (check service account)
# - Webhook configurations don't exist yet (deploy them first)
```

### Main Container Not Starting

```bash
# Check if secret exists
kubectl get secret threat-scanning-webhook-certs -n threat-scanning-system

# Check main container logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c manager

# Describe pod for events
kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning
```

### Webhook Not Working

```bash
# Check if CA bundle was injected
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | base64 -d | openssl x509 -text -noout

# Check webhook service
kubectl get svc -n threat-scanning-system threat-scanning-webhook-service

# Check webhook endpoints
kubectl get endpoints -n threat-scanning-system threat-scanning-webhook-service
```

## Update Deployment

### Rebuild and Redeploy

```bash
# Build new image
export IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:v1.1
make docker-build docker-push IMG=${IMG}

# Update deployment image
kubectl set image deployment/threat-scanning-controller \
  manager=${IMG} \
  webhook-cert-init=${IMG} \
  -n threat-scanning-system

# Watch rollout
kubectl rollout status deployment/threat-scanning-controller -n threat-scanning-system
```

### Regenerate Certificates

```bash
# Delete the secret (init container will recreate it on restart)
kubectl delete secret threat-scanning-webhook-certs -n threat-scanning-system

# Restart the pod
kubectl delete pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning

# Watch init container regenerate certificates
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -c webhook-cert-init -f
```

## Certificate Lifecycle

- **Validity**: 1 year (same as Trilio)
- **Renewal**: Restart the pod to regenerate (or implement auto-renewal logic)
- **Location**: Stored in Secret `threat-scanning-webhook-certs`
- **CA Bundle**: Automatically injected into webhook configurations

## Comparison with cert-manager

| Feature | Runtime Generation | cert-manager |
|---------|-------------------|--------------|
| Dependencies | ✅ None | ❌ Requires cert-manager |
| Setup Complexity | ✅ Simple | ⚠️ Medium |
| Air-gap Support | ✅ Yes | ❌ No |
| Auto-renewal | ⚠️ Manual (restart pod) | ✅ Automatic |
| Used by Trilio | ✅ Yes | ❌ No |
| Production Ready | ✅ Yes | ✅ Yes |

## Optional: Use cert-manager Instead

If you prefer cert-manager:

```bash
# Deploy with cert-manager (requires cert-manager pre-installed)
./deploy-webhook.sh --build --use-cert-manager
```

## Summary

**You no longer need cert-manager!** The controller generates certificates automatically using the same approach as Trilio k8s-triliovault.

Just run:
```bash
./deploy-webhook.sh --build
```

And you're done! 🎉
