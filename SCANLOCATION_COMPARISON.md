# ScanLocation Structure Comparison

## Before (PVC Paths Only)

```json
{
  "status": {
    "type": "TVK",
    "scanLocations": [
      {
        "namespace": "dp",
        "backupUID": "1bbba2bd-a28c-4691-a588-284ac26f97f9",
        "backupPath": "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9",
        "pvcPaths": [
          "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9/custom/data-snapshot/vol-src-as-dv",
          "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9/custom/data-snapshot/vol-src-pvc"
        ]
      }
    ]
  }
}
```

### Issues:
- ❌ No VM name information
- ❌ No PVC name (embedded in path but needs parsing)
- ❌ Can't easily identify which VM owns which PVC
- ❌ Need to parse path to extract PVC name

## After (Rich VM PVC Metadata)

```json
{
  "status": {
    "type": "TVK",
    "scanLocations": [
      {
        "namespace": "dp",
        "backupUID": "1bbba2bd-a28c-4691-a588-284ac26f97f9",
        "backupPath": "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9",
        "vmPVCs": [
          {
            "vmName": "vm-test",
            "pvcName": "vol-src-as-dv",
            "pvcPath": "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9/custom/data-snapshot/vol-src-as-dv"
          },
          {
            "vmName": "vm-test",
            "pvcName": "vol-src-pvc",
            "pvcPath": "35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9/custom/data-snapshot/vol-src-pvc"
          }
        ]
      }
    ]
  }
}
```

### Benefits:
- ✅ VM name explicitly available (`vm-test`)
- ✅ PVC name explicitly available (`vol-src-as-dv`, `vol-src-pvc`)
- ✅ Easy to identify both PVCs belong to same VM (`vm-test`)
- ✅ No path parsing needed
- ✅ Better for logging and debugging
- ✅ Easier to implement boot disk filtering (future)

## Controller Usage Example

### Before (with pvcPaths)

```go
for _, scanLoc := range scanInstance.Status.ScanLocations {
    for _, pvcPath := range scanLoc.PVCPaths {
        // Need to parse pvcPath to extract PVC name
        pvcName := extractPVCNameFromPath(pvcPath)
        
        // No way to know VM name
        logger.Info("Scanning PVC", "pvc", pvcName, "path", pvcPath)
        
        createScanJob(scanLoc, pvcPath)
    }
}
```

### After (with vmPVCs)

```go
for _, scanLoc := range scanInstance.Status.ScanLocations {
    for _, vmPVC := range scanLoc.VMPVCs {
        // All metadata directly available!
        logger.Info("Scanning VM PVC", 
            "vm", vmPVC.VMName, 
            "pvc", vmPVC.PVCName, 
            "path", vmPVC.PVCPath)
        
        // Can group by VM, filter by PVC name, etc.
        createScanJob(scanLoc, vmPVC)
    }
}
```

## Real-World Example: Multi-VM Cluster Backup

```json
{
  "status": {
    "type": "TVK",
    "scanLocations": [
      {
        "namespace": "database",
        "backupUID": "abc-123",
        "backupPath": "plan1/abc-123",
        "vmPVCs": [
          {
            "vmName": "postgres-primary",
            "pvcName": "postgres-primary-boot",
            "pvcPath": "plan1/abc-123/custom/data-snapshot/postgres-primary-boot"
          },
          {
            "vmName": "postgres-primary",
            "pvcName": "postgres-primary-data",
            "pvcPath": "plan1/abc-123/custom/data-snapshot/postgres-primary-data"
          },
          {
            "vmName": "postgres-replica",
            "pvcName": "postgres-replica-boot",
            "pvcPath": "plan1/abc-123/custom/data-snapshot/postgres-replica-boot"
          }
        ]
      },
      {
        "namespace": "frontend",
        "backupUID": "def-456",
        "backupPath": "plan1/def-456",
        "vmPVCs": [
          {
            "vmName": "web-server-1",
            "pvcName": "web-server-1-boot",
            "pvcPath": "plan1/def-456/custom/data-snapshot/web-server-1-boot"
          },
          {
            "vmName": "web-server-2",
            "pvcName": "web-server-2-boot",
            "pvcPath": "plan1/def-456/custom/data-snapshot/web-server-2-boot"
          }
        ]
      }
    ]
  }
}
```

### Insights from this structure:
1. **Database namespace** has 2 VMs:
   - `postgres-primary` with 2 PVCs (boot + data)
   - `postgres-replica` with 1 PVC (boot only)
   
2. **Frontend namespace** has 2 VMs:
   - `web-server-1` with 1 PVC (boot only)
   - `web-server-2` with 1 PVC (boot only)

3. **Total**: 4 VMs across 2 namespaces with 5 PVCs to scan

All of this is immediately clear from the structure without any parsing or guessing!
