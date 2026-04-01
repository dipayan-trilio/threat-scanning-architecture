# Backup Metadata Integration - Implementation Complete

## Summary

Successfully implemented end-to-end backup metadata flow from backup files through the threat scanning architecture to the scan configuration. This enables the scanning engine to automatically include backup context (UID, target, plan, timestamp) in generated reports for Grafana dashboard analysis.

## Implementation Details

### 1. Prescan Phase Enhancement (Python)

#### File: `datastore-attacher/shared/backup_detection/tvk_detector.py`

**Changes to `_extract_namespace_backup_metadata()`:**
- Extract `backup_creation_timestamp` from `backup.json → metadata.creationTimestamp`
- Extract `backupplan_name` from `backup.json → spec.backupPlan`
- Return values: `backup_creation_timestamp`, `backupplan_name`

**Changes to `_extract_cluster_backup_metadata()`:**
- Extract `backup_creation_timestamp` from `cluster-backup.json → metadata.creationTimestamp`
- Extract `backupplan_name` from `cluster-backup.json → spec.clusterBackupPlan`
- Return values: `backup_creation_timestamp`, `backupplan_name`

#### File: `datastore-attacher/prescan/cli.py`

**Added Annotations:**
```python
annotations = {
    'trilio.io/vm-workload': str(is_vm_workload).lower(),
    'trilio.io/cluster-backup': str(is_cluster_backup).lower(),
    'trilio.io/backup-creation-timestamp': backup_creation_timestamp,
    'trilio.io/backupplan-uid': backupplan_uid,
    'trilio.io/backupplan-name': backupplan_name
}
```

These annotations are applied to the ScanInstance CR after prescan validation completes.

### 2. Controller Enhancement (Go)

#### File: `internal/constants.go`

**Added Constants:**
```go
BackupCreationTimestampAnnotation = "trilio.io/backup-creation-timestamp"
BackupPlanUIDAnnotation = "trilio.io/backupplan-uid"
BackupPlanNameAnnotation = "trilio.io/backupplan-name"
ClusterBackupAnnotation = "trilio.io/cluster-backup"
```

#### File: `pkg/helpers/job_helper.go`

**Modified `GetScanConfigMap(scanInstance *v1.ScanInstance)`:**
- Extracts backup metadata from ScanInstance annotations and spec
- Builds `backupMetadata` map with 5 fields:
  - `backup_uid`: From `spec.BackupRef.UID` (parent backup/cluster-backup UID)
  - `backup_target_name`: From `spec.BackupTarget.Name`
  - `backupplan_uid`: From annotation `trilio.io/backupplan-uid`
  - `backupplan_name`: From annotation `trilio.io/backupplan-name`
  - `backup_timestamp`: From annotation `trilio.io/backup-creation-timestamp`
- Passes `backupMetadata` to `GetScanConfigMapData()`

**Modified `GetScanConfigMapData(scanLocations, backupMetadata)`:**
- Updated function signature to accept `backupMetadata map[string]string`
- Generates JSON structure with new `vm_collection_metadata` section:
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

## Data Flow

```
┌──────────────────────┐
│ Backup Files         │
│ ─────────────────    │
│ backup.json          │
│ cluster-backup.json  │
└──────────┬───────────┘
           │ Prescan reads metadata
           ▼
┌──────────────────────┐
│ ScanInstance CR      │
│ ─────────────────    │
│ Annotations:         │
│  • backup-creation-  │
│    timestamp         │
│  • backupplan-uid    │
│  • backupplan-name   │
│                      │
│ Spec:                │
│  • BackupRef.UID     │
│  • BackupTarget.Name │
└──────────┬───────────┘
           │ Controller reads
           ▼
┌──────────────────────┐
│ ConfigMap            │
│ ─────────────────    │
│ scan-config-{name}   │
│                      │
│ vm_artifacts_        │
│ configuration.json   │
│  ├─ vm_artifacts     │
│  └─ vm_collection_   │
│     metadata         │
│      └─ backup-      │
│         metadata     │
└──────────┬───────────┘
           │ Scan job mounts
           ▼
┌──────────────────────┐
│ Scan Engine          │
│ ─────────────────    │
│ enhanced-soc-        │
│ analysis/main.py     │
│                      │
│ Reads config & adds  │
│ to report            │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Scan Report JSON     │
│ ─────────────────    │
│ backup_metadata: {   │
│   backup_uid,        │
│   backup_target_name,│
│   backup_plan_uid,   │
│   backup_created_at  │
│ }                    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ PostgreSQL DB        │
│ ─────────────────    │
│ • backups table      │
│ • backup_scans table │
│ • Grafana dashboards │
└──────────────────────┘
```

## Key Design Decisions

### 1. Backup UID Source for Cluster Backups
- **Decision**: Use `spec.BackupRef.UID` instead of `scanLocations[0].BackupUID`
- **Rationale**: For cluster backups, `scanLocations` contains child backup UIDs, but we need the parent cluster-backup UID for correlation
- **Result**: Correctly associates all child backup scans with their parent cluster-backup

### 2. Annotation-Based Metadata Transfer
- **Decision**: Store backup metadata in ScanInstance annotations
- **Rationale**: Provides durable, queryable storage that survives controller restarts
- **Result**: Controller can access metadata during ConfigMap creation without re-reading backup files

### 3. ConfigMap Structure
- **Decision**: Nest backup-metadata under `vm_collection_metadata`
- **Rationale**: Matches the structure expected by the existing scan engine (`enhanced-soc-analysis`)
- **Result**: No changes needed to scan engine's config loading logic

## Testing Checklist

- [ ] **Namespace Backup Flow**
  - [ ] Prescan extracts timestamp from backup.json
  - [ ] Prescan extracts backup plan name from backup.json spec.backupPlan
  - [ ] ScanInstance has correct annotations
  - [ ] ConfigMap includes vm_collection_metadata
  - [ ] Scan report includes backup_metadata
  - [ ] PostgreSQL backups table populated

- [ ] **Cluster Backup Flow**
  - [ ] Prescan extracts timestamp from cluster-backup.json
  - [ ] Prescan extracts cluster backup plan name from cluster-backup.json spec.clusterBackupPlan
  - [ ] ScanInstance has correct annotations with cluster-backup UID
  - [ ] ConfigMap includes parent cluster-backup metadata (not child UIDs)
  - [ ] Scan report includes cluster-backup metadata
  - [ ] PostgreSQL backups table uses cluster-backup UID

- [ ] **Edge Cases**
  - [ ] Missing creationTimestamp → annotation is empty string
  - [ ] Missing backup plan name → annotation is empty string
  - [ ] Controller handles missing annotations gracefully
  - [ ] ConfigMap generation skips empty metadata fields
  - [ ] Scan engine handles missing backup-metadata

## Validation Commands

### 1. Check Prescan Annotations
```bash
kubectl get scaninstance <name> -n threat-scanning-system -o yaml | grep -A5 annotations
```

Expected output:
```yaml
annotations:
  trilio.io/backup-creation-timestamp: "2026-02-27T10:00:00Z"
  trilio.io/backupplan-name: "daily-vm-backup"
  trilio.io/backupplan-uid: "bkp_all"
  trilio.io/cluster-backup: "false"
  trilio.io/vm-workload: "true"
```

### 2. Check ConfigMap Structure
```bash
kubectl get configmap scan-config-<name> -n threat-scanning-system -o json | jq '.data["vm_artifacts_configuration.json"] | fromjson | .vm_collection_metadata'
```

Expected output:
```json
{
  "backup-metadata": {
    "backup_uid": "216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",
    "backup_target_name": "s3-prod-target",
    "backupplan_uid": "bkp_all",
    "backupplan_name": "daily-vm-backup",
    "backup_timestamp": "2026-02-27T10:00:00Z"
  }
}
```

### 3. Check Scan Report
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

## Files Modified

### Python (Prescan)
1. `datastore-attacher/shared/backup_detection/tvk_detector.py`
   - Extract backup creation timestamp
   - Extract backup plan name
   - Return extended metadata

2. `datastore-attacher/prescan/cli.py`
   - Add three new annotations to ScanInstance
   - Pass metadata to Kubernetes API

### Go (Controller)
1. `internal/constants.go`
   - Add annotation key constants

2. `pkg/helpers/job_helper.go`
   - Extract metadata from ScanInstance
   - Generate ConfigMap with vm_collection_metadata

## Integration with Grafana Dashboards

This implementation enables the Grafana dashboards to:

1. **Filter by Backup Target**: Use `backup_target_name` for multi-target environments
2. **Filter by Backup Plan**: Use `backupplan_uid` or `backupplan_name` for plan-specific analysis
3. **Threat Evolution Timeline**: Track threats across backups chronologically using `backup_timestamp`
4. **Rescan Tracking**: Correlate multiple scans of the same backup using `backup_uid`

The PostgreSQL schema (`backups`, `backup_scans` tables) is already designed to handle this metadata structure.

## Next Steps

1. Deploy updated controller and datastore-attacher images
2. Create test ScanInstance with both namespace and cluster backups
3. Verify annotations are populated correctly
4. Verify ConfigMap structure matches expected format
5. Run end-to-end scan and verify report contains backup_metadata
6. Load reports into PostgreSQL and test Grafana dashboard filters
