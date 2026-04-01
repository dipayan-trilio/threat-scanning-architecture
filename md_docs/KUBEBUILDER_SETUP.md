# Kubebuilder Project Setup - Corrected Implementation

## Overview

This document describes the corrected Target Controller implementation using proper kubebuilder scaffolding and the correct API group.

## Corrections Made

### 1. ✅ API Group Fixed
- **Before**: `triliovault.trilio.io`
- **After**: `threatscanning.trilio.io`

### 2. ✅ Cluster-Scoped Resource Confirmed
The Target CRD is properly configured as cluster-scoped:
```yaml
spec:
  scope: Cluster
```

### 3. ✅ Kubebuilder Project Structure
Added proper kubebuilder scaffolding:
```
config/
├── crd/                           # CRD manifests
│   ├── bases/
│   │   └── threatscanning.trilio.io_targets.yaml
│   ├── kustomization.yaml
│   └── kustomizeconfig.yaml
├── default/                       # Default kustomization
│   ├── kustomization.yaml
│   └── manager_auth_proxy_patch.yaml
├── manager/                       # Controller deployment
│   ├── kustomization.yaml
│   └── manager.yaml
├── rbac/                         # RBAC resources
│   ├── kustomization.yaml
│   ├── service_account.yaml
│   ├── role.yaml
│   ├── role_binding.yaml
│   ├── leader_election_role.yaml
│   └── leader_election_role_binding.yaml
└── samples/                      # Example targets
    ├── kustomization.yaml
    ├── threatscanning_v1_target_nfs.yaml
    ├── threatscanning_v1_target_s3.yaml
    └── threatscanning_v1_target_reporting.yaml
```

## Generated CRD

The CRD was successfully generated using controller-gen:

```bash
make manifests
```

**Generated file**: `config/crd/bases/threatscanning.trilio.io_targets.yaml`

**CRD Specifications:**
- **API Group**: `threatscanning.trilio.io`
- **Version**: `v1`
- **Kind**: `Target`
- **Scope**: `Cluster` (cluster-scoped)
- **Plural**: `targets`
- **Singular**: `target`

**Printer Columns:**
- Type
- Vendor
- Status
- Age

## Kubebuilder Markers

The Target CRD includes proper kubebuilder markers:

```go
// Target is a location where backup artifacts are stored.
//
// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:scope=Cluster
// +kubebuilder:printcolumn:name="Type",type=string,JSONPath=`.spec.type`
// +kubebuilder:printcolumn:name="Vendor",type=string,JSONPath=`.spec.vendor`
// +kubebuilder:printcolumn:name="Status",type=string,JSONPath=`.status.status`
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"
type Target struct {
    // ...
}
```

## PROJECT File

Created `PROJECT` file to track kubebuilder metadata:

```yaml
domain: trilio.io
layout:
- go.kubebuilder.io/v4
projectName: threat-scanning-architecture
repo: github.com/trilioData/threat-scanning-architecture
resources:
- api:
    crdVersion: v1
    namespaced: false
  controller: true
  domain: trilio.io
  group: threatscanning
  kind: Target
  path: github.com/trilioData/threat-scanning-architecture/api/v1
  version: v1
version: "3"
```

## Installation and Deployment

### 1. Install CRDs

```bash
make install
# Or manually:
kubectl apply -f config/crd/bases/threatscanning.trilio.io_targets.yaml
```

### 2. Deploy Controller (using kustomize)

```bash
# Deploy everything (namespace, RBAC, controller)
kubectl apply -k config/default

# Or deploy components individually:
kubectl apply -f config/rbac/
kubectl apply -f config/manager/
```

### 3. Create Sample Targets

```bash
# Create NFS target
kubectl apply -f config/samples/threatscanning_v1_target_nfs.yaml

# Create S3 target
kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml

# Create Reporting target
kubectl apply -f config/samples/threatscanning_v1_target_reporting.yaml
```

## Verify Installation

### Check CRD Installation

```bash
kubectl get crd targets.threatscanning.trilio.io
```

Expected output:
```
NAME                                CREATED AT
targets.threatscanning.trilio.io    2024-12-03T12:38:38Z
```

### Check API Resources

```bash
kubectl api-resources | grep threatscanning
```

Expected output:
```
targets       threatscanning.trilio.io/v1    false   Target
```

Note: `false` in the NAMESPACED column confirms it's cluster-scoped.

### Create a Test Target

```bash
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: test-target
spec:
  type: NFS
  vendor: Other
  nfsCredentials:
    nfsExport: "192.168.1.100:/backups"
  thresholdCapacity: 100Gi
EOF
```

### Verify Target Creation

```bash
# List all targets (cluster-scoped, no namespace needed)
kubectl get targets

# Get specific target
kubectl get target test-target -o yaml

# Watch for status updates
kubectl get target test-target -w
```

## RBAC Configuration

The controller requires cluster-wide permissions (ClusterRole) since Targets are cluster-scoped:

**Key Permissions:**
- `targets.threatscanning.trilio.io`: CRUD + status updates
- `jobs.batch`: CRUD (for validation jobs)
- `persistentvolumes`: CRUD (for NFS)
- `persistentvolumeclaims`: CRUD (for NFS)
- `secrets`: Read (for credentials)
- `configmaps`: CRUD (for validation cache)
- `events`: Create/Patch (for events)

## Docker Build

### Build Container Image

```bash
# Build for local architecture
make docker-build IMG=threat-scanning-controller:v1.0.0

# Build and push
make docker-build docker-push IMG=your-registry/threat-scanning-controller:v1.0.0
```

### Multi-platform Build

```bash
export PLATFORMS="linux/amd64,linux/arm64"
make docker-buildx IMG=your-registry/threat-scanning-controller:v1.0.0
```

## Development Workflow

### 1. Make API Changes

Edit `api/v1/target_types.go`

### 2. Regenerate Code

```bash
# Regenerate DeepCopy methods
make generate

# Regenerate CRD manifests
make manifests
```

### 3. Update RBAC (if needed)

Controller-gen automatically updates `config/rbac/role.yaml` based on RBAC markers in controller code.

### 4. Test Locally

```bash
# Run against configured cluster
make run

# In another terminal, test with sample targets
kubectl apply -f config/samples/
```

### 5. Build and Deploy

```bash
# Build binary
make build

# Build container
make docker-build IMG=threat-scanning-controller:v1.0.0

# Deploy to cluster
kubectl apply -k config/default
```

## Kustomize Overlays

You can create environment-specific overlays:

```
config/
├── default/          # Base kustomization
├── development/      # Dev overlay
│   └── kustomization.yaml
├── staging/          # Staging overlay
│   └── kustomization.yaml
└── production/       # Prod overlay
    └── kustomization.yaml
```

Example development overlay:

```yaml
# config/development/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

bases:
- ../default

namespace: threat-scanning-dev

images:
- name: controller
  newName: threat-scanning-controller
  newTag: dev

patchesStrategicMerge:
- manager_patch.yaml
```

## Validation

The CRD includes extensive validation via kubebuilder markers:

```go
// +kubebuilder:validation:Enum=ObjectStore;NFS
type TargetType string

// +kubebuilder:validation:Enum=AWS;RedhatCeph;Ceph;...
type Vendor string

// +kubebuilder:validation:Enum=InProgress;Available;Unavailable
type Status string
```

## Testing

### Unit Tests

```bash
make test
```

### Integration Tests

```bash
# Run controller in test mode
make run

# In another terminal, run integration tests
go test ./tests/integration/...
```

## Cleanup

### Uninstall Controller

```bash
kubectl delete -k config/default
```

### Uninstall CRDs

```bash
make uninstall
# Or manually:
kubectl delete -f config/crd/bases/threatscanning.trilio.io_targets.yaml
```

**Warning**: Deleting CRDs will also delete all Target resources!

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make manifests` | Generate CRD and RBAC manifests |
| `make generate` | Generate DeepCopy code |
| `make fmt` | Format code |
| `make vet` | Run go vet |
| `make test` | Run tests |
| `make build` | Build manager binary |
| `make run` | Run locally against cluster |
| `make docker-build` | Build Docker image |
| `make docker-push` | Push Docker image |
| `make install` | Install CRDs |
| `make uninstall` | Uninstall CRDs |
| `make deploy` | Deploy controller |
| `make undeploy` | Undeploy controller |

## Summary of Corrections

✅ **API Group**: Changed from `triliovault.trilio.io` to `threatscanning.trilio.io`  
✅ **Cluster Scope**: Confirmed and verified in generated CRD  
✅ **Kubebuilder Structure**: Complete config/ directory with all manifests  
✅ **PROJECT File**: Added for kubebuilder metadata tracking  
✅ **Samples**: Created example targets in `config/samples/`  
✅ **Generated CRD**: Successfully generated with controller-gen  
✅ **RBAC**: Proper ClusterRole for cluster-scoped resources  
✅ **Dockerfile**: Added for container builds  

The project now follows proper kubebuilder conventions and can be deployed using standard Kubernetes tooling (kubectl, kustomize).

