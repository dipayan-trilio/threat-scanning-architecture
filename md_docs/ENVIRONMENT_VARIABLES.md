# Environment Variables Configuration

This document lists all environment variables used by the Threat Scanning Target Controller.

## Required Environment Variables

None - all environment variables have sensible defaults.

## Optional Environment Variables

### 1. `INSTALL_NAMESPACE`

**Purpose**: Specifies the namespace where all child resources (validation jobs, poller cronjobs, configmaps, PVCs, etc.) will be created.

**Default**: `threat-scanning-system`

**Usage**:
```bash
export INSTALL_NAMESPACE="my-custom-namespace"
./bin/manager
```

**Important Notes**:
- ⚠️ The namespace **must already exist** - the controller will NOT create it
- Create the namespace before starting the controller:
  ```bash
  kubectl create namespace my-custom-namespace
  ```
- All resources will be created in this namespace:
  - Validation Jobs
  - Poller CronJobs
  - NFS PersistentVolumes and PersistentVolumeClaims
  - Validation ConfigMap
  - Any other child resources

**Example Deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-scanning-controller
spec:
  template:
    spec:
      containers:
      - name: manager
        image: threat-scanning-controller:latest
        env:
        - name: INSTALL_NAMESPACE
          value: "custom-namespace"
```

### 2. `RELATED_IMAGE_VALIDATOR`

**Purpose**: Container image for target validation jobs.

**Default**: `busybox:1.36`

**Usage**:
```bash
export RELATED_IMAGE_VALIDATOR="my-registry/threat-scan-validator:v1.0.0"
```

**Example**:
```yaml
env:
- name: RELATED_IMAGE_VALIDATOR
  value: "quay.io/trilio/threat-scan-validator:v1.2.0"
```

### 3. `RELATED_IMAGE_POLLER`

**Purpose**: Container image for target poller cronjobs.

**Default**: `threat-scan-poller:latest`

**Usage**:
```bash
export RELATED_IMAGE_POLLER="my-registry/threat-scan-poller:v1.0.0"
```

**Example**:
```yaml
env:
- name: RELATED_IMAGE_POLLER
  value: "quay.io/trilio/threat-scan-poller:v1.2.0"
```

### 4. `POLLER_SCHEDULE`

**Purpose**: Cron schedule for poller jobs.

**Default**: `0 */6 * * *` (every 6 hours)

**Format**: Standard cron format

**Usage**:
```bash
export POLLER_SCHEDULE="0 */4 * * *"  # Every 4 hours
```

**Examples**:
| Schedule | Meaning |
|----------|---------|
| `0 */6 * * *` | Every 6 hours (default) |
| `0 */4 * * *` | Every 4 hours |
| `0 */12 * * *` | Every 12 hours |
| `0 0 * * *` | Daily at midnight |
| `*/30 * * * *` | Every 30 minutes |

**Deployment Example**:
```yaml
env:
- name: POLLER_SCHEDULE
  value: "0 */4 * * *"
```

## Complete Example

### Deployment with All Environment Variables

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: my-scanning-system
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-scanning-controller
  namespace: my-scanning-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: threat-scanning-controller
  template:
    metadata:
      labels:
        app: threat-scanning-controller
    spec:
      serviceAccountName: threat-scanning-controller
      containers:
      - name: manager
        image: threat-scanning-controller:latest
        env:
        # Namespace where all child resources will be created
        - name: INSTALL_NAMESPACE
          value: "my-scanning-system"
        
        # Custom validator image
        - name: RELATED_IMAGE_VALIDATOR
          value: "quay.io/myorg/validator:v1.0.0"
        
        # Custom poller image
        - name: RELATED_IMAGE_POLLER
          value: "quay.io/myorg/poller:v1.0.0"
        
        # Poll every 4 hours
        - name: POLLER_SCHEDULE
          value: "0 */4 * * *"
        
        resources:
          limits:
            cpu: 500m
            memory: 512Mi
          requests:
            cpu: 100m
            memory: 128Mi
```

### Running Locally with Custom Namespace

```bash
# 1. Create the namespace
kubectl create namespace my-scanning-ns

# 2. Set environment variables
export INSTALL_NAMESPACE="my-scanning-ns"
export RELATED_IMAGE_VALIDATOR="myregistry/validator:v1.0.0"
export RELATED_IMAGE_POLLER="myregistry/poller:v1.0.0"
export POLLER_SCHEDULE="0 */4 * * *"

# 3. Run the controller
./bin/manager
```

## Verification

### Check Which Namespace is Being Used

When the controller starts, it logs the installation namespace:

```
Installation namespace: my-scanning-system
```

### Verify Resources are Created in Correct Namespace

```bash
# Check validation jobs
kubectl get jobs -n my-scanning-system

# Check poller cronjobs
kubectl get cronjobs -n my-scanning-system

# Check validation configmap
kubectl get configmap threat-scan-target-validation-config -n my-scanning-system

# Check all resources
kubectl get all -n my-scanning-system
```

## Troubleshooting

### Error: "namespaces 'X' not found"

**Cause**: The namespace specified in `INSTALL_NAMESPACE` doesn't exist.

**Solution**:
```bash
# Create the namespace first
kubectl create namespace your-namespace-name

# Then start the controller
INSTALL_NAMESPACE=your-namespace-name ./bin/manager
```

### Resources Created in Wrong Namespace

**Check**: Verify the environment variable is set correctly

```bash
# In the controller pod
kubectl exec -it deployment/threat-scanning-controller -n threat-scanning-system -- env | grep INSTALL_NAMESPACE
```

**Fix**: Update the deployment to set the correct environment variable.

## Best Practices

1. **Namespace Creation**: Always create the namespace before deploying the controller
   ```bash
   kubectl create namespace threat-scanning-system
   ```

2. **Consistent Naming**: Use the same namespace for the controller and its child resources
   ```yaml
   # Controller deployed in: threat-scanning-system
   # Child resources created in: threat-scanning-system (via INSTALL_NAMESPACE)
   ```

3. **Environment-Specific Namespaces**: Use different namespaces for different environments
   - Development: `threat-scanning-dev`
   - Staging: `threat-scanning-staging`
   - Production: `threat-scanning-prod`

4. **Image Management**: Use specific image tags, not `latest`
   ```bash
   export RELATED_IMAGE_VALIDATOR="registry/validator:v1.2.3"
   export RELATED_IMAGE_POLLER="registry/poller:v1.2.3"
   ```

## Summary

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `INSTALL_NAMESPACE` | `threat-scanning-system` | No | Namespace for child resources (must exist) |
| `RELATED_IMAGE_VALIDATOR` | `busybox:1.36` | No | Validator container image |
| `RELATED_IMAGE_POLLER` | `threat-scan-poller:latest` | No | Poller container image |
| `POLLER_SCHEDULE` | `0 */6 * * *` | No | Cron schedule for polling |

All environment variables are optional and have sensible defaults for quick testing and development.

