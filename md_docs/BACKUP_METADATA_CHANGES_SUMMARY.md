# Backup Metadata Integration - Change Summary

## Overview
Implemented automatic backup metadata extraction and flow from backup files through the threat scanning architecture to enable Grafana dashboard filtering by backup target and backup plan.

## Changes by Component

### 1. Prescan - Backup Detection (Python)

**File**: `datastore-attacher/shared/backup_detection/tvk_detector.py`

**Function**: `_extract_namespace_backup_metadata()`
- Added extraction of `backup_creation_timestamp` from `backup.json → metadata.creationTimestamp`
- Added extraction of `backupplan_name` from `backup.json → spec.backupPlan`
- Updated return dict with 2 new fields

**Function**: `_extract_cluster_backup_metadata()`
- Added extraction of `backup_creation_timestamp` from `cluster-backup.json → metadata.creationTimestamp`
- Added extraction of `backupplan_name` from `cluster-backup.json → spec.clusterBackupPlan`
- Updated return dict with 2 new fields

**Impact**: +2 dict fields in metadata response

---

### 2. Prescan - CLI (Python)

**File**: `datastore-attacher/prescan/cli.py`

**Changes**:
- Extract 2 new fields from detector metadata: `backupplan_name`, `backup_creation_timestamp`
- Add 3 new annotations to ScanInstance CR:
  - `trilio.io/backup-creation-timestamp`
  - `trilio.io/backupplan-uid`
  - `trilio.io/backupplan-name`

**Before**:
```python
annotations = {
    'trilio.io/vm-workload': str(is_vm_workload).lower(),
    'trilio.io/cluster-backup': str(is_cluster_backup).lower()
}
```

**After**:
```python
annotations = {
    'trilio.io/vm-workload': str(is_vm_workload).lower(),
    'trilio.io/cluster-backup': str(is_cluster_backup).lower(),
    'trilio.io/backup-creation-timestamp': backup_creation_timestamp,
    'trilio.io/backupplan-uid': backupplan_uid,
    'trilio.io/backupplan-name': backupplan_name
}
```

**Impact**: +3 ScanInstance annotations

---

### 3. Controller - Constants (Go)

**File**: `internal/constants.go`

**Changes**: Added 4 new annotation key constants
```go
BackupCreationTimestampAnnotation = "trilio.io/backup-creation-timestamp"
BackupPlanUIDAnnotation = "trilio.io/backupplan-uid"
BackupPlanNameAnnotation = "trilio.io/backupplan-name"
ClusterBackupAnnotation = "trilio.io/cluster-backup"
```

**Impact**: Constants for type-safe annotation key access

---

### 4. Controller - ConfigMap Generation (Go)

**File**: `pkg/helpers/job_helper.go`

**Function**: `GetScanConfigMap(scanInstance *v1.ScanInstance)`

**Changes**: Extract backup metadata and pass to data generation
```go
// NEW: Extract backup metadata from ScanInstance
backupMetadata := make(map[string]string)
if scanInstance.Annotations != nil {
    if timestamp := scanInstance.Annotations[internal.BackupCreationTimestampAnnotation]; timestamp != "" {
        backupMetadata["backup_timestamp"] = timestamp
    }
    if planUID := scanInstance.Annotations[internal.BackupPlanUIDAnnotation]; planUID != "" {
        backupMetadata["backupplan_uid"] = planUID
    }
    if planName := scanInstance.Annotations[internal.BackupPlanNameAnnotation]; planName != "" {
        backupMetadata["backupplan_name"] = planName
    }
}
backupMetadata["backup_uid"] = scanInstance.Spec.BackupRef.UID
backupMetadata["backup_target_name"] = scanInstance.Spec.BackupTarget.Name

// MODIFIED: Pass backupMetadata to data generation
data, err := GetScanConfigMapData(scanInstance.Status.ScanLocations, backupMetadata)
```

**Function**: `GetScanConfigMapData(scanLocations, backupMetadata)`

**Changes**: Updated signature and added metadata section to JSON

**Before**:
```go
func GetScanConfigMapData(scanLocations []v1.ScanLocation) (map[string]string, error) {
    // ...
    data := map[string]interface{}{
        "vm_artifacts": vmArtifacts,
    }
    // ...
}
```

**After**:
```go
func GetScanConfigMapData(scanLocations []v1.ScanLocation, backupMetadata map[string]string) (map[string]string, error) {
    // ...
    data := map[string]interface{}{
        "vm_artifacts": vmArtifacts,
    }
    
    // Add vm_collection_metadata if backup metadata is provided
    if backupMetadata != nil && len(backupMetadata) > 0 {
        vmCollectionMetadata := make(map[string]string)
        // Populate from backupMetadata map...
        if len(vmCollectionMetadata) > 0 {
            data["vm_collection_metadata"] = map[string]interface{}{
                "backup-metadata": vmCollectionMetadata,
            }
        }
    }
    // ...
}
```

**Impact**: ConfigMap JSON structure extended with optional `vm_collection_metadata` section

---

## ConfigMap Structure Change

### Before
```json
{
  "vm_artifacts": {
    "vm-name_namespace": {
      "disk_image": "...",
      "memory_dump": "...",
      ...
    }
  }
}
```

### After
```json
{
  "vm_artifacts": {
    "vm-name_namespace": {
      "disk_image": "...",
      "memory_dump": "...",
      ...
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

---

## Key Implementation Details

### 1. Backup UID Selection

**For Namespace Backups**:
- Source: `spec.BackupRef.UID`
- Value: Namespace backup UID
- Same as: `scanLocations[0].BackupUID`

**For Cluster Backups**:
- Source: `spec.BackupRef.UID`
- Value: **Parent cluster-backup UID** (not child backup UIDs)
- Different from: `scanLocations[i].BackupUID` (which are child UIDs)

**Rationale**: We want to correlate all scans with the top-level backup entity that the user sees in TVK/TVO UI.

### 2. Timestamp Format Handling

**backup.json format**: `"2026-03-27T10:00:00Z"` (ISO 8601)
**Annotation value**: `"2026-03-27T10:00:00Z"` (preserved as-is)
**ConfigMap value**: `"2026-03-27T10:00:00Z"` (preserved as-is)
**Report value**: `"2026-03-27 10:00:00"` (converted by dashboard_report_generator)
**Database value**: `2026-03-27 10:00:00+00` (PostgreSQL TIMESTAMPTZ)

### 3. Field Name Variations

Multiple field name conventions are handled:

| Context | Backup Plan UID | Backup Plan Name | Timestamp |
|---------|----------------|------------------|-----------|
| backup.json | (from path) | `spec.backupPlan` | `metadata.creationTimestamp` |
| Detector metadata | `backupplan_uid` | `backupplan_name` | `backup_creation_timestamp` |
| ScanInstance annotation | `trilio.io/backupplan-uid` | `trilio.io/backupplan-name` | `trilio.io/backup-creation-timestamp` |
| ConfigMap JSON | `backupplan_uid` | `backupplan_name` | `backup_timestamp` |
| Scan report JSON | `backup_plan_uid` | - | `backup_created_at` |
| PostgreSQL column | `backup_plan_uid` | `backup_plan_name` | `created_at` |

**Normalization**: Each layer handles its own format, with transformations at boundaries.

---

## Files Modified

| File | Type | Lines Changed | Purpose |
|------|------|---------------|---------|
| `datastore-attacher/shared/backup_detection/tvk_detector.py` | Python | ~15 | Extract timestamp & plan name |
| `datastore-attacher/prescan/cli.py` | Python | ~5 | Add annotations to ScanInstance |
| `internal/constants.go` | Go | ~12 | Define annotation constants |
| `pkg/helpers/job_helper.go` | Go | ~50 | Extract metadata & update ConfigMap |

**Total**: ~82 lines changed across 4 files

---

## Testing Status

- [x] Python syntax validation (prescan, detector)
- [x] Go compilation (constants, helpers, controllers)
- [x] Go linter checks (no errors)
- [ ] Unit tests (none exist for these components)
- [ ] Integration test (requires deployment)
- [ ] End-to-end test (requires real backup)

---

## Backward Compatibility

✅ **Fully backward compatible**

- Old backups without creationTimestamp: Returns empty string, handled gracefully
- Old ScanInstances without annotations: ConfigMap created without metadata section
- Old scan engine: Ignores `vm_collection_metadata` if not present
- Database: Handles missing backup_metadata with fallbacks

**No breaking changes** - all additions are optional and additive.

---

## Dependencies

### Existing Components (No Changes)
- ✅ Scan engine (`enhanced-soc-analysis/main.py`) - already handles `vm_collection_metadata`
- ✅ Report generator (`dashboard_report_generator.py`) - already processes backup metadata
- ✅ Database setup (`soc_database_setup.py`) - already has `backups` and `backup_scans` tables
- ✅ Grafana dashboards - already query by `backup_target_name` and `backup_plan_uid`

### Integration Points
- ScanInstance CRD: Uses existing annotations field (no CRD changes)
- ConfigMap: Uses existing data structure (backward compatible extension)
- Kubernetes API: Standard annotation patch (no new permissions)

---

## Next Actions

1. **Build & Deploy**:
   - Build updated datastore-attacher image
   - Build updated controller image
   - Deploy to test cluster

2. **Test**:
   - Create test ScanInstance with namespace backup
   - Create test ScanInstance with cluster backup
   - Verify annotations, ConfigMap, reports, database

3. **Validate**:
   - Check Grafana dashboard filters work correctly
   - Verify rescan tracking
   - Test edge cases (missing metadata, empty fields)

4. **Document**:
   - Update deployment docs with new annotations
   - Add troubleshooting guide for metadata issues
   - Update architecture diagrams

---

## Related Documentation

- `BACKUP_METADATA_FLOW.md` - Complete architecture and data flow
- `BACKUP_METADATA_QUICK_REF.md` - Quick reference for annotations and queries
- `BACKUP_METADATA_VISUAL_GUIDE.md` - Visual diagrams and field mappings
- `BACKUP_METADATA_TESTING_GUIDE.md` - Detailed testing scenarios
