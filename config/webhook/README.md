# Webhook Deployment Guide

This directory contains the configuration for deploying the Threat Scanning validating webhook.

## Prerequisites

1. **Kubernetes cluster** with admin access
2. **cert-manager** installed (for automatic TLS certificate management)
3. **Docker** with access to push to `eu.gcr.io/amazing-chalice-243510`

### Install cert-manager

If cert-manager is not already installed:

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
```

Wait for cert-manager to be ready:

```bash
kubectl wait --for=condition=Available --timeout=300s deployment/cert-manager -n cert-manager
kubectl wait --for=condition=Available --timeout=300s deployment/cert-manager-webhook -n cert-manager
kubectl wait --for=condition=Available --timeout=300s deployment/cert-manager-cainjector -n cert-manager
```

## Quick Start - Full Deployment

To build, push, and deploy the webhook in one command:

```bash
make webhook-build-deploy
```

This will:
1. Run tests
2. Build the Docker image as `eu.gcr.io/amazing-chalice-243510/threat-scanning-webhook:latest`
3. Push the image to GCR
4. Deploy the webhook deployment, service, and validating webhook configuration
5. Create TLS certificates using cert-manager
6. Wait for certificates to be ready

## Step-by-Step Deployment

### 1. Build and Push Docker Image

```bash
# Build only
make webhook-docker-build

# Build and push
make webhook-docker-push
```

### 2. Deploy to Kubernetes

```bash
make webhook-deploy
```

This deploys:
- Namespace: `threat-scanning-system`
- ServiceAccount: `threat-scanning-webhook`
- Deployment: `threat-scanning-webhook` (1 replica)
- Service: `threat-scanning-webhook-service` (port 443 → 9443)
- Certificate resources (cert-manager)
- ValidatingWebhookConfiguration: `threat-scanning-validating-webhook`
- RBAC: ClusterRole and ClusterRoleBinding

### 3. Verify Deployment

Check webhook pod status:

```bash
kubectl get pods -n threat-scanning-system
```

Check webhook logs:

```bash
make webhook-logs
# or
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -f
```

Check certificate status:

```bash
kubectl get certificate -n threat-scanning-system
kubectl describe certificate webhook-server-cert -n threat-scanning-system
```

Check validating webhook configuration:

```bash
kubectl get validatingwebhookconfigurations threat-scanning-validating-webhook
kubectl describe validatingwebhookconfigurations threat-scanning-validating-webhook
```

## Webhook Validations

The webhook validates Target CRD on CREATE and UPDATE operations:

### CREATE Validations:
1. Target type must be NFS or ObjectStore
2. NFS targets must have NFS credentials (not ObjectStore credentials)
3. ObjectStore targets must have ObjectStore credentials (not NFS credentials)
4. ObjectStore targets must have credentialSecret and bucketName
5. Non-AWS/Azure vendors must provide a valid URL
6. SSL cert config must have certKey if provided
7. Only one reporting target allowed in the cluster

### UPDATE Validations:
- All CREATE validations
- Backup targets cannot be converted to reporting targets
- Reporting targets can be converted to backup targets

## Uninstall

To remove the webhook:

```bash
make webhook-undeploy
```

## Local Testing with ngrok

For local development, use the ngrok configuration:

1. Generate local certificates:
   ```bash
   bash hack/test-webhook-locally.sh
   ```

2. Run controller locally:
   ```bash
   go run ./cmd/manager/main.go --enable-webhook --webhook-port=9443 --webhook-cert-dir=/tmp/k8s-webhook-server/serving-certs
   ```

3. In another terminal, expose via ngrok:
   ```bash
   ngrok http 9443
   ```

4. Update ngrok manifest with your URL:
   ```bash
   sed -i 's/YOUR_NGROK_URL/<your-ngrok-url>/g' config/webhook/manifests-ngrok.yaml
   kubectl apply -f config/webhook/manifests-ngrok.yaml
   ```

## Files

- `deployment.yaml` - Webhook deployment, service account, and namespace
- `manifests.yaml` - Service and ValidatingWebhookConfiguration (with cert-manager injection)
- `certificate.yaml` - cert-manager Certificate and Issuer resources
- `manifests-ngrok.yaml` - ValidatingWebhookConfiguration for ngrok testing
- `kustomization.yaml` - Kustomize configuration

## Troubleshooting

### Webhook not receiving requests

Check if the webhook endpoint is reachable:

```bash
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -k https://threat-scanning-webhook-service.threat-scanning-system.svc.cluster.local:443/validate-threatscanning-trilio-io-v1-target
```

### Certificate issues

Check certificate status:

```bash
kubectl get certificate -n threat-scanning-system
kubectl describe certificate webhook-server-cert -n threat-scanning-system
kubectl get secret webhook-server-cert -n threat-scanning-system
```

Re-create certificates:

```bash
kubectl delete certificate webhook-server-cert -n threat-scanning-system
kubectl apply -f config/webhook/certificate.yaml
```

### Webhook validation failures

Check webhook logs for errors:

```bash
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning --tail=100
```

Test with a sample target:

```bash
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml
```

### Image pull issues

Ensure you're authenticated to GCR:

```bash
gcloud auth configure-docker eu.gcr.io
```

Or use a service account with appropriate permissions.

