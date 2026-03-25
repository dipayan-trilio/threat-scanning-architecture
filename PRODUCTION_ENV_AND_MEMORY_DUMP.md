# PRODUCTION Environment Variable and Memory Dump Path Implementation

## Overview

Added two enhancements to the scan job:
1. **PRODUCTION environment variable** - Controls whether `--production` flag is included in scan command
2. **Memory dump path** - Added to configmap alongside disk image path

## Changes Made

### 1. Memory Dump Path in ConfigMap

**File: `pkg/helpers/job_helper.go` - `GetScanConfigMapData()`**

#### Before
```go
diskImage = fmt.Sprintf("%s%s/pv.qcow2", internal.DefaultDatastoreBase, pvcPath)

vmArtifacts[vmKey] = map[string]interface{}{
    "memory_dump": "",        // Empty - memory dumps not collected
    "disk_image":  diskImage,
    ...
}
```

#### After
```go
// Construct full paths
diskImage = fmt.Sprintf("%s%s/pv.qcow2", internal.DefaultDatastoreBase, pvcPath)
memoryDump = fmt.Sprintf("%s%s/memory.dmp", internal.DefaultDatastoreBase, pvcPath)

vmArtifacts[vmKey] = map[string]interface{}{
    "memory_dump": memoryDump,   // Path to memory dump file
    "disk_image":  diskImage,    // Path to disk image file
    ...
}
```

#### Example ConfigMap Data

**Before:**
```json
{
  "vm_artifacts": {
    "ubuntu-vm_namespace1": {
      "hostname": "ubuntu-vm",
      "disk_image": "/triliodata/path/to/vm-disk-1/pv.qcow2",
      "memory_dump": "",
      ...
    }
  }
}
```

**After:**
```json
{
  "vm_artifacts": {
    "ubuntu-vm_namespace1": {
      "hostname": "ubuntu-vm",
      "disk_image": "/triliodata/path/to/vm-disk-1/pv.qcow2",
      "memory_dump": "/triliodata/path/to/vm-disk-1/memory.dmp",
      ...
    }
  }
}
```

### 2. PRODUCTION Environment Variable

**File: `pkg/helpers/job_helper.go` - `GetScanJob()`**

#### Implementation

```go
// Get PRODUCTION environment variable (default: "true")
productionMode := os.Getenv("PRODUCTION")
if productionMode == "" {
    productionMode = "true"
}

// Build scan engine command
scanEngineCmd := "python3 /app/main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json"

// Add --production flag only if PRODUCTION env is "true"
if strings.ToLower(productionMode) == "true" {
    scanEngineCmd = scanEngineCmd + " --production"
}
```

#### Environment Variable Added to Container

```go
scanContainer := corev1.Container{
    ...
    Env: []corev1.EnvVar{
        ...
        // PRODUCTION mode flag (default: "true")
        // When "false", --production flag is not included in scan command
        {
            Name:  "PRODUCTION",
            Value: productionMode,
        },
        ...
    },
}
```

## Usage

### Default Behavior (Production Mode)

**Controller Deployment:** No special configuration needed
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
        # PRODUCTION env not set, defaults to "true"
```

**Scan Job Command:**
```bash
python3 /app/main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json --production
```

### Development/Testing Mode

**Controller Deployment:** Set PRODUCTION to "false"
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
        env:
        - name: PRODUCTION
          value: "false"  # Disable production mode
```

**Scan Job Command:**
```bash
python3 /app/main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json
# Note: --production flag is NOT included
```

## Path Structure

### Memory Dump and Disk Image Paths

Both files are in the same directory (PVC snapshot directory):

```
/triliodata/                                    ← Mounted target root
  └── instance-id/                              ← Instance ID
      └── backups/
          └── backup-uid/                       ← Backup UID
              └── dataSnapshots/
                  └── vm-disk-1/                ← PVC snapshot directory
                      ├── pv.qcow2              ← Disk image ✅
                      └── memory.dmp            ← Memory dump ✅
```

**Disk Image Path:**
```
/triliodata/instance-id/backups/backup-uid/dataSnapshots/vm-disk-1/pv.qcow2
```

**Memory Dump Path:**
```
/triliodata/instance-id/backups/backup-uid/dataSnapshots/vm-disk-1/memory.dmp
```

## PRODUCTION Flag Behavior

### When PRODUCTION = "true" (default)

- **Command includes**: `--production`
- **Scanner behavior**: 
  - Production mode enabled
  - Full scanning with all checks
  - Results written to database
  - Alerts/notifications enabled

### When PRODUCTION = "false"

- **Command excludes**: `--production`
- **Scanner behavior**:
  - Development/testing mode
  - May skip certain checks
  - May use mock data
  - May disable external integrations

## ConfigMap Example

### Complete Example with Memory Dump

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scan-config-test-si
  namespace: threat-scanning-system
data:
  vm_artifacts_configuration.json: |
    {
      "vm_artifacts": {
        "ubuntu-vm_namespace1": {
          "description": "VM from backup bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d",
          "hostname": "ubuntu-vm",
          "ip_address": "0.0.0.0",
          "os": "Unknown",
          "memory_dump": "/triliodata/dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1/memory.dmp",
          "disk_image": "/triliodata/dipayan-ts-namespace1-e8d1e3f6/backups/bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d/dataSnapshots/ubuntu-vm-disk-1/pv.qcow2",
          "collection_time": "2026-02-19T14:30:00Z",
          "priority": "high",
          "suspected_compromise": true
        },
        "fedora-vm_namespace2": {
          "description": "VM from backup bc17e8b8-48b3-4c63-a0d6-7daf9ca09e8d",
          "hostname": "fedora-vm",
          "ip_address": "0.0.0.0",
          "os": "Unknown",
          "memory_dump": "/triliodata/dipayan-ts-namespace2-f8e2f4g7/backups/cd28f9c9-59c4-5d74-b1e7-8ebf0db10f9c/dataSnapshots/fedora-vm-disk-1/memory.dmp",
          "disk_image": "/triliodata/dipayan-ts-namespace2-f8e2f4g7/backups/cd28f9c9-59c4-5d74-b1e7-8ebf0db10f9c/dataSnapshots/fedora-vm-disk-1/pv.qcow2",
          "collection_time": "2026-02-19T14:30:00Z",
          "priority": "high",
          "suspected_compromise": true
        }
      }
    }
```

## Job Example

### Scan Job with PRODUCTION Environment

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: threat-scan-scanjob-test-si
  namespace: threat-scanning-system
spec:
  template:
    spec:
      containers:
      - name: scanner
        image: gcr.io/your-registry/enhanced-soc-analysis:latest
        command: ["/bin/bash", "-c"]
        args:
        - "python3 /app/main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json --production"
        env:
        - name: JOB_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['job-name']
        - name: JOB_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: PRODUCTION
          value: "true"  # ✅ PRODUCTION mode enabled
        - name: REDIS_URL
          value: redis://redis-svc-test-si.threat-scanning-system.svc.cluster.local:6379
        - name: DATABASE_URL
          value: sqlite:////data/scan.db
        volumeMounts:
        - name: scan-config
          mountPath: /config/vm_artifacts_configuration.json
          subPath: vm_artifacts_configuration.json
          readOnly: true
        - name: nfs-volume
          mountPath: /triliodata
      volumes:
      - name: scan-config
        configMap:
          name: scan-config-test-si
      - name: nfs-volume
        persistentVolumeClaim:
          claimName: nfs-pvc
```

## File Existence Handling

### Scanner Behavior

The scanner should handle cases where files may not exist:

**Disk Image** (`pv.qcow2`):
- ✅ **Always exists** - Required for backup
- Scanner must open and analyze this file

**Memory Dump** (`memory.dmp`):
- ⚠️ **May or may not exist** - Optional capture
- Scanner should:
  ```python
  import os
  
  memory_dump_path = vm_artifact["memory_dump"]
  if memory_dump_path and os.path.exists(memory_dump_path):
      # Analyze memory dump
      analyze_memory_dump(memory_dump_path)
  else:
      # Skip memory analysis, log info message
      logger.info(f"Memory dump not available for {vm_name}")
  ```

## Testing

### Test Production Mode (Default)

```bash
# Deploy controller with default settings
kubectl apply -f controller.yaml

# Create ScanInstance
kubectl apply -f scaninstance.yaml

# Check scan job command
kubectl get job threat-scan-scanjob-<name> -n threat-scanning-system -o yaml | grep -A5 args
# Should include: --production
```

### Test Development Mode

```bash
# Update controller deployment
kubectl set env deployment/threat-scanning-controller PRODUCTION=false -n threat-scanning-system

# Restart controller
kubectl rollout restart deployment/threat-scanning-controller -n threat-scanning-system

# Create ScanInstance
kubectl apply -f scaninstance.yaml

# Check scan job command
kubectl get job threat-scan-scanjob-<name> -n threat-scanning-system -o yaml | grep -A5 args
# Should NOT include: --production
```

### Verify ConfigMap Paths

```bash
# Get configmap
kubectl get configmap scan-config-<name> -n threat-scanning-system -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq .

# Should show both paths for each VM:
# {
#   "vm_artifacts": {
#     "vm-name_namespace": {
#       "disk_image": "/triliodata/.../pv.qcow2",
#       "memory_dump": "/triliodata/.../memory.dmp",
#       ...
#     }
#   }
# }
```

## Files Modified

| File | Changes |
|------|---------|
| `pkg/helpers/job_helper.go` | 1. Added memory dump path generation in `GetScanConfigMapData()`<br>2. Added PRODUCTION environment variable logic in `GetScanJob()`<br>3. Added conditional `--production` flag based on env var |

## Environment Variable Summary

| Variable | Default | Source | Purpose |
|----------|---------|--------|---------|
| `PRODUCTION` | `"true"` | Controller deployment | Controls `--production` flag in scan command |

## Command Variations

| PRODUCTION Value | Scan Command |
|------------------|--------------|
| `"true"` (default) | `python3 /app/main.py multi-vm ... --production` |
| `"false"` | `python3 /app/main.py multi-vm ...` |
| Not set | `python3 /app/main.py multi-vm ... --production` (defaults to true) |

## Summary

✅ **Memory dump path** now included in configmap (same directory as disk image, with `memory.dmp` filename)
✅ **PRODUCTION environment variable** controls whether `--production` flag is included
✅ **Default behavior** includes `--production` flag (production mode)
✅ **Testing mode** can be enabled by setting `PRODUCTION=false` in controller deployment
✅ **Code compiles** successfully with all changes

Both features are now ready for deployment and testing!
