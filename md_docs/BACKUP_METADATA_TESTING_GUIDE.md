# Backup Metadata Integration - Testing Guide

## Test Scenarios

### Scenario 1: Single Namespace Backup

#### Setup
```yaml
apiVersion: triliovault.trilio.io/v1
kind: Backup
metadata:
  name: daily-backup-001
  uid: abc-123-456
  creationTimestamp: "2026-03-27T10:00:00Z"
spec:
  backupPlan: daily-vm-backup
  target:
    name: s3-prod-target
```

Backup path structure:
```
/triliodata/
└── bkp_all/
    └── abc-123-456/
        ├── backup.json
        ├── tvk-meta.json
        └── custom/
            └── data-snapshot/
                ├── vol-boot/
                │   ├── pv.qcow2
                │   └── memory.dmp
                └── vol-data/
                    └── pv.qcow2
```

#### Expected Results

**1. Prescan Log Output:**
```
✓ Extracted metadata: instance_id=..., backupplan_uid=bkp_all, backup_uid=abc-123-456, 
  is_vm_workload=true, is_cluster_backup=false, scan_locations_count=1
✓ Successfully updated ScanInstance scan-daily-001
```

**2. ScanInstance Annotations:**
```yaml
metadata:
  annotations:
    trilio.io/backup-creation-timestamp: "2026-03-27T10:00:00Z"
    trilio.io/backupplan-uid: "bkp_all"
    trilio.io/backupplan-name: "daily-vm-backup"
    trilio.io/cluster-backup: "false"
    trilio.io/vm-workload: "true"
```

**3. ConfigMap Content:**
```json
{
  "vm_artifacts": {
    "vm-ubuntu-22_default": {...}
  },
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

**4. Scan Report:**
```json
{
  "scan_id": "SCAN-20260330-120000-vm-scan",
  "backup_metadata": {
    "backup_uid": "abc-123-456",
    "backup_target_name": "s3-prod-target",
    "backup_plan_uid": "bkp_all",
    "backup_created_at": "2026-03-27 10:00:00"
  },
  "summary": {...}
}
```

**5. PostgreSQL Verification:**
```sql
-- Verify backups table
SELECT * FROM backups WHERE backup_uid = 'abc-123-456';

-- Expected result:
-- backup_uid     | backup_target_name | backup_plan_uid | backup_plan_name   | created_at
-- abc-123-456    | s3-prod-target     | bkp_all         | daily-vm-backup    | 2026-03-27 10:00:00
```

---

### Scenario 2: Cluster Backup with Multiple Children

#### Setup
```yaml
apiVersion: triliovault.trilio.io/v1
kind: ClusterBackup
metadata:
  name: cluster-backup-001
  uid: xyz-789-cluster
  creationTimestamp: "2026-03-27T15:00:00Z"
spec:
  clusterBackupPlan: cluster-daily-plan
  target:
    name: nfs-cluster-target
```

Backup path structure:
```
/triliodata/
└── cluster-plan-uid/
    └── xyz-789-cluster/
        ├── cluster-backup.json
        ├── tvk-meta.json
        └── backups/
            ├── ns-app/
            │   └── abc-child-1/
            │       ├── backup.json (hasKubevirtResources: true)
            │       └── custom/data-snapshot/...
            ├── ns-db/
            │   └── abc-child-2/
            │       ├── backup.json (hasKubevirtResources: true)
            │       └── custom/data-snapshot/...
            └── ns-web/
                └── abc-child-3/
                    └── backup.json (hasKubevirtResources: false)
```

#### Expected Results

**1. Prescan Log Output:**
```
Detected cluster-backup, processing child backups
Cluster-backup has 3 child backups
Processing child backup in namespace 'ns-app'
  Child backup 'ns-app' has kubevirt resources, parsing dataSnapshots
  Added scan location for namespace 'ns-app' with 2 VM(s) and 3 PVC(s)
Processing child backup in namespace 'ns-db'
  Child backup 'ns-db' has kubevirt resources, parsing dataSnapshots
  Added scan location for namespace 'ns-db' with 1 VM(s) and 2 PVC(s)
Processing child backup in namespace 'ns-web'
  Child backup 'ns-web' has no kubevirt resources (hasKubevirtResources=false), skipping
✓ Cluster-backup has VM workloads: 2 child backup(s) with VMs
✓ Successfully updated ScanInstance scan-cluster-001
```

**2. ScanInstance Annotations:**
```yaml
metadata:
  annotations:
    trilio.io/backup-creation-timestamp: "2026-03-27T15:00:00Z"
    trilio.io/backupplan-uid: "cluster-plan-uid"
    trilio.io/backupplan-name: "cluster-daily-plan"
    trilio.io/cluster-backup: "true"
    trilio.io/vm-workload: "true"

spec:
  backupRef:
    uid: xyz-789-cluster  # Parent cluster-backup UID
    path: /cluster-plan-uid/xyz-789-cluster

status:
  scanLocations:
  - namespace: ns-app
    backupUID: abc-child-1  # Child backup UID
    backupPath: backups/ns-app/abc-child-1
    vms: [...]
  - namespace: ns-db
    backupUID: abc-child-2  # Child backup UID
    backupPath: backups/ns-db/abc-child-2
    vms: [...]
```

**3. ConfigMap Content:**
```json
{
  "vm_artifacts": {
    "vm-app-1_ns-app": {...},
    "vm-app-2_ns-app": {...},
    "vm-db-1_ns-db": {...}
  },
  "vm_collection_metadata": {
    "backup-metadata": {
      "backup_uid": "xyz-789-cluster",
      "backup_target_name": "nfs-cluster-target",
      "backupplan_uid": "cluster-plan-uid",
      "backupplan_name": "cluster-daily-plan",
      "backup_timestamp": "2026-03-27T15:00:00Z"
    }
  }
}
```

**Key Point**: `backup_uid` is the **parent cluster-backup UID** (`xyz-789-cluster`), NOT the child UIDs (`abc-child-1`, `abc-child-2`).

**4. Scan Report:**
```json
{
  "scan_id": "SCAN-20260330-150000-cluster-scan",
  "backup_metadata": {
    "backup_uid": "xyz-789-cluster",
    "backup_target_name": "nfs-cluster-target",
    "backup_plan_uid": "cluster-plan-uid",
    "backup_created_at": "2026-03-27 15:00:00"
  },
  "summary": {
    "total_vms_scanned": 3,
    ...
  },
  "threats": {...}
}
```

**5. PostgreSQL Verification:**
```sql
-- Verify backups table (should have cluster-backup UID)
SELECT * FROM backups WHERE backup_uid = 'xyz-789-cluster';

-- Expected result:
-- backup_uid       | backup_target_name  | backup_plan_name      | created_at
-- xyz-789-cluster  | nfs-cluster-target  | cluster-daily-plan    | 2026-03-27 15:00:00

-- Verify scan association
SELECT s.scan_id, bs.backup_uid, bs.scan_number 
FROM scans s 
JOIN backup_scans bs ON s.scan_id = bs.scan_id
WHERE bs.backup_uid = 'xyz-789-cluster';

-- Expected result:
-- scan_id                              | backup_uid       | scan_number
-- SCAN-20260330-150000-cluster-scan    | xyz-789-cluster  | 1
```

---

### Scenario 3: Rescan of Same Backup

#### Setup
Same backup scanned twice at different times.

#### Expected Results

**First Scan:**
```sql
-- backup_scans table after first scan
SELECT * FROM backup_scans WHERE backup_uid = 'abc-123-456';

-- Result:
-- id | backup_uid  | scan_id  | scan_number | is_latest | created_at
-- 1  | abc-123-456 | SCAN-001 | 1           | TRUE      | 2026-03-27 11:00:00
```

**Second Scan (Rescan):**
```sql
-- backup_scans table after second scan
SELECT * FROM backup_scans WHERE backup_uid = 'abc-123-456' ORDER BY scan_number;

-- Result:
-- id | backup_uid  | scan_id  | scan_number | is_latest | created_at
-- 1  | abc-123-456 | SCAN-001 | 1           | FALSE     | 2026-03-27 11:00:00
-- 2  | abc-123-456 | SCAN-002 | 2           | TRUE      | 2026-03-30 14:00:00
```

**Grafana Heatmap Query:**
Uses `WHERE bs.is_latest = TRUE` to show only the latest scan results.

---

### Scenario 4: Missing Metadata (Backward Compatibility)

#### Setup
Old backup files without complete metadata or prescan without annotations.

#### Expected Behavior

**Missing creationTimestamp in backup.json:**
```python
# Detector returns empty string
backup_creation_timestamp = backup_json.get('metadata', {}).get('creationTimestamp', '')
# Result: backup_creation_timestamp = ''
```

**Missing annotations in ScanInstance:**
```go
// Controller checks if annotation exists
if backupUID := scanInstance.Annotations[internal.BackupCreationTimestampAnnotation]; backupUID != "" {
    backupMetadata["backup_timestamp"] = backupUID
}
// Result: backup_timestamp field not added to backupMetadata map
```

**ConfigMap Generation:**
```go
// Only adds non-empty fields
if timestamp, ok := backupMetadata["backup_timestamp"]; ok && timestamp != "" {
    vmCollectionMetadata["backup_timestamp"] = timestamp
}
// Result: backup_timestamp field not added to ConfigMap
```

**Database Ingestion:**
```python
# Provides fallback values
backup_meta = {
    'backup_uid': report.get('scan_id', 'UNKNOWN'),  # Fallback
    'backup_target_name': 'unknown',
    'backup_plan_uid': None,
    'backup_plan_name': None,
    'created_at': datetime.utcnow()  # Fallback to ingestion time
}
```

**Result**: System continues to work with fallback values, no failures.

---

## Manual Testing Steps

### Step 1: Deploy Updated Components

```bash
# Build and push datastore-attacher image with updated prescan
cd threat-scanning-architecture/datastore-attacher
docker build -t <registry>/datastore-attacher:backup-metadata .
docker push <registry>/datastore-attacher:backup-metadata

# Build and deploy controller
cd ../
make docker-build IMG=<registry>/threat-scanning-controller:backup-metadata
make docker-push IMG=<registry>/threat-scanning-controller:backup-metadata
make deploy IMG=<registry>/threat-scanning-controller:backup-metadata
```

### Step 2: Create Test ScanInstance

```bash
# Create sample ScanInstance
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-backup-metadata
  namespace: threat-scanning-system
spec:
  backupTarget:
    name: s3-test-target
    credentialSecret: s3-creds
  backupRef:
    uid: test-backup-123
    path: /test-plan/test-backup-123
EOF
```

### Step 3: Monitor Prescan

```bash
# Watch prescan job
kubectl logs -n threat-scanning-system -f prescan-test-backup-metadata

# Expected in logs:
# ✓ Extracted metadata: instance_id=..., backupplan_uid=test-plan, backup_uid=test-backup-123, 
#   backup_creation_timestamp=2026-03-27T10:00:00Z, backupplan_name=...
```

### Step 4: Verify ScanInstance

```bash
# Check annotations
kubectl get scaninstance test-backup-metadata -n threat-scanning-system -o yaml

# Verify these annotations exist:
# trilio.io/backup-creation-timestamp
# trilio.io/backupplan-uid
# trilio.io/backupplan-name
```

### Step 5: Verify ConfigMap

```bash
# Wait for ConfigMap creation
kubectl wait --for=condition=Available scaninstance/test-backup-metadata -n threat-scanning-system --timeout=5m

# Check ConfigMap
kubectl get configmap scan-config-test-backup-metadata -n threat-scanning-system -o json | \
  jq '.data["vm_artifacts_configuration.json"] | fromjson | .vm_collection_metadata'

# Expected output:
# {
#   "backup-metadata": {
#     "backup_uid": "test-backup-123",
#     "backup_target_name": "s3-test-target",
#     "backupplan_uid": "test-plan",
#     "backupplan_name": "...",
#     "backup_timestamp": "2026-03-27T10:00:00Z"
#   }
# }
```

### Step 6: Monitor Scan Job

```bash
# Check scan job logs
kubectl logs -n threat-scanning-system -f scan-job-test-backup-metadata

# Expected in logs:
# Loading configuration from /config/vm_artifacts_configuration.json
# Backup metadata: backup_uid=test-backup-123, target=s3-test-target, ...
```

### Step 7: Verify Report

```bash
# After scan completes, check report on scan job container
kubectl exec -n threat-scanning-system scan-job-test-backup-metadata -- \
  cat /reports/scan_report_*.json | jq '.backup_metadata'

# Expected output:
# {
#   "backup_uid": "test-backup-123",
#   "backup_target_name": "s3-test-target",
#   "backup_plan_uid": "test-plan",
#   "backup_created_at": "2026-03-27 10:00:00"
# }
```

### Step 8: Verify Database

```bash
# Copy report to local machine and ingest
kubectl cp threat-scanning-system/scan-job-test-backup-metadata:/reports/scan_report_*.json ./test_report.json

# Run database setup
cd enhanced-soc-analysis
python3 soc_database_setup.py --report test_report.json

# Query PostgreSQL
psql -h localhost -U postgres -d soc_dashboard -c "
  SELECT 
    backup_uid, 
    backup_target_name, 
    backup_plan_name, 
    created_at 
  FROM backups 
  WHERE backup_uid = 'test-backup-123';
"

# Expected result:
# backup_uid      | backup_target_name | backup_plan_name   | created_at
# test-backup-123 | s3-test-target     | daily-vm-backup    | 2026-03-27 10:00:00
```

---

## Automated Test Script

```bash
#!/bin/bash
set -e

SCANINSTANCE_NAME="test-backup-metadata-$(date +%s)"
BACKUP_UID="test-backup-$(uuidgen | cut -d- -f1)"
TARGET_NAME="s3-test-target"

echo "=== Testing Backup Metadata Integration ==="
echo "ScanInstance: $SCANINSTANCE_NAME"
echo "Backup UID: $BACKUP_UID"

# Step 1: Create ScanInstance
echo "Creating ScanInstance..."
kubectl apply -f - <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: $SCANINSTANCE_NAME
  namespace: threat-scanning-system
spec:
  backupTarget:
    name: $TARGET_NAME
    credentialSecret: s3-creds
  backupRef:
    uid: $BACKUP_UID
    path: /test-plan/$BACKUP_UID
EOF

# Step 2: Wait for prescan to complete
echo "Waiting for prescan..."
kubectl wait --for=jsonpath='{.status.condition[?(@.phase=="PreScan")].status}'=Completed \
  scaninstance/$SCANINSTANCE_NAME -n threat-scanning-system --timeout=5m

# Step 3: Check annotations
echo "Verifying annotations..."
TIMESTAMP=$(kubectl get scaninstance $SCANINSTANCE_NAME -n threat-scanning-system \
  -o jsonpath='{.metadata.annotations.trilio\.io/backup-creation-timestamp}')
PLAN_UID=$(kubectl get scaninstance $SCANINSTANCE_NAME -n threat-scanning-system \
  -o jsonpath='{.metadata.annotations.trilio\.io/backupplan-uid}')
PLAN_NAME=$(kubectl get scaninstance $SCANINSTANCE_NAME -n threat-scanning-system \
  -o jsonpath='{.metadata.annotations.trilio\.io/backupplan-name}')

echo "  Timestamp: $TIMESTAMP"
echo "  Plan UID: $PLAN_UID"
echo "  Plan Name: $PLAN_NAME"

if [ -z "$TIMESTAMP" ]; then
  echo "❌ FAILED: backup-creation-timestamp annotation not found"
  exit 1
fi

# Step 4: Wait for ConfigMap
echo "Waiting for ConfigMap creation..."
kubectl wait --for=jsonpath='{.status.condition[?(@.phase=="Scanning")].status}'=InProgress \
  scaninstance/$SCANINSTANCE_NAME -n threat-scanning-system --timeout=5m

# Step 5: Verify ConfigMap
echo "Verifying ConfigMap..."
CONFIG_METADATA=$(kubectl get configmap scan-config-$SCANINSTANCE_NAME -n threat-scanning-system \
  -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq '.vm_collection_metadata')

echo "ConfigMap metadata:"
echo "$CONFIG_METADATA" | jq

if [ "$CONFIG_METADATA" == "null" ]; then
  echo "❌ FAILED: vm_collection_metadata not found in ConfigMap"
  exit 1
fi

# Step 6: Wait for scan completion
echo "Waiting for scan to complete..."
kubectl wait --for=jsonpath='{.status.condition[?(@.phase=="Scanning")].status}'=Completed \
  scaninstance/$SCANINSTANCE_NAME -n threat-scanning-system --timeout=10m

# Step 7: Extract and verify report
echo "Extracting scan report..."
SCAN_JOB=$(kubectl get jobs -n threat-scanning-system -l trilio.io/scaninstance-name=$SCANINSTANCE_NAME \
  -o jsonpath='{.items[?(@.metadata.labels.trilio\.io/operation=="scan")].metadata.name}')

kubectl cp threat-scanning-system/$SCAN_JOB:/reports/scan_report_*.json ./test_report_$SCANINSTANCE_NAME.json

REPORT_METADATA=$(cat test_report_$SCANINSTANCE_NAME.json | jq '.backup_metadata')
echo "Report metadata:"
echo "$REPORT_METADATA" | jq

if [ "$REPORT_METADATA" == "null" ]; then
  echo "❌ FAILED: backup_metadata not found in scan report"
  exit 1
fi

echo "✅ ALL TESTS PASSED"
```

---

## Regression Testing

### Test 1: Backward Compatibility

**Old ScanInstance (no annotations):**
- Should still create ConfigMap successfully
- ConfigMap may lack `vm_collection_metadata` section
- Scan proceeds normally with fallback values

**Validation:**
```bash
# Remove annotations
kubectl annotate scaninstance test-backup-metadata \
  trilio.io/backup-creation-timestamp- \
  trilio.io/backupplan-uid- \
  trilio.io/backupplan-name- \
  -n threat-scanning-system

# Trigger ConfigMap recreation (delete existing)
kubectl delete configmap scan-config-test-backup-metadata -n threat-scanning-system

# Wait for controller to recreate
# Verify ConfigMap still created (may lack metadata section)
```

### Test 2: Empty Timestamp

**backup.json without creationTimestamp:**
```json
{
  "metadata": {
    "uid": "abc-123"
    // No creationTimestamp field
  }
}
```

**Expected**: 
- Annotation `trilio.io/backup-creation-timestamp` is empty string
- ConfigMap `backup_timestamp` field is omitted
- Database uses ingestion time as fallback

### Test 3: Multiple Rescans

**Steps:**
1. Scan backup `abc-123` → Report with `backup_uid=abc-123`
2. Load report → Database has `scan_number=1, is_latest=TRUE`
3. Scan same backup again → New report with same `backup_uid`
4. Load report → Database updates:
   - Previous scan: `is_latest=FALSE`
   - New scan: `scan_number=2, is_latest=TRUE`

**Validation:**
```sql
SELECT 
  backup_uid,
  scan_id,
  scan_number,
  is_latest,
  created_at
FROM backup_scans
WHERE backup_uid = 'abc-123'
ORDER BY scan_number;
```

---

## Common Issues & Solutions

### Issue 1: Annotations not appearing

**Symptom**: ScanInstance has no `trilio.io/backup-creation-timestamp` annotation

**Possible Causes**:
1. Prescan failed before annotation update
2. backup.json missing or malformed
3. Prescan image not updated

**Debug**:
```bash
# Check prescan job logs
kubectl logs -n threat-scanning-system prescan-<name>

# Check if prescan job completed successfully
kubectl get job -n threat-scanning-system prescan-<name> -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}'
```

### Issue 2: ConfigMap has vm_artifacts but no vm_collection_metadata

**Symptom**: ConfigMap created but missing metadata section

**Possible Causes**:
1. Annotations exist but controller image not updated
2. Annotations are empty strings

**Debug**:
```bash
# Check controller logs
kubectl logs -n threat-scanning-system deployment/threat-scanning-controller | grep -A10 "Creating scan configmap"

# Verify annotations are non-empty
kubectl get scaninstance <name> -n threat-scanning-system -o jsonpath='{.metadata.annotations}' | jq
```

### Issue 3: Wrong backup_uid in database (child instead of parent for cluster backups)

**Symptom**: PostgreSQL has child backup UIDs instead of cluster-backup UID

**Cause**: Using `scanLocations[0].BackupUID` instead of `spec.BackupRef.UID`

**Solution**: Already fixed in implementation - uses `spec.BackupRef.UID`

**Validation**:
```bash
# For cluster backup, verify ConfigMap has parent UID
kubectl get scaninstance <name> -o jsonpath='{.spec.backupRef.uid}'  # Should match
kubectl get cm scan-config-<name> -o jsonpath='{.data.vm_artifacts_configuration\.json}' | \
  jq '.vm_collection_metadata."backup-metadata".backup_uid'  # Should match above
```

---

## Performance Considerations

### Impact Analysis

**Prescan Phase:**
- Additional file reads: +1 (backup.json/cluster-backup.json already read)
- JSON parsing: +3 fields (creationTimestamp, backupPlan/clusterBackupPlan, spec.backupPlan)
- **Impact**: Negligible (<10ms per backup)

**Controller:**
- Annotation reads: +3 (from in-memory ScanInstance object)
- Map operations: +5 string assignments
- JSON marshaling: +1 nested object in ConfigMap
- **Impact**: Negligible (<5ms)

**Scan Job:**
- Config loading: No change (already reads full JSON)
- **Impact**: None

**Database:**
- Tables already exist (backups, backup_scans)
- Indexes already optimized
- **Impact**: None

### Scalability

**Many ScanInstances**: Annotations are lightweight, no scalability concerns
**Large Cluster Backups**: Only parent UID stored, not all child UIDs
**Frequent Rescans**: `backup_scans` table handles with `is_latest` flag efficiently

---

## Rollback Plan

If issues arise, rollback is straightforward:

1. **Revert Controller:**
```bash
kubectl rollout undo deployment/threat-scanning-controller -n threat-scanning-system
```

2. **Revert Prescan:**
```bash
# Update deployment to use previous image
kubectl set image deployment/datastore-attacher datastore-attacher=<previous-image>
```

3. **Database**: No schema changes needed - new annotations are optional

4. **Existing Scans**: Continue to work with fallback values
