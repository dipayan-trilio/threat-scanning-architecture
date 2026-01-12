# Threat Scanning Architecture - Target Controller

This repository contains the Target Controller for the Threat Scanning Service. The controller is based on the k8s-triliovault Target CRD and controller but simplified to focus on target validation only.

## Overview

The Target Controller manages Target resources which represent storage locations where backup artifacts are stored. It performs validation of these targets to ensure they are accessible and properly configured.

## Features

- **Target Validation**: Creates validation pods to verify target accessibility
- **NFS Support**: Full support for NFS-based targets with PV/PVC management
- **Object Store Support**: Support for S3-compatible object stores
- **Credential Hash Management**: Efficiently tracks credential changes
- **Validation ConfigMap**: Caches validation results to avoid redundant validation

## Architecture

### Components

1. **Target CRD** (`api/v1/target_types.go`)
   - Cluster-scoped custom resource
   - Supports NFS and ObjectStore types
   - Tracks validation status and conditions

2. **Target Controller** (`controllers/target/controller.go`)
   - Reconciles Target resources
   - Creates validation jobs
   - Manages NFS volumes (PV/PVC)
   - Handles finalizers for cleanup

3. **Helper Functions** (`pkg/helpers/`)
   - `target_helper.go`: Target-specific utilities
   - `job_helper.go`: Validation job creation

4. **Internal Package** (`internal/`)
   - Constants and common utilities

## How It Works

### Target Creation Flow

1. User creates a Target CR with either NFS or ObjectStore credentials
2. Controller calculates a hash of the target credentials
3. Controller marks the target as `InProgress`
4. If NFS target, controller creates PV and PVC
5. Controller checks validation ConfigMap for cached results
6. If validation needed, controller creates a validation Job
7. Job validates target accessibility:
   - NFS: Mounts the NFS share and checks accessibility
   - ObjectStore: Validates credentials and connectivity
8. Based on job result, controller updates target status to `Available` or `Unavailable`
9. Validation result is cached in ConfigMap

### Credential Hash Management

The controller uses a SHA-256 hash of target credentials to:
- Identify unique credential combinations
- Share validation results across targets with same credentials
- Manage lifecycle of validation jobs and NFS volumes

### Validation ConfigMap

The controller maintains a ConfigMap (`threat-scan-target-validation-config`) that stores:
- Key: Credential hash
- Value: `VALID` or `INVALID`

This prevents redundant validation for targets with identical credentials.

## Target Types

### NFS Target

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: nfs-backup-target
spec:
  type: NFS
  vendor: Other
  nfsCredentials:
    nfsExport: "192.168.1.100:/backup/path"
    nfsOptions: "rw,hard,intr"
  thresholdCapacity: 100Gi
```

### ObjectStore Target

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: s3-backup-target
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    url: "https://s3.amazonaws.com"
    bucketName: "my-backup-bucket"
    region: "us-east-1"
    credentialSecret:
      name: s3-credentials
      namespace: threat-scanning-system
    skipCertVerification: false
```

### Reporting Target

A reporting target is designated by annotation:

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  vendor: MinIO
  objectStoreCredentials:
    url: "https://minio.example.com"
    bucketName: "scan-reports"
    credentialSecret:
      name: minio-credentials
      namespace: threat-scanning-system
```

## Differences from k8s-triliovault Target Controller

This simplified controller **excludes** the following features from the original:

1. **Event Target**: No event target functionality
2. **Target Browsing**: No target browser deployment
3. **Statistics**: No capacity/backup plan statistics tracking
4. **Immutable Targets**: No object locking support
5. **Retention Policies**: No retention period management
6. **Continuous Restore**: No continuous restore instance tracking
7. **Security Scanning Instances**: Simplified for this use case
8. **Migration Support**: No namespace migration
9. **Webhooks**: No validation/mutation webhooks

The controller **focuses only on**:
- Target validation via Jobs
- NFS volume management (PV/PVC)
- Credential change detection
- Status management

## Building and Running

### Prerequisites

- Go 1.24.9 or later
- Kubernetes cluster (v1.31+)
- kubectl configured

### Build

```bash
# Build the binary
make build

# Run locally (against configured cluster)
make run
```

### Generate Manifests

```bash
# Generate CRD manifests
make manifests

# Generate DeepCopy implementations
make generate
```

### Docker Build

```bash
# Build Docker image
make docker-build IMG=my-registry/threat-scanning-controller:latest

# Push Docker image
make docker-push IMG=my-registry/threat-scanning-controller:latest
```

### Deploy to Cluster

```bash
# Install CRDs
make install

# Deploy controller
make deploy

# Undeploy
make undeploy

# Uninstall CRDs
make uninstall
```

## Development

### Project Structure

```
.
├── api/v1/                      # CRD definitions
│   ├── groupversion_info.go
│   └── target_types.go
├── cmd/manager/                 # Main entrypoint
│   └── main.go
├── controllers/target/          # Target controller
│   ├── controller.go
│   └── controller_helper.go
├── internal/                    # Internal utilities
│   └── constants.go
├── pkg/helpers/                 # Helper functions
│   ├── job_helper.go
│   └── target_helper.go
├── config/                      # Kubernetes manifests (to be generated)
├── hack/                        # Build scripts
└── Makefile
```

### Adding New Features

1. Update CRD in `api/v1/target_types.go`
2. Run `make generate` to update DeepCopy methods
3. Run `make manifests` to update CRD manifests
4. Implement reconciliation logic in `controllers/target/`
5. Add helper functions in `pkg/helpers/`
6. Update tests

## Testing

```bash
# Run tests
make test

# Run with coverage
go test ./... -coverprofile=cover.out
go tool cover -html=cover.out
```

## Configuration

The controller can be configured via command-line flags:

```bash
./bin/manager \
  --metrics-bind-address=:8080 \
  --health-probe-bind-address=:8081 \
  --leader-elect
```

### Environment Variables

- Installation namespace is hardcoded to `threat-scanning-system` in `internal/constants.go`
- Modify `internal.InstallNamespace` to change the namespace

## RBAC Permissions

The controller requires the following permissions:

- `targets`: get, list, watch, create, update, patch, delete
- `targets/status`: get, update, patch
- `jobs`: get, list, watch, create, update, patch, delete
- `persistentvolumes`: get, list, watch, create, update, patch, delete
- `persistentvolumeclaims`: get, list, watch, create, update, patch, delete
- `secrets`: get, list, watch
- `configmaps`: get, list, watch, create, update, patch, delete
- `events`: create, patch

## Monitoring

The controller exposes metrics on `:8080/metrics` and health checks:
- Liveness: `:8081/healthz`
- Readiness: `:8081/readyz`

## Reference

This controller is based on the k8s-triliovault Target controller:
- Original: `/home/dipayanpramanik/Devops/trilio/repo/k8s-triliovault/controllers/target/`
- API: `/home/dipayanpramanik/Devops/trilio/repo/k8s-triliovault/api/v1/target_types.go`

Key simplifications made for threat scanning use case:
- Removed event target functionality
- Removed target browsing features
- Simplified to focus on validation only
- Cluster-scoped resources instead of namespaced

## License

Copyright 2024 Trilio.

