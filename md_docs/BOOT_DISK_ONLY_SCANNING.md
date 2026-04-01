# Boot Disk Only Scanning - Implementation

## Overview
Currently, the scan engine only scans boot disks. Until proper boot disk detection logic is implemented, the system uses **first PVC path** as an approximation of the boot disk.

## Design Decision

### **Where Filtering Happens: ConfigMap Creation** ✅

The filtering happens in `GetScanConfigMapData()` function when creating the scan job configuration, NOT in the ScanInstance status.

### **Why This Approach?**

#### 1. **ScanInstance Status = Complete Discovery**
- `ScanInstance.Status.ScanLocations` contains **ALL** PVCs discovered during pre-scan
- Provides complete visibility for debugging and audit
- Users can see all discovered disks via `kubectl get scaninstance <name> -o yaml`

#### 2. **ConfigMap = Execution Plan**
- ConfigMap contains filtered list (boot disk only)
- Scan job only sees what it should scan
- Easy to change filtering logic without CRD changes

#### 3. **Separation of Concerns**
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Pre-scan    │────▶│  Controller  │────▶│   Scan Job   │
│              │     │              │     │              │
│ Discovers    │     │  Filters to  │     │  Scans boot  │
│ ALL PVCs     │     │  boot disk   │     │  disk only   │
└──────────────┘     └──────────────┘     └──────────────┘
      │                     │                     │
      ▼                     ▼                     ▼
  Sets Status          Creates ConfigMap     Reads ConfigMap
  (all PVCs)           (first PVC only)      (boot disk)
```

#### 4. **Future Flexibility**
- **Today**: First PVC (simple heuristic)
- **Near Future**: Proper boot disk detection (analyze metadata, naming patterns)
- **Long Term**: Support scanning all disks, user-selected disks, specific disk types
- **Status format unchanged** - only filtering logic evolves

## Implementation

### Code Change

**File**: `pkg/helpers/job_helper.go`  
**Function**: `GetScanConfigMapData()`

```go
for _, location := range scanLocations {
    for _, vm := range location.VMs {
        // For now, only scan the boot disk (first PVC path)
        // Future: Implement proper boot disk detection logic
        var diskImages []string
        if len(vm.PVCPaths) > 0 {
            // Take only the first PVC path as boot disk approximation
            diskImages = []string{vm.PVCPaths[0]}
        } else {
            // No PVCs found for this VM, skip it
            continue
        }

        vmArtifacts[vm.VMName] = map[string]interface{}{
            "disk_image":           diskImages,  // Array with single element
            "collection_time":      time.Now().UTC().Format(time.RFC3339),
            "priority":             "high",
            "suspected_compromise": true,
        }
    }
}
```

### Data Flow Example

#### ScanInstance Status (All Disks)
```yaml
status:
  scanLocations:
  - namespace: "default"
    backupUID: "backup-123"
    backupPath: "/backups/backup-123"
    vms:
    - vmName: "web-server-vm"
      pvcPaths:
      - "/backups/backup-123/default/web-server-vm-boot-pvc"    # Boot disk
      - "/backups/backup-123/default/web-server-vm-data-pvc"     # Data disk
      - "/backups/backup-123/default/web-server-vm-logs-pvc"     # Logs disk
```

#### ConfigMap (Boot Disk Only)
```json
{
  "vm_artifacts": {
    "web-server-vm": {
      "disk_image": [
        "/backups/backup-123/default/web-server-vm-boot-pvc"
      ],
      "collection_time": "2026-02-23T12:00:00Z",
      "priority": "high",
      "suspected_compromise": true
    }
  }
}
```

**Notice**: 
- Status has **3 PVCs**
- ConfigMap has **1 PVC** (first one only)

## Benefits

### 1. **Transparency**
- Users see all discovered disks in ScanInstance status
- Clear what was scanned vs. what was discovered
- Audit trail preserved

### 2. **Debugging**
- If wrong disk is scanned, easy to see full list in status
- Can identify if boot disk detection needs improvement
- ConfigMap shows exactly what was sent to scanner

### 3. **Easy Migration Path**

**Current State**:
```go
diskImages = []string{vm.PVCPaths[0]}  // First PVC
```

**Future (Proper Detection)**:
```go
diskImages = []string{DetectBootDisk(vm.PVCPaths)}  // Smart detection
```

**Future (Scan All)**:
```go
diskImages = vm.PVCPaths  // All disks
```

**Future (User-Selected)**:
```go
diskImages = FilterByPolicy(vm.PVCPaths, scanPolicy)  // Policy-based
```

### 4. **No CRD Changes Needed**
- ScanInstance CRD format stays same
- Comments in `VMInfo.PVCPaths` already mention future filtering:
  ```go
  // PVCPaths contains the list of PVC paths for this VM
  // For now, includes all VM PVCs (boot disk + data disks)
  // Future: Will be filtered to include only the boot disk
  ```

## Limitations & Assumptions

### Current Limitation
**Assumption**: First PVC in the list is the boot disk

**Why This Works (Usually)**:
1. TVK/TVO likely returns PVCs in consistent order
2. Boot disk often created first (lower creation timestamp)
3. Naming conventions often put boot disk first alphabetically

**Why This Might Fail**:
1. If PVCs are not ordered consistently
2. If boot disk is named differently (e.g., "z-boot" comes after "a-data")
3. If there's no consistent pattern in PVC naming/ordering

### Risk Mitigation
- **Short Term**: Document assumption clearly
- **Medium Term**: Implement proper boot disk detection:
  - Analyze PVC metadata (labels, annotations)
  - Check VM spec for root volume reference
  - Use naming patterns (boot, root, os, system)
  - Check filesystem type (ext4, xfs vs. xfs-data, btrfs-data)

## Future Enhancements

### 1. **Boot Disk Detection Logic**

```go
// DetectBootDisk identifies the boot disk from a list of PVC paths
func DetectBootDisk(pvcPaths []string) string {
    // Strategy 1: Check for explicit markers in path
    for _, path := range pvcPaths {
        if strings.Contains(path, "-boot") || 
           strings.Contains(path, "-root") || 
           strings.Contains(path, "-os") {
            return path
        }
    }
    
    // Strategy 2: Check metadata (future: fetch PVC annotations)
    // ...
    
    // Strategy 3: Filesystem analysis (future: mount and check)
    // ...
    
    // Fallback: Return first PVC
    if len(pvcPaths) > 0 {
        return pvcPaths[0]
    }
    return ""
}
```

### 2. **Configurable Scan Policy**

```go
type ScanPolicy struct {
    ScanBootDiskOnly bool
    ScanAllDisks     bool
    IncludePatterns  []string  // e.g., ["*-boot-*", "*-root-*"]
    ExcludePatterns  []string  // e.g., ["*-data-*", "*-logs-*"]
}

func FilterByPolicy(pvcPaths []string, policy ScanPolicy) []string {
    if policy.ScanAllDisks {
        return pvcPaths
    }
    
    if policy.ScanBootDiskOnly {
        return []string{DetectBootDisk(pvcPaths)}
    }
    
    // Apply include/exclude patterns
    // ...
}
```

### 3. **Per-VM Scan Configuration**

```yaml
# Future ScanInstance spec
spec:
  scanPolicy:
    defaultPolicy: bootDiskOnly
    vmOverrides:
    - vmName: "database-vm"
      scanAllDisks: true  # Database VM needs all disks scanned
    - vmName: "web-server"
      scanDisks: ["boot", "config"]  # Specific disks only
```

## Testing

### Test Case 1: Single Disk VM
```yaml
# Input (Status)
vms:
- vmName: "simple-vm"
  pvcPaths: ["/path/to/single-disk"]

# Output (ConfigMap)
"simple-vm": {
  "disk_image": ["/path/to/single-disk"]
}
```
✅ **Expected**: Single disk scanned

### Test Case 2: Multi-Disk VM
```yaml
# Input (Status)
vms:
- vmName: "complex-vm"
  pvcPaths: 
  - "/path/to/boot-disk"
  - "/path/to/data-disk"
  - "/path/to/logs-disk"

# Output (ConfigMap)
"complex-vm": {
  "disk_image": ["/path/to/boot-disk"]
}
```
✅ **Expected**: Only first disk (boot) scanned

### Test Case 3: Zero Disks VM
```yaml
# Input (Status)
vms:
- vmName: "no-disks-vm"
  pvcPaths: []

# Output (ConfigMap)
# VM not included in config
```
✅ **Expected**: VM skipped (no disk_image array)

### Verification Commands

```bash
# Check all discovered disks
kubectl get scaninstance my-scan -o jsonpath='{.status.scanLocations[0].vms[0].pvcPaths}' | jq .

# Check what's being scanned
kubectl get configmap scan-config-my-scan -o jsonpath='{.data.config\.json}' | jq '.vm_artifacts'

# Compare discovered vs. scanned
echo "=== Discovered (Status) ==="
kubectl get scaninstance my-scan -o jsonpath='{.status.scanLocations[*].vms[*].pvcPaths}' | jq .

echo "=== Scanned (ConfigMap) ==="
kubectl get configmap scan-config-my-scan -o jsonpath='{.data.config\.json}' | jq '.vm_artifacts[].disk_image'
```

## Documentation Updates Needed

### User-Facing Docs
- Document current limitation (first PVC = boot disk assumption)
- Recommend consistent PVC naming conventions
- Explain future roadmap for boot disk detection

### Developer Docs
- Document where filtering happens (ConfigMap creation)
- Explain rationale for this design
- Provide guidance for implementing proper boot disk detection

## Summary

| Aspect | Current Implementation | Future Enhancement |
|--------|----------------------|-------------------|
| **Where filtering happens** | ConfigMap creation | Same |
| **Detection method** | First PVC | Smart detection (metadata, naming) |
| **What's stored in Status** | All PVCs | All PVCs (unchanged) |
| **What's in ConfigMap** | First PVC only | Detected boot disk(s) |
| **User visibility** | All disks visible in Status | Same |
| **Flexibility** | Easy to change logic | Policy-based scanning |

✅ **Recommendation**: Filter at ConfigMap creation time (already implemented)  
✅ **Current approach**: Take first PVC as boot disk approximation  
✅ **Future proof**: Easy to enhance without breaking changes
