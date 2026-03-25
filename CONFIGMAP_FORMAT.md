# ConfigMap Format for Scan Job

## Overview
The scan job ConfigMap follows the `enhanced-soc-analysis` VM artifacts configuration format with complete metadata structure.

### ConfigMap Key Name
- **Key**: `vm_artifacts_configuration.json`
- **Mount Path**: `/config/vm_artifacts_configuration.json` (using subPath)
- **Volume**: Mounted from ConfigMap using subPath to create a single file

## Key Format

### VM Artifact Key: `{vmname}_{namespace}`

- **Pattern**: `<vm-name>_<namespace>`
- **Single Namespace Backup**: Uses `default` if namespace is empty
- **Example**: `web-server_production`, `database-vm_default`

## Complete ConfigMap Structure

### Example ConfigMap Data

```json
{
  "vm_artifacts": {
    "web-server_production": {
      "description": "VM from backup backup-abc123",
      "hostname": "web-server",
      "ip_address": "0.0.0.0",
      "os": "Unknown",
      "memory_dump": "",
      "disk_image": "/triliodata/backups/backup-abc123/production/web-server-boot-pvc",
      "collection_time": "2026-02-23T12:00:00Z",
      "priority": "high",
      "suspected_compromise": true
    },
    "database-vm_production": {
      "description": "VM from backup backup-abc123",
      "hostname": "database-vm",
      "ip_address": "0.0.0.0",
      "os": "Unknown",
      "memory_dump": "",
      "disk_image": "/triliodata/backups/backup-abc123/production/database-vm-boot-pvc",
      "collection_time": "2026-02-23T12:00:00Z",
      "priority": "high",
      "suspected_compromise": true
    }
  }
}
```

## Field Descriptions

| Field | Type | Description | Source | Notes |
|-------|------|-------------|--------|-------|
| **Key** | string | `{vmname}_{namespace}` | Constructed | VM identifier for scan engine |
| `description` | string | VM description | Generated | Format: "VM from backup {backupUID}" |
| `hostname` | string | VM hostname | `VMInfo.VMName` | Actual VM name from backup |
| `ip_address` | string | IP address | Dummy: `"0.0.0.0"` | Not available from backup metadata |
| `os` | string | Operating system | Dummy: `"Unknown"` | Not available from backup metadata |
| `memory_dump` | string | Memory dump path | Empty: `""` | Memory dumps not collected |
| `disk_image` | string | Disk image path | `/triliodata` + `VMInfo.PVCPaths[0]` | **Boot disk only** (first PVC), prefixed with mount point |
| `collection_time` | string | Collection timestamp | Generated | RFC3339 format, UTC |
| `priority` | string | Scan priority | Static: `"high"` | All scans treated as high priority |
| `suspected_compromise` | boolean | Compromise flag | Static: `true` | All VMs treated as potentially compromised |

## Data Flow

### Input: ScanInstance Status

```yaml
status:
  scanLocations:
  - namespace: "production"
    backupUID: "backup-abc123"
    backupPath: "/backups/backup-abc123"
    vms:
    - vmName: "web-server"
      pvcPaths:
      - "/backups/backup-abc123/production/web-server-boot-pvc"
      - "/backups/backup-abc123/production/web-server-data-pvc"
    - vmName: "database-vm"
      pvcPaths:
      - "/backups/backup-abc123/production/database-vm-boot-pvc"
```

### Output: ConfigMap

```json
{
  "vm_artifacts": {
    "web-server_production": {
      "description": "VM from backup backup-abc123",
      "hostname": "web-server",
      "ip_address": "0.0.0.0",
      "os": "Unknown",
      "memory_dump": "",
      "disk_image": "/triliodata/backups/backup-abc123/production/web-server-boot-pvc",
      "collection_time": "2026-02-23T12:00:00Z",
      "priority": "high",
      "suspected_compromise": true
    },
    "database-vm_production": {
      "description": "VM from backup backup-abc123",
      "hostname": "database-vm",
      "ip_address": "0.0.0.0",
      "os": "Unknown",
      "memory_dump": "",
      "disk_image": "/triliodata/backups/backup-abc123/production/database-vm-boot-pvc",
      "collection_time": "2026-02-23T12:00:00Z",
      "priority": "high",
      "suspected_compromise": true
    }
  }
}
```

### Key Transformations

1. **VM Key Construction**:
   - `VMName` = "web-server"
   - `Namespace` = "production"
   - **Result**: "web-server_production"

2. **Disk Image Path Construction**:
   - Input: `"/backups/backup-abc123/production/web-server-boot-pvc"`
   - Add prefix: `/triliodata`
   - **Result**: `"/triliodata/backups/backup-abc123/production/web-server-boot-pvc"`

3. **Boot Disk Filtering**:
   - Input: `["/path/boot", "/path/data", "/path/logs"]`
   - **Result**: `/triliodata/path/boot` (first PVC only, with prefix)

4. **Hostname Assignment**:
   - **Source**: `VMInfo.VMName`
   - **Result**: Same as VM name

5. **Dummy Values**:
   - `ip_address`: "0.0.0.0" (not available)
   - `os`: "Unknown" (not available)
   - `memory_dump`: "" (not collected)

## Examples by Backup Type

### Single Namespace Backup

**Input**:
```yaml
scanLocations:
- namespace: ""  # Empty for single namespace
  backupUID: "backup-123"
  vms:
  - vmName: "app-server"
    pvcPaths: ["/backups/app-server-boot"]
```

**Output**:
```json
{
  "vm_artifacts": {
    "app-server_default": {
      "hostname": "app-server",
      "disk_image": "/triliodata/backups/app-server-boot",
      ...
    }
  }
}
```
**Note**: Uses "default" when namespace is empty, adds `/triliodata` prefix

### Cluster Backup (Multiple Namespaces)

**Input**:
```yaml
scanLocations:
- namespace: "frontend"
  vms:
  - vmName: "nginx"
    pvcPaths: ["/backups/nginx-boot"]
- namespace: "backend"
  vms:
  - vmName: "api-server"
    pvcPaths: ["/backups/api-boot"]
```

**Output**:
```json
{
  "vm_artifacts": {
    "nginx_frontend": {
      "hostname": "nginx",
      "disk_image": "/triliodata/backups/nginx-boot",
      ...
    },
    "api-server_backend": {
      "hostname": "api-server",
      "disk_image": "/triliodata/backups/api-boot",
      ...
    }
  }
}
```

### VM with Multiple Disks (Boot Disk Filtering)

**Input**:
```yaml
vms:
- vmName: "database"
  pvcPaths:
  - "/backups/database-boot-pvc"    # ← Only this one
  - "/backups/database-data-pvc"     # Filtered out
  - "/backups/database-logs-pvc"     # Filtered out
```

**Output**:
```json
{
  "vm_artifacts": {
    "database_production": {
      "hostname": "database",
      "disk_image": "/triliodata/backups/database-boot-pvc",
      ...
    }
  }
}
```

## Scanner Code Usage

### Reading Configuration

```python
import json
import os

# Load configuration from mounted ConfigMap (specific file mount)
with open("/config/vm_artifacts_configuration.json") as f:
    config = json.load(f)

vm_artifacts = config["vm_artifacts"]

# Iterate over VMs to scan
for vm_key, vm_info in vm_artifacts.items():
    hostname = vm_info["hostname"]
    disk_image = vm_info["disk_image"]
    
    print(f"Scanning VM: {hostname} (key: {vm_key})")
    print(f"Disk image: {disk_image}")
    
    # Scan the disk
    scan_disk_image(disk_image, hostname)
```

### Using VM Key for Redis Checkpointing

```python
import redis

redis_url = os.environ["REDIS_URL"]
redis_client = redis.from_url(redis_url)

backup_id = "backup-abc123"

# Track completed VMs using the vm_key
for vm_key, vm_info in vm_artifacts.items():
    # Check if already scanned
    if redis_client.sismember(f"completed_vms:{backup_id}", vm_key):
        print(f"Skipping {vm_key} - already scanned")
        continue
    
    # Scan VM
    scan_vm(vm_info)
    
    # Mark as completed
    redis_client.sadd(f"completed_vms:{backup_id}", vm_key)
    print(f"Completed: {vm_key}")
```

## Kubernetes ConfigMap Example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scan-config-my-scan
  namespace: threat-scanning-system
  labels:
    app.kubernetes.io/name: scan-config
    app.kubernetes.io/component: scan-config
    app.kubernetes.io/managed-by: threat-scanning-controller
    trilio.io/scaninstance-name: my-scan
data:
  vm_artifacts_configuration.json: |
    {
      "vm_artifacts": {
        "web-server_production": {
          "description": "VM from backup backup-abc123",
          "hostname": "web-server",
          "ip_address": "0.0.0.0",
          "os": "Unknown",
          "memory_dump": "",
          "disk_image": "/triliodata/backups/backup-abc123/production/web-server-boot-pvc",
          "collection_time": "2026-02-23T12:00:00Z",
          "priority": "high",
          "suspected_compromise": true
        }
      }
    }
```

## Mount Point in Scan Job

The scan job mounts the ConfigMap as a specific file using subPath:

```yaml
spec:
  containers:
  - name: scanner
    volumeMounts:
    - name: scan-config
      mountPath: /config/vm_artifacts_configuration.json
      subPath: vm_artifacts_configuration.json  # Mount specific file only
      readOnly: true
  volumes:
  - name: scan-config
    configMap:
      name: scan-config-my-scan
```

The scanner can access the configuration at `/config/vm_artifacts_configuration.json` and disk images at `/triliodata/...` paths.

## Verification Commands

```bash
# Get ConfigMap
kubectl get configmap scan-config-my-scan -o yaml

# Extract and prettify JSON
kubectl get configmap scan-config-my-scan \
  -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq .

# List all VMs in config
kubectl get configmap scan-config-my-scan \
  -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq -r '.vm_artifacts | keys[]'

# Show disk images to be scanned
kubectl get configmap scan-config-my-scan \
  -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq -r '.vm_artifacts[].disk_image'

# Show VM keys and hostnames
kubectl get configmap scan-config-my-scan \
  -o jsonpath='{.data.vm_artifacts_configuration\.json}' | \
  jq -r '.vm_artifacts | to_entries[] | "\(.key) -> \(.value.hostname)"'
```

## Field Migration Path

### Current State (v1)
- `ip_address`: Dummy "0.0.0.0"
- `os`: Dummy "Unknown"
- `memory_dump`: Empty ""

### Future Enhancements (v2)
- `ip_address`: Extract from VM metadata or backup annotations
- `os`: Detect from filesystem or backup metadata
- `memory_dump`: Support optional memory dump collection

### Implementation
The format is designed to be forward-compatible. When these fields become available:

```go
// Future enhancement
vmArtifacts[vmKey] = map[string]interface{}{
    "ip_address": extractIPAddress(vm),     // Real IP from metadata
    "os":         detectOS(diskImage),       // Detected OS
    "memory_dump": getMemoryDump(vm),        // Optional memory dump
    // ... other fields unchanged
}
```

Scanner code will continue to work, just with better metadata.

## Notes

1. **VM Key Uniqueness**: The `vmname_namespace` format ensures unique keys even if multiple namespaces have VMs with the same name

2. **Boot Disk Only**: Currently only the first PVC is included in `disk_image`. This matches the requirement to scan boot disks only.

3. **Dummy Values**: Fields like `ip_address` and `os` are populated with dummy values to match the expected format. Scanner code should handle these gracefully.

4. **Empty Memory Dump**: The scanner should skip memory analysis when `memory_dump` is empty.

5. **Timestamp**: `collection_time` is set at ConfigMap creation time, not the actual backup time (which is not available).
