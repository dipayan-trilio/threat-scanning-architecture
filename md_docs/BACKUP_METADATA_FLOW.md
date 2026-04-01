# Backup Metadata Flow: End-to-End Integration

## Overview

This document describes the complete flow of backup metadata from the backup files through prescan, controller, and finally into the scan configuration that is consumed by the threat scanning engine.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 1: PRESCAN PHASE (Python)                                      │
│                                                                       │
│  backup.json / cluster-backup.json                                  │
│  ├─ metadata.creationTimestamp  ───────┐                            │
│  └─ spec.backupPlan / clusterBackupPlan ─┐                          │
│                                            │                          │
│  TVKBackupDetector.extract_metadata()    │                          │
│  ├─ Extracts: backup_creation_timestamp  │                          │
│  ├─ Extracts: backupplan_uid (from path) │                          │
│  └─ Extracts: backupplan_name (from spec)│                          │
│                                            │                          │
│  prescan/cli.py                            │                          │
│  └─ Patches ScanInstance with annotations:│                          │
│     ├─ trilio.io/backup-creation-timestamp ◄──┘                      │
│     ├─ trilio.io/backupplan-uid                                      │
│     └─ trilio.io/backupplan-name                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 2: CONTROLLER (Go)                                              │
│                                                                       │
│  ScanInstance Reconciler                                             │
│  ├─ Reads annotations:                                               │
│  │  ├─ trilio.io/backup-creation-timestamp                           │
│  │  ├─ trilio.io/backupplan-uid                                      │
│  │  └─ trilio.io/backupplan-name                                     │
│  │                                                                    │
│  ├─ Reads from spec/status:                                          │
│  │  ├─ spec.BackupTarget.Name  → backup_target_name                 │
│  │  └─ status.ScanLocations[0].BackupUID → backup_uid               │
│  │                                                                    │
│  └─ Calls helpers.GetScanConfigMap()                                 │
│     └─ Builds backupMetadata map:                                    │
│        ├─ backup_uid                                                 │
│        ├─ backup_target_name                                         │
│        ├─ backupplan_uid                                             │
│        ├─ backupplan_name                                            │
│        └─ backup_timestamp                                           │
│                                                                       │
│  helpers.GetScanConfigMapData()                                      │
│  └─ Generates JSON with:                                             │
│     ├─ vm_artifacts: {...}                                           │
│     └─ vm_collection_metadata:                                       │
│        └─ backup-metadata:                                           │
│           ├─ backup_uid                                              │
│           ├─ backup_target_name                                      │
│           ├─ backupplan_uid                                          │
│           ├─ backupplan_name                                         │
│           └─ backup_timestamp                                        │
│                                                                       │
│  Creates ConfigMap → scan-config-{scaninstance-name}                 │
│  └─ data["vm_artifacts_configuration.json"] = <JSON above>           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 3: SCAN JOB (Python - enhanced-soc-analysis)                   │
│                                                                       │
│  main.py reads /config/vm_artifacts_configuration.json              │
│  ├─ Loads vm_collection_metadata.backup-metadata                    │
│  └─ Passes to DashboardReportGenerator                               │
│                                                                       │
│  dashboard_report_generator.py                                       │
│  └─ Includes backup-metadata in generated scan report JSON           │
│                                                                       │
│  Output: scan_report_<timestamp>_<scan_id>.json                     │
│  └─ Contains: backup_metadata section for PostgreSQL ingestion       │
└─────────────────────────────────────────────────────────────────────┘
```

## Changes Summary

### 1. Prescan Phase (Python)

**File: `datastore-attacher/shared/backup_detection/tvk_detector.py`**

#### Namespace Backup Extraction (`_extract_namespace_backup_metadata`)
- Reads `backup.json` from backup directory
- Extracts `metadata.creationTimestamp` → `backup_creation_timestamp`
- Extracts `spec.backupPlan` → `backupplan_name`
- Returns extended metadata dict with new fields

#### Cluster Backup Extraction (`_extract_cluster_backup_metadata`)
- Reads `cluster-backup.json` from backup directory
- Extracts `metadata.creationTimestamp` → `backup_creation_timestamp`
- Extracts `spec.clusterBackupPlan` → `backupplan_name`
- Returns extended metadata dict with new fields

**File: `datastore-attacher/prescan/cli.py`**

- Receives extended metadata from detector
- Adds three new annotations to ScanInstance:
  ```python
  annotations = {
      'trilio.io/vm-workload': str(is_vm_workload).lower(),
      'trilio.io/cluster-backup': str(is_cluster_backup).lower(),
      'trilio.io/backup-creation-timestamp': backup_creation_timestamp,
      'trilio.io/backupplan-uid': backupplan_uid,
      'trilio.io/backupplan-name': backupplan_name
  }
  ```

### 2. Controller (Go)

**File: `internal/constants.go`**

Added annotation key constants:
```go
BackupCreationTimestampAnnotation = "trilio.io/backup-creation-timestamp"
BackupPlanUIDAnnotation = "trilio.io/backupplan-uid"
BackupPlanNameAnnotation = "trilio.io/backupplan-name"
ClusterBackupAnnotation = "trilio.io/cluster-backup"
```

**File: `pkg/helpers/job_helper.go`**

#### `GetScanConfigMap(scanInstance *v1.ScanInstance)` (Modified)
- Extracts backup metadata from ScanInstance annotations
- Builds `backupMetadata` map with:
  - `backup_timestamp` from `trilio.io/backup-creation-timestamp` annotation
  - `backupplan_uid` from `trilio.io/backupplan-uid` annotation
  - `backupplan_name` from `trilio.io/backupplan-name` annotation
  - `backup_uid` from `status.ScanLocations[0].BackupUID`
  - `backup_target_name` from `spec.BackupTarget.Name`
- Passes `backupMetadata` to `GetScanConfigMapData`

#### `GetScanConfigMapData(scanLocations, backupMetadata)` (Modified)
- Function signature updated to accept `backupMetadata map[string]string`
- Builds complete config JSON structure:
  ```json
  {
    "vm_artifacts": {...},
    "vm_collection_metadata": {
      "backup-metadata": {
        "backup_uid": "...",
        "backup_target_name": "...",
        "backupplan_uid": "...",
        "backupplan_name": "...",
        "backup_timestamp": "..."
      }
    }
  }
  ```

## Data Flow by Backup Type

### Single Namespace Backup
```
backup.json
├─ metadata.creationTimestamp → annotation → ConfigMap → vm_config.json
├─ metadata.uid → status.scanLocations → ConfigMap → vm_config.json
└─ spec.backupPlan → annotation → ConfigMap → vm_config.json
```

### Cluster Backup
```
cluster-backup.json
├─ metadata.creationTimestamp → annotation → ConfigMap → vm_config.json
├─ metadata.uid → status.scanLocations → ConfigMap → vm_config.json
└─ spec.clusterBackupPlan → annotation → ConfigMap → vm_config.json
```

## Configuration Examples

### ConfigMap Data Structure

The generated ConfigMap `scan-config-{scaninstance-name}` contains:

```json
{
  "vm_artifacts": {
    "vm-ubuntu-22_default": {
      "description": "VM from backup 216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",
      "hostname": "vm-ubuntu-22",
      "ip_address": "0.0.0.0",
      "os": "Unknown",
      "memory_dump": "/triliodata/bkp_all/216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e/custom/data-snapshot/vol-boot/memory.dmp",
      "disk_image": "/triliodata/bkp_all/216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e/custom/data-snapshot/vol-boot/pv.qcow2",
      "collection_time": "2026-03-27T15:30:00Z",
      "priority": "high",
      "suspected_compromise": true
    }
  },
  "vm_collection_metadata": {
    "backup-metadata": {
      "backup_uid": "216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",
      "backup_target_name": "s3-prod-target",
      "backupplan_uid": "bkp_all",
      "backupplan_name": "daily-vm-backup",
      "backup_timestamp": "2026-02-27T10:00:00Z"
    }
  }
}
```

### ScanInstance Annotations (After Prescan)

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: scan-xyz
  annotations:
    trilio.io/vm-workload: "true"
    trilio.io/cluster-backup: "false"
    trilio.io/backup-creation-timestamp: "2026-02-27T10:00:00Z"
    trilio.io/backupplan-uid: "bkp_all"
    trilio.io/backupplan-name: "daily-vm-backup"
spec:
  backupTarget:
    name: s3-prod-target
  backupRef:
    uid: 216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e
    path: /bkp_all/216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e
status:
  scanLocations:
  - backupUID: 216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e
    backupPath: bkp_all/216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e
    namespace: ""
    vms:
    - vmName: vm-ubuntu-22
      pvcPaths:
      - /bkp_all/216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e/custom/data-snapshot/vol-boot
```

## Scan Report Integration

The scan engine (`enhanced-soc-analysis/main.py`) reads the ConfigMap-mounted JSON file and automatically includes the `backup-metadata` in generated reports:

```json
{
  "scan_id": "SCAN-20260330-153151-multi-vm",
  "backup_metadata": {
    "backup_uid": "216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",
    "backup_target_name": "s3-prod-target",
    "backup_plan_uid": "bkp_all",
    "backup_created_at": "2026-02-27 10:00:00"
  },
  "summary": {...},
  "threats": {...}
}
```

## PostgreSQL Ingestion

The `soc_database_setup.py` script processes these reports and populates:

1. **`backups` table**: Stores unique backups with target/plan info
2. **`scans` table**: Links to `backups.backup_uid`
3. **`backup_scans` table**: Tracks rescans with `scan_number` and `is_latest`

## Benefits

1. **Automatic Metadata Flow**: No manual configuration needed
2. **Source of Truth**: Backup metadata comes directly from TVK/TVO backup files
3. **Grafana Dashboard Support**: Enables filtering by backup target, backup plan
4. **Rescan Detection**: Tracks multiple scans of the same backup
5. **Cluster Backup Support**: Handles both namespace and cluster-level backups correctly

## Testing

### 1. Verify Prescan Annotations

After prescan completes, check ScanInstance:

```bash
kubectl get scaninstance scan-xyz -o jsonpath='{.metadata.annotations}' | jq
```

Expected output:
```json
{
  "trilio.io/backup-creation-timestamp": "2026-02-27T10:00:00Z",
  "trilio.io/backupplan-uid": "bkp_all",
  "trilio.io/backupplan-name": "daily-vm-backup",
  "trilio.io/cluster-backup": "false",
  "trilio.io/vm-workload": "true"
}
```

### 2. Verify ConfigMap Content

After scan ConfigMap is created:

```bash
kubectl get configmap scan-config-scan-xyz -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq
```

Expected output includes:
```json
{
  "vm_artifacts": {...},
  "vm_collection_metadata": {
    "backup-metadata": {
      "backup_uid": "216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",
      "backup_target_name": "s3-prod-target",
      "backupplan_uid": "bkp_all",
      "backupplan_name": "daily-vm-backup",
      "backup_timestamp": "2026-02-27T10:00:00Z"
    }
  }
}
```

### 3. Verify Generated Report

After scan job completes, check the generated report:

```bash
cat dashboard_reports/scan_report_*.json | jq '.backup_metadata'
```

Expected output:
```json
{
  "backup_uid": "216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",
  "backup_target_name": "s3-prod-target",
  "backup_plan_uid": "bkp_all",
  "backup_created_at": "2026-02-27 10:00:00"
}
```

### 4. Verify PostgreSQL Data

After running `soc_database_setup.py`:

```sql
-- Check backups table
SELECT * FROM backups;

-- Check backup_scans table
SELECT bs.*, b.backup_target_name, b.backup_plan_name
FROM backup_scans bs
JOIN backups b ON bs.backup_uid = b.backup_uid
ORDER BY b.created_at DESC, bs.scan_number DESC;

-- Verify latest scan flag
SELECT backup_uid, scan_id, scan_number, is_latest
FROM backup_scans
WHERE backup_uid = '216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e'
ORDER BY scan_number DESC;
```

## File Changes

### Python Files
1. `datastore-attacher/shared/backup_detection/tvk_detector.py`
   - Extract `backup_creation_timestamp` from backup.json metadata
   - Extract `backupplan_name` from backup.json spec
   - Return extended metadata dict

2. `datastore-attacher/prescan/cli.py`
   - Add three new annotations to ScanInstance
   - Pass extracted metadata to Kubernetes API

### Go Files
1. `internal/constants.go`
   - Add annotation key constants

2. `pkg/helpers/job_helper.go`
   - Update `GetScanConfigMap` to extract metadata from ScanInstance
   - Update `GetScanConfigMapData` to include `vm_collection_metadata`

## Backward Compatibility

- If annotations are missing, the flow continues without metadata
- ConfigMap generation gracefully handles missing fields
- Scan engine already handles missing `backup-metadata` (optional field)
- Database ingestion provides fallback values for missing metadata

## Future Enhancements

1. Add backup plan labels to ScanInstance for easier querying
2. Include backup size/duration in metadata
3. Support TVO backup metadata extraction (currently TVK only)
4. Add validation for timestamp format consistency
