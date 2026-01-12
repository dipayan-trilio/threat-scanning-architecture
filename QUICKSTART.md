# Quick Start Guide

## Prerequisites

- Go 1.21 or later
- Access to a Kubernetes cluster (v1.29+)
- kubectl configured to access your cluster

## Build and Run

### 1. Build the Controller

```bash
cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture
make build
```

This creates `bin/manager` (51 MB binary).

### 2. Install CRDs (when manifests are generated)

```bash
# First, generate CRD manifests
make manifests

# Then install them
kubectl apply -f config/crd/bases/
```

### 3. Run Locally (Development)

```bash
# Run against your configured cluster
make run
```

### 4. Create a Test Target

**NFS Target Example:**

```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-nfs-target
spec:
  type: NFS
  vendor: Other
  nfsCredentials:
    nfsExport: "192.168.1.100:/backups"
    nfsOptions: "rw"
  thresholdCapacity: 100Gi
EOF
```

**S3 Target Example:**

```bash
# Create secret first
kubectl create secret generic s3-creds \
  --from-literal=accessKey=YOUR_ACCESS_KEY \
  --from-literal=secretKey=YOUR_SECRET_KEY \
  -n threat-scanning-system

# Create target
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-s3-target
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    url: "https://s3.amazonaws.com"
    bucketName: "my-bucket"
    region: "us-east-1"
    credentialSecret:
      name: s3-creds
      namespace: threat-scanning-system
EOF
```

### 5. Check Target Status

```bash
# List all targets
kubectl get targets

# Get target details
kubectl get target test-nfs-target -o yaml

# Watch for status updates
kubectl get target test-nfs-target -w
```

### 6. Check Validation Job

```bash
# The controller creates a validation job
# List jobs in the threat-scanning-system namespace
kubectl get jobs -n threat-scanning-system

# Get job logs
kubectl logs -n threat-scanning-system job/threat-scan-target-validation-XXXXX
```

### 7. Check Validation ConfigMap

```bash
# View cached validation results
kubectl get configmap threat-scan-target-validation-config \
  -n threat-scanning-system -o yaml
```

## Expected Behavior

1. **Target Created** → Status: `InProgress`
2. **Validation Job Created** → Pod runs validation
3. **Validation Succeeds** → Status: `Available`
4. **Validation Fails** → Status: `Unavailable`

## Troubleshooting

### Target Stuck in InProgress

```bash
# Check validation job
kubectl get jobs -n threat-scanning-system
kubectl describe job threat-scan-target-validation-XXXXX -n threat-scanning-system

# Check pod logs
kubectl logs -n threat-scanning-system -l job-name=threat-scan-target-validation-XXXXX
```

### Target Shows Unavailable

```bash
# Check target conditions
kubectl get target TARGET_NAME -o jsonpath='{.status.condition}' | jq

# Check validation job logs
kubectl logs -n threat-scanning-system -l target-name=TARGET_NAME
```

### Controller Not Reconciling

```bash
# Check controller logs (if running in cluster)
kubectl logs -n threat-scanning-system deployment/threat-scanning-controller

# Check controller metrics (if enabled)
curl http://localhost:8080/metrics
```

## Clean Up

```bash
# Delete target
kubectl delete target test-nfs-target

# The controller's finalizer will ensure cleanup of:
# - Validation jobs
# - NFS PV/PVC (for NFS targets)
# - Annotations and status

# Uninstall CRDs
kubectl delete -f config/crd/bases/
```

## Development Workflow

### Make Changes

1. Edit code in `api/`, `controllers/`, or `pkg/`
2. Run `make generate` to update DeepCopy methods (if API changed)
3. Run `make manifests` to update CRD manifests (if API changed)
4. Run `make fmt` to format code
5. Run `make vet` to check for issues
6. Run `make build` to compile

### Test Changes

```bash
# Run locally
make run

# In another terminal, create/update test targets
kubectl apply -f examples/test-target.yaml
```

## Next Steps

- See [CONTROLLER_README.md](CONTROLLER_README.md) for detailed documentation
- See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for architecture details
- See [architecture.md](architecture.md) for threat scanning workflow

