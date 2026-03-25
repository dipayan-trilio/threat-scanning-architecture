# Quick Deploy Reference - Threat Scanning Webhooks

## 🚀 Quick Deploy (Recommended)

```bash
# Deploy with existing image (assumes cert-manager installed)
./deploy-webhook.sh

# Build, push, and deploy
./deploy-webhook.sh --build

# Deploy without cert-manager (manual certs)
./deploy-webhook.sh --no-cert-manager
```

## 📦 Docker Build & Push

```bash
# Set image name
export IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest

# Build and push
make docker-build docker-push IMG=${IMG}
```

## 🔧 Manual Deployment Steps

### 1. Install cert-manager (one-time)
```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
kubectl wait --for=condition=Ready pods --all -n cert-manager --timeout=300s
```

### 2. Install CRDs
```bash
kubectl apply -f config/crd/bases
```

### 3. Install RBAC
```bash
kubectl apply -f config/rbac/
```

### 4. Deploy Webhook
```bash
kubectl apply -f config/webhook/manifests.yaml
```

### 5. Verify
```bash
kubectl get pods -n threat-scanning-system
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -f
```

## 🔐 Manual Certificates (Alternative)

If not using cert-manager:

```bash
# Generate certificates
./hack/generate-webhook-certs.sh

# Create secret
kubectl create namespace threat-scanning-system
kubectl create secret tls threat-scanning-webhook-certs \
  --cert=config/webhook/certs/tls.crt \
  --key=config/webhook/certs/tls.key \
  -n threat-scanning-system

# Inject CA bundle
export CA_BUNDLE=$(cat config/webhook/certs/ca.crt | base64 | tr -d '\n')
kubectl patch validatingwebhookconfiguration threat-scanning-validating-webhook-configuration \
  --type='json' -p="[
    {'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'},
    {'op': 'add', 'path': '/webhooks/1/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}
  ]"
kubectl patch mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration \
  --type='json' -p="[
    {'op': 'add', 'path': '/webhooks/0/clientConfig/caBundle', 'value':'${CA_BUNDLE}'},
    {'op': 'add', 'path': '/webhooks/1/clientConfig/caBundle', 'value':'${CA_BUNDLE}'}
  ]"
```

## 🧪 Quick Test

```bash
# Should fail - no namespace in credentialSecret
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
      # namespace missing
EOF
```

Expected: Webhook denies with error message.

## 📊 Status Check

```bash
# Pod status
kubectl get pods -n threat-scanning-system

# Certificate status (if using cert-manager)
kubectl get certificate -n threat-scanning-system

# Webhook configs
kubectl get validatingwebhookconfiguration
kubectl get mutatingwebhookconfiguration

# Logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -f
```

## 🔄 Update Deployment

### Update Image
```bash
kubectl set image deployment/threat-scanning-controller \
  manager=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:v1.1 \
  -n threat-scanning-system
```

### Update Environment Variables
```bash
kubectl edit deployment threat-scanning-controller -n threat-scanning-system
# Or
kubectl apply -f config/webhook/deployment.yaml
```

## 🗑️ Cleanup

```bash
# Delete everything
kubectl delete -f config/webhook/manifests.yaml
kubectl delete -f config/rbac/
kubectl delete -f config/crd/bases
kubectl delete namespace threat-scanning-system

# Or use make target
make webhook-undeploy
```

## 🐛 Troubleshooting

### Pod not starting
```bash
kubectl describe pod -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning
```

### Certificate not ready
```bash
kubectl describe certificate threat-scanning-webhook-cert -n threat-scanning-system
kubectl logs -n cert-manager -l app=cert-manager
```

### Webhook not being called
```bash
# Check webhook configs exist
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration
kubectl get mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration

# Check CA bundle injected
kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration -o yaml | grep caBundle
```

## 🎯 Environment Variables

The controller uses these environment variables (defined in deployment):

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

## 📚 Documentation

- **Full Deployment Guide**: `WEBHOOK_DEPLOYMENT_GUIDE.md`
- **Implementation Details**: `WEBHOOK_IMPLEMENTATION.md`
- **Test Guide**: `WEBHOOK_QUICK_TEST_GUIDE.md`
- **Webhook Configuration**: `config/webhook/README.md`

## ⚙️ Makefile Targets

```bash
make webhook-docker-build      # Build webhook image
make webhook-docker-push       # Build and push image
make webhook-deploy           # Deploy webhook
make webhook-build-deploy     # Build, push, and deploy
make webhook-logs             # Show logs
make webhook-undeploy         # Remove webhook
```

## 🎓 Examples

### Complete Fresh Install
```bash
# 1. Install cert-manager (one-time)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# 2. Build and deploy
./deploy-webhook.sh --build
```

### Update Existing Deployment
```bash
# Build new version
export IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:v1.1
make docker-build docker-push IMG=${IMG}

# Update deployment
kubectl set image deployment/threat-scanning-controller \
  manager=${IMG} -n threat-scanning-system
```

### Deploy to Different Namespace
```bash
# Edit deployment and manifests to use custom namespace
sed -i 's/threat-scanning-system/my-custom-namespace/g' config/webhook/*.yaml
kubectl apply -f config/webhook/manifests.yaml
```
