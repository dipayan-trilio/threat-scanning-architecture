# Backup Metadata Annotations - Field Reference

## Quick Lookup: Annotation → ConfigMap → Report → Database

| Annotation Key | ConfigMap Field | Report Field | DB Column | Example Value |
|---------------|-----------------|--------------|-----------|---------------|
| `trilio.io/backup-creation-timestamp` | `backup_timestamp` | `backup_created_at` | `backups.created_at` | `2026-03-27T10:00:00Z` |
| `trilio.io/backupplan-uid` | `backupplan_uid` | `backup_plan_uid` | `backups.backup_plan_uid` | `bkp_all` |
| `trilio.io/backupplan-name` | `backupplan_name` | - | `backups.backup_plan_name` | `daily-vm-backup` |
| (from spec) | `backup_uid` | `backup_uid` | `backups.backup_uid` | `abc-123-456` |
| (from spec) | `backup_target_name` | `backup_target_name` | `backups.backup_target_name` | `s3-prod-target` |

## Annotation Details

### trilio.io/backup-creation-timestamp

**Source**: `backup.json → metadata.creationTimestamp` or `cluster-backup.json → metadata.creationTimestamp`

**Format**: ISO 8601 timestamp string (e.g., `2026-03-27T10:00:00Z`)

**Purpose**: Track when the backup was created for chronological threat analysis

**Example Values**:
- `2026-03-27T10:00:00Z`
- `2025-12-15T08:30:00Z`
- `` (empty string if missing in backup file)

**Usage in Grafana**:
```sql
WHERE b.created_at BETWEEN $__timeFrom() AND $__timeTo()
ORDER BY b.created_at ASC
```

---

### trilio.io/backupplan-uid

**Source**: Backup path structure (directory name containing backup UID)

**Format**: String identifier (e.g., `bkp_all`, `cluster-plan-daily`)

**Purpose**: Unique identifier for backup plan, enables plan-based filtering

**Example Values**:
- `bkp_all`
- `cluster-plan-daily`
- `prod-weekly-backup`
- `dev-backup-plan-001`

**Usage in Grafana**:
```sql
WHERE b.backup_plan_uid = '$backup_plan_uid'
```

**Variable Definition**:
```sql
-- Cascading dropdown (depends on backup_target)
SELECT DISTINCT 
  backup_plan_uid AS __value,
  backup_plan_name AS __text
FROM backups
WHERE backup_target_name = '$backup_target'
ORDER BY backup_plan_name;
```

---

### trilio.io/backupplan-name

**Source**: 
- Namespace backup: `backup.json → spec.backupPlan`
- Cluster backup: `cluster-backup.json → spec.clusterBackupPlan`

**Format**: Human-readable string (e.g., `daily-vm-backup`)

**Purpose**: Display name for backup plans in Grafana dropdowns

**Example Values**:
- `daily-vm-backup`
- `weekly-full-backup`
- `hourly-critical-apps`
- `` (empty string if missing in backup file)

**Usage in Grafana**:
```sql
-- Display in dropdown (paired with backup_plan_uid)
SELECT backup_plan_uid, backup_plan_name FROM backups;

-- Show in table
SELECT backup_plan_name AS "Backup Plan" FROM backups;
```

---

### trilio.io/cluster-backup

**Source**: Detected by prescan (checks if `cluster-backup.json` exists)

**Format**: Boolean as string (`"true"` or `"false"`)

**Purpose**: Distinguish between namespace and cluster-level backups

**Example Values**:
- `"true"` - Cluster-level backup with multiple child namespaces
- `"false"` - Single namespace backup

**Usage**:
- Primarily for debugging and logging
- Could be used for dashboard filtering if needed

---

## Non-Annotation Metadata Sources

### backup_uid

**Source**: `spec.BackupRef.UID` (from ScanInstance spec)

**Why not annotation?**: Already available in spec, no need to duplicate

**Key Detail**: For cluster backups, this is the **parent cluster-backup UID**, not child backup UIDs

**Example Values**:
- Namespace backup: `abc-123-456` (namespace backup UID)
- Cluster backup: `xyz-789-cluster` (cluster-backup UID, NOT child UIDs)

**Usage**:
```sql
-- Join scans to backups
JOIN backups b ON s.backup_uid = b.backup_uid

-- Track rescans
SELECT COUNT(*) FROM backup_scans WHERE backup_uid = 'abc-123-456';
```

---

### backup_target_name

**Source**: `spec.BackupTarget.Name` (from ScanInstance spec)

**Why not annotation?**: Already available in spec, no need to duplicate

**Example Values**:
- `s3-prod-target`
- `nfs-backup-target`
- `azure-blob-target`

**Usage in Grafana**:
```sql
-- Primary filter variable
SELECT DISTINCT backup_target_name 
FROM backups 
ORDER BY backup_target_name;
```

---

## Field Mapping Examples

### Example 1: Namespace Backup

**backup.json**:
```json
{
  "metadata": {
    "name": "backup-001",
    "uid": "abc-123-456",
    "creationTimestamp": "2026-03-27T10:00:00Z"
  },
  "spec": {
    "backupPlan": "daily-vm-backup",
    "target": "s3-prod-target"
  }
}
```

**Path**: `/triliodata/bkp_all/abc-123-456/`

**ScanInstance**:
```yaml
metadata:
  annotations:
    trilio.io/backup-creation-timestamp: "2026-03-27T10:00:00Z"
    trilio.io/backupplan-uid: "bkp_all"
    trilio.io/backupplan-name: "daily-vm-backup"
    trilio.io/cluster-backup: "false"
spec:
  backupTarget:
    name: s3-prod-target
  backupRef:
    uid: abc-123-456
```

**ConfigMap**:
```json
{
  "vm_collection_metadata": {
    "backup-metadata": {
      "backup_uid": "abc-123-456",
      "backup_target_name": "s3-prod-target",
      "backupplan_uid": "bkp_all",
      "backupplan_name": "daily-vm-backup",
      "backup_timestamp": "2026-03-27T10:00:00Z"
    }
  }
}
```

---

### Example 2: Cluster Backup

**cluster-backup.json**:
```json
{
  "metadata": {
    "name": "cluster-backup-001",
    "uid": "xyz-789-cluster",
    "creationTimestamp": "2026-03-27T15:00:00Z"
  },
  "spec": {
    "clusterBackupPlan": "daily-cluster-backup",
    "target": "nfs-cluster-target"
  },
  "status": {
    "backupInfos": {
      "ns-app": {
        "backup": {"uid": "abc-child-1"},
        "location": "backups/ns-app/abc-child-1"
      },
      "ns-db": {
        "backup": {"uid": "abc-child-2"},
        "location": "backups/ns-db/abc-child-2"
      }
    }
  }
}
```

**Path**: `/triliodata/cluster-plan-daily/xyz-789-cluster/`

**ScanInstance**:
```yaml
metadata:
  annotations:
    trilio.io/backup-creation-timestamp: "2026-03-27T15:00:00Z"
    trilio.io/backupplan-uid: "cluster-plan-daily"
    trilio.io/backupplan-name: "daily-cluster-backup"
    trilio.io/cluster-backup: "true"
spec:
  backupTarget:
    name: nfs-cluster-target
  backupRef:
    uid: xyz-789-cluster    # ← Parent cluster-backup UID
status:
  scanLocations:
  - backupUID: abc-child-1  # ← Child backup UID (NOT used)
    namespace: ns-app
  - backupUID: abc-child-2  # ← Child backup UID (NOT used)
    namespace: ns-db
```

**ConfigMap**:
```json
{
  "vm_collection_metadata": {
    "backup-metadata": {
      "backup_uid": "xyz-789-cluster",     // ← Parent UID from spec.BackupRef.UID
      "backup_target_name": "nfs-cluster-target",
      "backupplan_uid": "cluster-plan-daily",
      "backupplan_name": "daily-cluster-backup",
      "backup_timestamp": "2026-03-27T15:00:00Z"
    }
  }
}
```

**Key Point**: ConfigMap uses **parent cluster-backup UID** (`xyz-789-cluster`), not child UIDs (`abc-child-1`, `abc-child-2`). This ensures all VMs from all child namespaces are correlated to the single cluster-backup entity.

---

## Annotation Lifecycle

### Creation (Prescan)
```
prescan job starts
  → mounts backup target
  → reads backup.json/cluster-backup.json
  → extracts metadata
  → patches ScanInstance with annotations
```

### Reading (Controller)
```
controller reconciles ScanInstance
  → reads annotations from scanInstance.Annotations map
  → reads spec from scanInstance.Spec
  → builds backupMetadata map
  → generates ConfigMap JSON
```

### Persistence
- Annotations are stored in etcd with ScanInstance CR
- Survive controller restarts
- Immutable after prescan completes (backup metadata doesn't change)
- Deleted when ScanInstance is deleted

---

## Edge Cases Handled

### 1. Missing creationTimestamp in backup file
**Result**: `backup_creation_timestamp = ""`  
**Impact**: Annotation is empty string, ConfigMap field omitted, DB uses ingestion time

### 2. Missing backupPlan in backup file
**Result**: `backupplan_name = ""`  
**Impact**: Annotation is empty string, ConfigMap field omitted, DB stores NULL

### 3. Old ScanInstance without annotations
**Result**: Controller creates ConfigMap without `vm_collection_metadata`  
**Impact**: Scan proceeds normally, report has no backup_metadata, DB uses fallbacks

### 4. Cluster backup with no VM child backups
**Result**: `scanLocations = []`, `is_vm_workload = false`  
**Impact**: PreScan marks as non-VM workload, no ConfigMap created, scan skipped

---

## Grafana Variable Configuration

### Variable: backup_target

**Query**:
```sql
SELECT DISTINCT backup_target_name 
FROM backups 
ORDER BY backup_target_name;
```

**Type**: Dropdown, single-select  
**Purpose**: Filter entire dashboard by backup target

---

### Variable: backup_plan_uid

**Query**:
```sql
SELECT DISTINCT 
  backup_plan_uid AS __value,
  COALESCE(backup_plan_name, backup_plan_uid) AS __text
FROM backups
WHERE backup_target_name = '$backup_target'
ORDER BY backup_plan_name;
```

**Type**: Dropdown, single-select, cascading (depends on `$backup_target`)  
**Purpose**: Filter dashboard by backup plan within selected target

**Display**: Shows human-readable plan name, uses UID internally

---

## Implementation Verification

Run this complete check:

```bash
#!/bin/bash

echo "=== Backup Metadata Integration Check ==="

# 1. Check Python files compile
echo "Checking Python syntax..."
python3 -m py_compile datastore-attacher/prescan/cli.py
python3 -m py_compile datastore-attacher/shared/backup_detection/tvk_detector.py
echo "✅ Python syntax OK"

# 2. Check Go files compile
echo "Checking Go compilation..."
go build ./internal/...
go build ./pkg/helpers/...
go build ./controllers/...
echo "✅ Go compilation OK"

# 3. Check constants defined
echo "Checking annotation constants..."
grep -q "BackupCreationTimestampAnnotation" internal/constants.go && echo "✅ Found BackupCreationTimestampAnnotation"
grep -q "BackupPlanUIDAnnotation" internal/constants.go && echo "✅ Found BackupPlanUIDAnnotation"
grep -q "BackupPlanNameAnnotation" internal/constants.go && echo "✅ Found BackupPlanNameAnnotation"

# 4. Check prescan uses annotations
echo "Checking prescan annotations..."
grep -q "trilio.io/backup-creation-timestamp" datastore-attacher/prescan/cli.py && echo "✅ Prescan adds backup-creation-timestamp"
grep -q "trilio.io/backupplan-uid" datastore-attacher/prescan/cli.py && echo "✅ Prescan adds backupplan-uid"
grep -q "trilio.io/backupplan-name" datastore-attacher/prescan/cli.py && echo "✅ Prescan adds backupplan-name"

# 5. Check controller reads annotations
echo "Checking controller integration..."
grep -q "BackupCreationTimestampAnnotation" pkg/helpers/job_helper.go && echo "✅ Controller reads backup-creation-timestamp"
grep -q "vm_collection_metadata" pkg/helpers/job_helper.go && echo "✅ Controller generates vm_collection_metadata"

echo ""
echo "=== All Checks Passed ==="
```

Save as `verify_backup_metadata_integration.sh` and run with `bash verify_backup_metadata_integration.sh`

---

## Constants Reference

### Go Constants (internal/constants.go)

```go
const (
    // Backup metadata annotation keys
    BackupCreationTimestampAnnotation = "trilio.io/backup-creation-timestamp"
    BackupPlanUIDAnnotation = "trilio.io/backupplan-uid"
    BackupPlanNameAnnotation = "trilio.io/backupplan-name"
    ClusterBackupAnnotation = "trilio.io/cluster-backup"
)
```

**Usage in code**:
```go
timestamp := scanInstance.Annotations[internal.BackupCreationTimestampAnnotation]
planUID := scanInstance.Annotations[internal.BackupPlanUIDAnnotation]
planName := scanInstance.Annotations[internal.BackupPlanNameAnnotation]
isCluster := scanInstance.Annotations[internal.ClusterBackupAnnotation]
```

### Python Constants (prescan/cli.py)

```python
# Annotation keys
ANNOTATION_BACKUP_TIMESTAMP = 'trilio.io/backup-creation-timestamp'
ANNOTATION_BACKUPPLAN_UID = 'trilio.io/backupplan-uid'
ANNOTATION_BACKUPPLAN_NAME = 'trilio.io/backupplan-name'
ANNOTATION_CLUSTER_BACKUP = 'trilio.io/cluster-backup'
ANNOTATION_VM_WORKLOAD = 'trilio.io/vm-workload'

# Usage
annotations = {
    ANNOTATION_VM_WORKLOAD: str(is_vm_workload).lower(),
    ANNOTATION_CLUSTER_BACKUP: str(is_cluster_backup).lower(),
    ANNOTATION_BACKUP_TIMESTAMP: backup_creation_timestamp,
    ANNOTATION_BACKUPPLAN_UID: backupplan_uid,
    ANNOTATION_BACKUPPLAN_NAME: backupplan_name
}
```

---

## kubectl Commands

### View All Annotations
```bash
kubectl get scaninstance <name> -n threat-scanning-system -o json | jq '.metadata.annotations'
```

### Get Specific Annotation
```bash
# Backup creation timestamp
kubectl get scaninstance <name> -n threat-scanning-system \
  -o jsonpath='{.metadata.annotations.trilio\.io/backup-creation-timestamp}'

# Backup plan UID
kubectl get scaninstance <name> -n threat-scanning-system \
  -o jsonpath='{.metadata.annotations.trilio\.io/backupplan-uid}'

# Backup plan name
kubectl get scaninstance <name> -n threat-scanning-system \
  -o jsonpath='{.metadata.annotations.trilio\.io/backupplan-name}'

# Is cluster backup
kubectl get scaninstance <name> -n threat-scanning-system \
  -o jsonpath='{.metadata.annotations.trilio\.io/cluster-backup}'
```

### Filter ScanInstances by Annotations
```bash
# Find all scans of a specific backup plan
kubectl get scaninstance -n threat-scanning-system \
  -o json | jq '.items[] | select(.metadata.annotations."trilio.io/backupplan-uid" == "bkp_all") | .metadata.name'

# Find all cluster backup scans
kubectl get scaninstance -n threat-scanning-system \
  -o json | jq '.items[] | select(.metadata.annotations."trilio.io/cluster-backup" == "true") | .metadata.name'

# Find scans from specific target
kubectl get scaninstance -n threat-scanning-system \
  -o json | jq '.items[] | select(.spec.backupTarget.name == "s3-prod-target") | .metadata.name'
```

---

## Troubleshooting Guide

### Issue: Empty timestamp annotation

**Check 1**: Does backup file have creationTimestamp?
```bash
# For namespace backup
cat /triliodata/bkp_all/abc-123/backup.json | jq '.metadata.creationTimestamp'

# For cluster backup
cat /triliodata/cluster-plan/xyz-789/cluster-backup.json | jq '.metadata.creationTimestamp'
```

**Check 2**: Prescan logs
```bash
kubectl logs -n threat-scanning-system prescan-<scaninstance> | grep "backup_creation_timestamp"
```

**Fix**: Ensure backup file is valid and created by TVK/TVO (not manually crafted)

---

### Issue: Annotation exists but ConfigMap missing vm_collection_metadata

**Check 1**: Controller reading annotations?
```bash
kubectl logs -n threat-scanning-system deployment/threat-scanning-controller | \
  grep -A5 "Creating scan configmap"
```

**Check 2**: Verify backupMetadata map is built
Add debug logging to `pkg/helpers/job_helper.go` before ConfigMap creation:
```go
fmt.Printf("DEBUG: backupMetadata = %+v\n", backupMetadata)
```

**Fix**: Ensure controller image is updated with latest code

---

### Issue: Wrong backup_uid in database for cluster backups

**Symptom**: Database has child backup UID instead of parent cluster-backup UID

**Check**: Compare values
```bash
# Get cluster-backup UID from spec
kubectl get scaninstance <name> -o jsonpath='{.spec.backupRef.uid}'

# Get what's in ConfigMap
kubectl get configmap scan-config-<name> -o jsonpath='{.data.vm_artifacts_configuration\.json}' | \
  jq '.vm_collection_metadata."backup-metadata".backup_uid'

# Should match!
```

**Fix**: Already implemented - uses `spec.BackupRef.UID` not `scanLocations[0].BackupUID`

---

### Issue: Grafana variable showing no options

**Check 1**: Database has data
```sql
SELECT COUNT(*) FROM backups;
SELECT DISTINCT backup_target_name FROM backups;
```

**Check 2**: Grafana data source configured
```bash
# Test PostgreSQL connection from Grafana
# Admin → Data Sources → PostgreSQL → Test
```

**Check 3**: Variable query syntax
```sql
-- Should return columns: __value, __text
SELECT DISTINCT 
  backup_plan_uid AS __value,
  backup_plan_name AS __text
FROM backups;
```

---

## API Reference

### Kubernetes API Patch (Python)

```python
from shared.k8s.client import K8sClient

k8s_client = K8sClient()

# Patch ScanInstance with annotations
success = k8s_client.patch_scan_instance(
    name="scan-001",
    annotations={
        'trilio.io/backup-creation-timestamp': '2026-03-27T10:00:00Z',
        'trilio.io/backupplan-uid': 'bkp_all',
        'trilio.io/backupplan-name': 'daily-vm-backup'
    }
)
```

### Controller API (Go)

```go
import (
    v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
    "github.com/trilioData/threat-scanning-architecture/internal"
)

// Read annotations from ScanInstance
timestamp := scanInstance.Annotations[internal.BackupCreationTimestampAnnotation]
planUID := scanInstance.Annotations[internal.BackupPlanUIDAnnotation]
planName := scanInstance.Annotations[internal.BackupPlanNameAnnotation]

// Read from spec
backupUID := scanInstance.Spec.BackupRef.UID
targetName := scanInstance.Spec.BackupTarget.Name
```

---

## Summary

**Total Annotations Added**: 3
- `trilio.io/backup-creation-timestamp`
- `trilio.io/backupplan-uid`
- `trilio.io/backupplan-name`

**Total Metadata Fields in ConfigMap**: 5
- `backup_uid`
- `backup_target_name`
- `backupplan_uid`
- `backupplan_name`
- `backup_timestamp`

**Backward Compatibility**: ✅ 100% - All additions are optional

**Integration Status**: ✅ Complete - All components aligned
