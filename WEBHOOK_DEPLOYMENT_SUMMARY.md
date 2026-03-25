# Webhook Deployment - Implementation Summary

## Overview

Successfully created comprehensive deployment infrastructure for the threat-scanning controller with webhooks enabled, including Docker build, Kubernetes manifests, and automation scripts.

## Files Created

### Docker & Build Configuration

1. **Dockerfile** (already exists, supports both manager and janitor)
   - Multi-stage build with Go 1.21
   - Alpine-based runtime
   - Non-root user execution
   - Webhook support enabled

2. **Makefile** (already exists, enhanced with webhook targets)
   - `make webhook-docker-build` - Build webhook image
   - `make webhook-docker-push` - Build and push
   - `make webhook-deploy` - Deploy webhook
   - `make webhook-build-deploy` - Full workflow
   - `make webhook-logs` - View logs
   - `make webhook-undeploy` - Remove webhook

### Kubernetes Manifests

Located in `config/webhook/`:

1. **`namespace.yaml`** - Namespace definition
   - Creates `threat-scanning-system` namespace

2. **`service.yaml`** - Webhook service
   - Exposes webhook on port 443
   - Routes to manager pod port 9443

3. **`deployment.yaml`** - Controller deployment
   - Single replica (HA can use 3+ replicas)
   - Webhook enabled with args
   - All environment variables configured:
     - `INSTALL_NAMESPACE=default`
     - `PRODUCTION=false`
     - `RELATED_IMAGE_VALIDATOR`
     - `RELATED_IMAGE_POLLER`
     - `RELATED_IMAGE_SCANNER`
     - `RELATED_IMAGE_JANITOR`
     - `RELATED_IMAGE_REDIS`
     - `TARGET_POLLING_DISABLED=true`
     - `TARGET_POLLING_CRON=2 * * * *`
     - `DATABASE_URL`
   - Health and readiness probes
   - Resource limits configured
   - Security context (non-root, drop all capabilities)
   - Volume mount for webhook certificates

4. **`certificate.yaml`** - cert-manager Certificate
   - Self-signed issuer
   - 1-year validity
   - Proper DNS SANs for webhook service

5. **`validating_webhook_configuration.yaml`** - Validating webhooks
   - Target validation (CREATE, UPDATE, DELETE)
   - ScanInstance validation (CREATE, UPDATE, DELETE)
   - cert-manager CA injection annotation

6. **`mutating_webhook_configuration.yaml`** - Mutating webhooks
   - Target mutation (CREATE)
   - ScanInstance mutation (CREATE)
   - cert-manager CA injection annotation

7. **`manifests.yaml`** - Combined manifest
   - All-in-one deployment file
   - Includes: namespace, service, certificates, deployment, webhooks
   - Easy single-command deployment

8. **`kustomization.yaml`** (already exists)
   - Kustomize configuration

9. **`README.md`** - Webhook configuration documentation

### Automation Scripts

1. **`deploy-webhook.sh`** - Automated deployment script
   - Prerequisites checking
   - cert-manager installation (optional)
   - Image building and pushing (optional)
   - CRD installation
   - RBAC setup
   - Webhook deployment
   - Verification and status reporting
   - Command-line flags:
     - `--build` - Build and push image
     - `--no-cert-manager` - Use manual certificates
     - `--image IMAGE` - Custom image
     - `--help` - Show help

2. **`hack/generate-webhook-certs.sh`** (already exists)
   - Self-signed certificate generation
   - For development/testing without cert-manager

### Documentation

1. **`WEBHOOK_DEPLOYMENT_GUIDE.md`** - Comprehensive deployment guide
   - Prerequisites and setup
   - Step-by-step instructions
   - cert-manager and manual certificate options
   - Customization guide
   - Testing instructions
   - Troubleshooting section
   - Production considerations
   - Makefile targets reference

2. **`WEBHOOK_QUICK_DEPLOY.md`** - Quick reference card
   - Quick deploy commands
   - Common operations
   - Status checks
   - Troubleshooting tips
   - Environment variables reference
   - Examples

3. **`config/webhook/README.md`** - Webhook configuration docs
   - File descriptions
   - Endpoint documentation
   - Deployment instructions
   - Configuration details
   - Troubleshooting

## Deployment Options

### Option 1: Automated Deployment (Recommended)

```bash
# Deploy with existing image
./deploy-webhook.sh

# Build, push, and deploy
./deploy-webhook.sh --build

# Deploy without cert-manager
./deploy-webhook.sh --no-cert-manager
```

### Option 2: Using Makefile

```bash
# Build and push image
IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest \
  make docker-build docker-push

# Deploy CRDs and RBAC
kubectl apply -f config/crd/bases
kubectl apply -f config/rbac/

# Deploy webhook
make webhook-deploy
```

### Option 3: Manual Deployment

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Install CRDs
kubectl apply -f config/crd/bases

# Install RBAC
kubectl apply -f config/rbac/

# Deploy webhook with all resources
kubectl apply -f config/webhook/manifests.yaml
```

## Environment Variables Configured

All environment variables from your requirements are configured in the deployment:

```yaml
INSTALL_NAMESPACE: "default"
PRODUCTION: "false"
RELATED_IMAGE_VALIDATOR: "eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v9.5"
RELATED_IMAGE_POLLER: "eu.gcr.io/amazing-chalice-243510/threatscanning/datastore-attacher:v9.5"
RELATED_IMAGE_SCANNER: "eu.gcr.io/amazing-chalice-243510/threatscanning/scan-engine:v1.6"
RELATED_IMAGE_JANITOR: "eu.gcr.io/amazing-chalice-243510/threatscanning/janitor:v1.2"
RELATED_IMAGE_REDIS: "redis:7-alpine"
TARGET_POLLING_DISABLED: "true"
TARGET_POLLING_CRON: "2 * * * *"
DATABASE_URL: "sqlite+aiosqlite:///./scan_analysis.db"
```

## Docker Image Build

The Dockerfile supports building the webhook-enabled controller:

```bash
# Build
docker build -t eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest .

# Push
docker push eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest
```

The image includes:
- Manager binary with webhook support
- Janitor binary
- CA certificates for HTTPS
- Non-root user (65532)
- Alpine-based minimal image

## Webhook Configuration

### Endpoints Registered

**Target Webhooks:**
- `POST /validate-threatscanning-trilio-io-v1-target` (Validating)
- `POST /mutate-threatscanning-trilio-io-v1-target` (Mutating)

**ScanInstance Webhooks:**
- `POST /validate-threatscanning-trilio-io-v1-scaninstance` (Validating)
- `POST /mutate-threatscanning-trilio-io-v1-scaninstance` (Mutating)

### Certificate Management

**Option 1: cert-manager (Recommended)**
- Automated certificate lifecycle
- Auto-renewal before expiration
- CA bundle auto-injection

**Option 2: Manual Certificates**
- Use `hack/generate-webhook-certs.sh`
- Create secret manually
- Inject CA bundle with kubectl patch

## Verification

After deployment, verify with:

```bash
# Check pod status
kubectl get pods -n threat-scanning-system

# Check certificate (if using cert-manager)
kubectl get certificate -n threat-scanning-system

# Check webhook configurations
kubectl get validatingwebhookconfiguration
kubectl get mutatingwebhookconfiguration

# View logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -f

# Test webhook
kubectl apply -f config/samples/minio-target.yaml
```

## Production Readiness

The deployment includes production-ready features:

1. **Security**
   - Non-root user execution
   - Dropped capabilities
   - Security context configured
   - TLS for webhook communication

2. **High Availability**
   - Leader election enabled
   - Can scale to multiple replicas
   - Health and readiness probes

3. **Observability**
   - Metrics endpoint (port 8080)
   - Health endpoint (port 8081)
   - Structured logging
   - Pod events and status

4. **Resource Management**
   - CPU and memory limits
   - Resource requests
   - Graceful termination

## Next Steps

1. **Deploy the controller:**
   ```bash
   ./deploy-webhook.sh --build
   ```

2. **Verify deployment:**
   ```bash
   kubectl get pods -n threat-scanning-system
   ```

3. **Test webhooks:**
   - Follow `WEBHOOK_QUICK_TEST_GUIDE.md`
   - Create test targets and scan instances

4. **Monitor:**
   - Set up monitoring for webhook metrics
   - Configure alerts for certificate expiration
   - Monitor pod health and logs

5. **Customize:**
   - Adjust resource limits for your workload
   - Configure environment variables as needed
   - Set up production certificates

## Troubleshooting

Common issues and solutions are documented in:
- `WEBHOOK_DEPLOYMENT_GUIDE.md` - Comprehensive troubleshooting
- `WEBHOOK_QUICK_DEPLOY.md` - Quick troubleshooting tips
- `config/webhook/README.md` - Configuration-specific issues

Quick checks:
```bash
# Pod not starting?
kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning

# Certificate not ready?
kubectl describe certificate threat-scanning-webhook-cert -n threat-scanning-system

# Webhook not being called?
kubectl get validatingwebhookconfiguration -o yaml | grep caBundle
```

## Files Modified/Created Summary

**New Files:**
- `config/webhook/deployment.yaml` - Controller deployment
- `config/webhook/namespace.yaml` - Namespace
- `config/webhook/certificate.yaml` - cert-manager certificate
- `config/webhook/manifests.yaml` - Combined manifest
- `deploy-webhook.sh` - Automated deployment script
- `WEBHOOK_DEPLOYMENT_GUIDE.md` - Comprehensive guide
- `WEBHOOK_QUICK_DEPLOY.md` - Quick reference

**Modified Files:**
- `config/webhook/validating_webhook_configuration.yaml` - Added cert-manager annotation
- `config/webhook/mutating_webhook_configuration.yaml` - Added cert-manager annotation
- `config/webhook/README.md` - Updated documentation

**Existing Files (Used):**
- `Dockerfile` - Builds controller image
- `Makefile` - Build and deployment targets
- `hack/generate-webhook-certs.sh` - Manual cert generation
- `config/rbac/*.yaml` - RBAC resources
- `config/crd/bases/*.yaml` - CRD definitions

## Success Criteria

✅ Docker build configured with webhook support
✅ Kubernetes manifests with all environment variables
✅ cert-manager integration for automatic certificates
✅ Manual certificate option for environments without cert-manager
✅ Automated deployment script with verification
✅ Comprehensive documentation and guides
✅ Quick reference for common operations
✅ Troubleshooting guides and examples
✅ Production-ready security and resource configuration
✅ Health checks and observability

The deployment infrastructure is complete and ready for use!
