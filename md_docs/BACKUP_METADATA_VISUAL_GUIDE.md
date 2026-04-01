# Backup Metadata Flow - Visual Guide

## Complete Data Flow Diagram

```
╔════════════════════════════════════════════════════════════════════════════╗
║                         BACKUP FILE STRUCTURE                              ║
╚════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────┐    ┌──────────────────────────────────┐
│ backup.json                     │    │ cluster-backup.json              │
│ (Namespace Backup)              │    │ (Cluster Backup)                 │
├─────────────────────────────────┤    ├──────────────────────────────────┤
│ metadata:                       │    │ metadata:                        │
│   uid: "abc-123"                │    │   uid: "xyz-789"                 │
│   creationTimestamp: "2026..."  │    │   creationTimestamp: "2026..."   │
│                                 │    │                                  │
│ spec:                           │    │ spec:                            │
│   backupPlan: "daily-backup"    │    │   clusterBackupPlan: "cluster-1" │
└─────────────────────────────────┘    └──────────────────────────────────┘
           │                                        │
           └────────────────┬───────────────────────┘
                            │
                            ▼
╔════════════════════════════════════════════════════════════════════════════╗
║                    STEP 1: PRESCAN PHASE (Python)                          ║
╚════════════════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────────────────┐
│ TVKBackupDetector.extract_metadata()                                       │
│                                                                             │
│ Namespace Backup:                    Cluster Backup:                       │
│ ─────────────────                    ─────────────                         │
│ ├─ Read backup.json                  ├─ Read cluster-backup.json           │
│ ├─ Extract metadata.creationTimestamp├─ Extract metadata.creationTimestamp │
│ ├─ Extract spec.backupPlan           ├─ Extract spec.clusterBackupPlan     │
│ └─ Parse path for backupplan_uid     └─ Parse path for backupplan_uid      │
│                                                                             │
│ Returns:                                                                    │
│ {                                                                           │
│   "backup_creation_timestamp": "2026-02-27T10:00:00Z",                     │
│   "backupplan_uid": "bkp_all",                                             │
│   "backupplan_name": "daily-vm-backup",                                    │
│   "backup_uid": "216a37b9-...",                                            │
│   "instance_id": "...",                                                    │
│   "is_cluster_backup": true/false,                                         │
│   "scan_locations": [...]                                                  │
│ }                                                                           │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ prescan/cli.py - Patches ScanInstance                                      │
│                                                                             │
│ annotations:                                                                │
│   trilio.io/backup-creation-timestamp: "2026-02-27T10:00:00Z"              │
│   trilio.io/backupplan-uid: "bkp_all"                                      │
│   trilio.io/backupplan-name: "daily-vm-backup"                             │
│   trilio.io/cluster-backup: "false"                                        │
│   trilio.io/vm-workload: "true"                                            │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
╔════════════════════════════════════════════════════════════════════════════╗
║                    STEP 2: CONTROLLER PHASE (Go)                           ║
╚════════════════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────────────────┐
│ helpers.GetScanConfigMap(scanInstance)                                     │
│                                                                             │
│ Extract from ScanInstance:                                                 │
│ ┌───────────────────────────────┬─────────────────────────────────┐        │
│ │ Source                        │ Destination Field               │        │
│ ├───────────────────────────────┼─────────────────────────────────┤        │
│ │ annotations[...timestamp]     │ backup_timestamp                │        │
│ │ annotations[...plan-uid]      │ backupplan_uid                  │        │
│ │ annotations[...plan-name]     │ backupplan_name                 │        │
│ │ spec.BackupRef.UID            │ backup_uid                      │        │
│ │ spec.BackupTarget.Name        │ backup_target_name              │        │
│ └───────────────────────────────┴─────────────────────────────────┘        │
│                                                                             │
│ Result: backupMetadata map[string]string                                   │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ helpers.GetScanConfigMapData(scanLocations, backupMetadata)                │
│                                                                             │
│ Builds JSON:                                                                │
│ {                                                                           │
│   "vm_artifacts": {                                                         │
│     "vm-ubuntu-22_default": {                                               │
│       "disk_image": "/triliodata/.../pv.qcow2",                             │
│       "memory_dump": "/triliodata/.../memory.dmp",                          │
│       ...                                                                   │
│     }                                                                       │
│   },                                                                        │
│   "vm_collection_metadata": {                                               │
│     "backup-metadata": {                                                    │
│       "backup_uid": "216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",                 │
│       "backup_target_name": "s3-prod-target",                               │
│       "backupplan_uid": "bkp_all",                                          │
│       "backupplan_name": "daily-vm-backup",                                 │
│       "backup_timestamp": "2026-02-27T10:00:00Z"                            │
│     }                                                                       │
│   }                                                                         │
│ }                                                                           │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ ConfigMap Created: scan-config-{scaninstance-name}                         │
│                                                                             │
│ data:                                                                       │
│   vm_artifacts_configuration.json: |                                       │
│     <JSON structure from above>                                             │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
╔════════════════════════════════════════════════════════════════════════════╗
║                    STEP 3: SCAN JOB PHASE (Python)                         ║
╚════════════════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────────────────┐
│ Scan Job Container                                                          │
│                                                                             │
│ ConfigMap mounted at: /config/vm_artifacts_configuration.json              │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ enhanced-soc-analysis/main.py                                              │
│                                                                             │
│ 1. Loads: /config/vm_artifacts_configuration.json                          │
│ 2. Extracts: vm_collection_metadata.backup-metadata                        │
│ 3. Passes to: DashboardReportGenerator(backup_metadata=...)                │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ dashboard_report_generator.py                                              │
│                                                                             │
│ set_backup_metadata():                                                      │
│ ├─ Normalizes field names (backupplan_uid → backup_plan_uid)               │
│ ├─ Converts timestamp format (ISO8601 → YYYY-MM-DD HH:MM:SS)               │
│ └─ Stores in self.report['backup_metadata']                                │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Output: scan_report_<timestamp>_<scan_id>.json                             │
│                                                                             │
│ {                                                                           │
│   "scan_id": "SCAN-20260330-153151-multi-vm",                              │
│   "backup_metadata": {                                                      │
│     "backup_uid": "216a37b9-0cd0-4d2f-afd7-fa9c17c9ba0e",                  │
│     "backup_target_name": "s3-prod-target",                                │
│     "backup_plan_uid": "bkp_all",                                          │
│     "backup_created_at": "2026-02-27 10:00:00"                             │
│   },                                                                        │
│   "summary": {...},                                                         │
│   "threats": {...}                                                          │
│ }                                                                           │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
╔════════════════════════════════════════════════════════════════════════════╗
║                    STEP 4: DATABASE INGESTION                              ║
╚════════════════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────────────────┐
│ soc_database_setup.py                                                       │
│                                                                             │
│ 1. extract_backup_metadata(report)                                         │
│    └─ Extracts backup_metadata from report JSON                            │
│                                                                             │
│ 2. insert_backup(cur, backup_meta)                                         │
│    └─ INSERT INTO backups (...) ON CONFLICT DO UPDATE                      │
│                                                                             │
│ 3. insert_scan(cur, report, backup_uid)                                    │
│    └─ INSERT INTO scans (scan_id, backup_uid, ...)                         │
│                                                                             │
│ 4. insert_backup_scan_link(cur, backup_uid, scan_id)                       │
│    └─ INSERT INTO backup_scans (backup_uid, scan_id, scan_number, ...)     │
│       ├─ Set is_latest=FALSE for previous scans                            │
│       └─ Set is_latest=TRUE for new scan                                   │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ PostgreSQL Tables                                                           │
│                                                                             │
│ ┌──────────────────────────────────────────────────────────────┐           │
│ │ backups                                                       │           │
│ ├──────────────────────────────────────────────────────────────┤           │
│ │ backup_uid          | backup_target_name | backup_plan_name  │           │
│ │ 216a37b9-...        | s3-prod-target     | daily-vm-backup   │           │
│ │ created_at          | backup_plan_uid    | ingested_at       │           │
│ │ 2026-02-27 10:00:00 | bkp_all            | 2026-03-30...     │           │
│ └──────────────────────────────────────────────────────────────┘           │
│                                  │                                          │
│                                  ├──────────────┐                           │
│                                  │              │                           │
│ ┌────────────────────────────────▼───┐   ┌─────▼──────────────────────┐   │
│ │ scans                              │   │ backup_scans               │   │
│ ├────────────────────────────────────┤   ├────────────────────────────┤   │
│ │ scan_id | backup_uid | scan_time   │   │ backup_uid | scan_id       │   │
│ │ SCAN-1  | 216a37b9.. | 2026-03-01  │◄──┤ 216a37b9.. | SCAN-1        │   │
│ │ SCAN-2  | 216a37b9.. | 2026-03-15  │◄──┤ 216a37b9.. | SCAN-2        │   │
│ └────────────────────────────────────┘   │ scan_number | is_latest     │   │
│                                           │ 1           | FALSE         │   │
│                                           │ 2           | TRUE          │   │
│                                           └────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
╔════════════════════════════════════════════════════════════════════════════╗
║                       GRAFANA DASHBOARD QUERIES                            ║
╚════════════════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────────────────┐
│ Dashboard 1: Backup Plan Threat Evolution                                  │
│                                                                             │
│ Variables (Dropdowns):                                                      │
│ ├─ $backup_target: SELECT DISTINCT backup_target_name FROM backups         │
│ └─ $backup_plan_uid: SELECT backup_plan_uid FROM backups                   │
│                      WHERE backup_target_name = '$backup_target'            │
│                                                                             │
│ Heatmap Query (VM x Backup):                                               │
│ SELECT                                                                      │
│   tv.vm_id AS "VM",                                                         │
│   SUBSTRING(b.backup_uid, 1, 8) || ' (' || b.created_at || ')' AS "Backup",│
│   SUM(t.total_incidents) AS "IOCs"                                          │
│ FROM backups b                                                              │
│ JOIN backup_scans bs ON b.backup_uid = bs.backup_uid AND bs.is_latest=TRUE │
│ ...                                                                         │
│ WHERE b.backup_target_name = '$backup_target'                              │
│   AND b.backup_plan_uid = '$backup_plan_uid'                               │
│ GROUP BY tv.vm_id, b.backup_uid, b.created_at                              │
│ ORDER BY b.created_at ASC                                                  │
└────────────────────────────────────────────────────────────────────────────┘
```

## Field Mapping by Backup Type

### Namespace Backup

| backup.json Field | Prescan Metadata Key | Annotation Key | ConfigMap Field | Report Field | DB Column |
|-------------------|---------------------|----------------|-----------------|--------------|-----------|
| `metadata.uid` | `backup_uid` | - | `backup_uid` | `backup_uid` | `backups.backup_uid` |
| `metadata.creationTimestamp` | `backup_creation_timestamp` | `trilio.io/backup-creation-timestamp` | `backup_timestamp` | `backup_created_at` | `backups.created_at` |
| `spec.backupPlan` | `backupplan_name` | `trilio.io/backupplan-name` | `backupplan_name` | - | `backups.backup_plan_name` |
| (from path) | `backupplan_uid` | `trilio.io/backupplan-uid` | `backupplan_uid` | `backup_plan_uid` | `backups.backup_plan_uid` |

### Cluster Backup

| cluster-backup.json Field | Prescan Metadata Key | Annotation Key | ConfigMap Field | Report Field | DB Column |
|---------------------------|---------------------|----------------|-----------------|--------------|-----------|
| `metadata.uid` | `backup_uid` | - | `backup_uid` | `backup_uid` | `backups.backup_uid` |
| `metadata.creationTimestamp` | `backup_creation_timestamp` | `trilio.io/backup-creation-timestamp` | `backup_timestamp` | `backup_created_at` | `backups.created_at` |
| `spec.clusterBackupPlan` | `backupplan_name` | `trilio.io/backupplan-name` | `backupplan_name` | - | `backups.backup_plan_name` |
| (from path) | `backupplan_uid` | `trilio.io/backupplan-uid` | `backupplan_uid` | `backup_plan_uid` | `backups.backup_plan_uid` |

## Backup Type Differences

```
┌──────────────────────────┬─────────────────────────┬────────────────────────┐
│ Aspect                   │ Namespace Backup        │ Cluster Backup         │
├──────────────────────────┼─────────────────────────┼────────────────────────┤
│ File Read                │ backup.json             │ cluster-backup.json    │
│ Plan Field               │ spec.backupPlan         │ spec.clusterBackupPlan │
│ Backup UID in ConfigMap  │ Namespace backup UID    │ Cluster-backup UID     │
│ ScanLocations Count      │ 1                       │ Multiple (per child)   │
│ Annotation cluster-backup│ "false"                 │ "true"                 │
└──────────────────────────┴─────────────────────────┴────────────────────────┘
```

## Example: Cluster Backup Scenario

```
Cluster Backup: xyz-789 (has 3 child backups)
├─ Child backup ns-app: abc-111 (2 VMs)
├─ Child backup ns-db: abc-222 (1 VM)
└─ Child backup ns-cache: abc-333 (0 VMs - skipped)

Prescan Result:
├─ scan_locations[0]: {backup_uid: "abc-111", namespace: "ns-app", vms: [...]}
├─ scan_locations[1]: {backup_uid: "abc-222", namespace: "ns-db", vms: [...]}
└─ (ns-cache skipped - no VMs)

Annotations on ScanInstance:
├─ trilio.io/backup-creation-timestamp: "2026-02-27T10:00:00Z" (from cluster-backup.json)
├─ trilio.io/backupplan-uid: "cluster-plan-1"
├─ trilio.io/backupplan-name: "daily-cluster-backup"
└─ trilio.io/cluster-backup: "true"

ConfigMap backup_uid: "xyz-789" (from spec.BackupRef.UID - cluster-backup parent)

PostgreSQL:
├─ backups table: 1 row with backup_uid="xyz-789"
├─ scans table: 1 row with backup_uid="xyz-789"
└─ backup_scans table: 1 row linking backup_uid="xyz-789" to scan_id
```

**Why this matters**: All VMs from all child backups in a cluster-backup are scanned together in one scan job and associated with the parent cluster-backup UID for correlation.

## Quick Debugging

### Problem: Annotations not added to ScanInstance
**Check**: Prescan job logs
```bash
kubectl logs -n threat-scanning-system prescan-<scaninstance-name>
```
**Look for**: "✓ Extracted metadata: ... backup_creation_timestamp=..."

### Problem: ConfigMap missing vm_collection_metadata
**Check 1**: ScanInstance annotations exist
```bash
kubectl get scaninstance <name> -n threat-scanning-system -o jsonpath='{.metadata.annotations.trilio\.io/backup-creation-timestamp}'
```

**Check 2**: Controller logs during ConfigMap creation
```bash
kubectl logs -n threat-scanning-system deployment/threat-scanning-controller
```

### Problem: Report missing backup_metadata
**Check 1**: ConfigMap structure
```bash
kubectl get cm scan-config-<name> -n threat-scanning-system -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq '.vm_collection_metadata'
```

**Check 2**: Scan engine logs
```bash
kubectl logs -n threat-scanning-system scan-job-<name>
```

## Integration Points

1. **Backup Files** → Prescan detector reads metadata
2. **Prescan** → Adds annotations to ScanInstance CR
3. **Controller** → Reads annotations, creates ConfigMap
4. **Scan Job** → Mounts ConfigMap at /config/
5. **Scan Engine** → Reads config, generates report
6. **Report** → Contains backup_metadata section
7. **Database Setup** → Ingests into PostgreSQL
8. **Grafana** → Queries with backup filters
