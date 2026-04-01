# ConfigMap File Mount Update

## Overview

Updated the scan job ConfigMap mounting to use a specific file name (`vm_artifacts_configuration.json`) and mount it as a single file using `subPath` instead of mounting the entire ConfigMap directory.

## Changes Made

### 1. ConfigMap Key Name
**File**: `pkg/helpers/job_helper.go` - `GetScanConfigMapData()`

Changed the ConfigMap data key from `config.json` to `vm_artifacts_configuration.json`:

```go
// Before
return map[string]string{
    "config.json": string(jsonData),
}, nil

// After
return map[string]string{
    "vm_artifacts_configuration.json": string(jsonData),
}, nil
```

### 2. Volume Mount with SubPath
**File**: `pkg/helpers/job_helper.go` - `GetScanJob()`

Updated the volume mount to use `subPath` for mounting a specific file:

```go
// Before
VolumeMounts: []corev1.VolumeMount{
    {
        Name:      "scan-config",
        MountPath: "/config",
        ReadOnly:  true,
    },
}

// After
VolumeMounts: []corev1.VolumeMount{
    {
        Name:      "scan-config",
        MountPath: "/config/vm_artifacts_configuration.json",
        SubPath:   "vm_artifacts_configuration.json",
        ReadOnly:  true,
    },
}
```

## Benefits

### 1. **Specific File Mounting**
- Only mounts the required file, not the entire ConfigMap
- Cleaner pod filesystem structure
- File path matches the exact name expected by scan engine

### 2. **Consistency with Scan Engine**
- Matches the expected configuration file name format
- No ambiguity about which file to read
- Aligns with `enhanced-soc-analysis` expectations

### 3. **Prevents Directory Clutter**
- Without `subPath`, mounting at `/config` creates a directory with `vm_artifacts_configuration.json` inside
- With `subPath`, the file is directly accessible at `/config/vm_artifacts_configuration.json`

### 4. **Kubernetes Best Practice**
- Using `subPath` for single file mounts is a standard pattern
- Prevents the ConfigMap from overwriting other files in `/config` directory

## How SubPath Works

### Without SubPath (Before)
```
/config/
  └── vm_artifacts_configuration.json  # File inside directory
```

Scan command would need:
```bash
python3 main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json
```

### With SubPath (After)
```
/config/vm_artifacts_configuration.json  # Direct file mount
```

Scan command:
```bash
python3 main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json
```

The path works the same, but the file is mounted directly rather than as part of a directory.

## ConfigMap Structure

The ConfigMap now looks like:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scan-config-<scaninstance-name>
  namespace: threat-scanning-system
data:
  vm_artifacts_configuration.json: |
    {
      "vm_artifacts": {
        "vm-name_namespace": {
          "hostname": "vm-name",
          "disk_image": "/triliodata/path/to/disk",
          ...
        }
      }
    }
```

## Pod Volume Specification

```yaml
spec:
  containers:
  - name: scanner
    volumeMounts:
    - name: scan-config
      mountPath: /config/vm_artifacts_configuration.json
      subPath: vm_artifacts_configuration.json
      readOnly: true
  volumes:
  - name: scan-config
    configMap:
      name: scan-config-<scaninstance-name>
```

## Verification

Check the mounted file in the pod:

```bash
# Exec into scan job pod
kubectl exec -it <scan-job-pod> -- bash

# Verify file exists
ls -la /config/vm_artifacts_configuration.json

# View contents
cat /config/vm_artifacts_configuration.json | jq .

# Verify it's a file, not a directory
file /config/vm_artifacts_configuration.json
# Output: /config/vm_artifacts_configuration.json: ASCII text
```

## Compatibility

This change is **fully compatible** with the scan engine command:

```bash
python3 /app/main.py multi-vm /app/config/minimal_working.json /config/vm_artifacts_configuration.json --production
```

The file is accessible at the exact path specified in the command.

## Files Updated

1. **pkg/helpers/job_helper.go**
   - `GetScanConfigMapData()`: Changed key to `vm_artifacts_configuration.json`
   - `GetScanJob()`: Updated VolumeMount to use `subPath`

2. **Documentation**
   - `SCAN_JOB_MOUNT_AND_SCAN.md`: Updated to reflect subPath mounting
   - `CONFIGMAP_FORMAT.md`: Updated examples and verification commands

## Testing Checklist

- [x] ConfigMap created with correct key name
- [x] Volume mount uses subPath
- [x] File accessible at `/config/vm_artifacts_configuration.json`
- [x] Scan command uses correct file path
- [x] Build succeeds without errors
- [x] Documentation updated

## Rollout

When the updated controller is deployed:

1. **New ScanInstances**: Will create ConfigMaps with the new key name
2. **Existing ScanInstances**: 
   - Existing ConfigMaps remain unchanged
   - New scans will use the new format
   - Old ConfigMaps can be cleaned up by janitor service

## Notes

- **Read-Only Mount**: File is mounted read-only for security
- **ConfigMap Updates**: If ConfigMap is updated, pod must be restarted to see changes (Kubernetes behavior)
- **SubPath Limitation**: Cannot use ConfigMap automatic updates with subPath (not an issue as we don't update ConfigMaps)
