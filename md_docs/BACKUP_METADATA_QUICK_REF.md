# Backup Metadata Integration - Quick Reference

## Overview
Backup metadata (UID, target, plan, timestamp) now flows automatically from backup files → prescan → controller → scan config → scan reports.

## New ScanInstance Annotations

After prescan completes, these annotations are added:

| Annotation | Source | Example Value |
|-----------|--------|---------------|
| `trilio.io/backup-creation-timestamp` | backup.json `metadata.creationTimestamp` | `2026-02-27T10:00:00Z` |
| `trilio.io/backupplan-uid` | Backup path structure | `bkp_all` |
| `trilio.io/backupplan-name` | backup.json `spec.backupPlan` | `daily-vm-backup` |
| `trilio.io/cluster-backup` | Backup structure detection | `true` or `false` |

For **cluster backups**, values come from `cluster-backup.json` instead.

## ConfigMap Structure

The scan ConfigMap now includes `vm_collection_metadata`:

```json
{
  "vm_artifacts": {
    "vm-name_namespace": {...}
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

## Metadata Sources

| Field | Source | Notes |
|-------|--------|-------|
| `backup_uid` | `status.scanLocations[0].backupUID` | From prescan scan locations |
| `backup_target_name` | `spec.backupTarget.name` | From ScanInstance spec |
| `backupplan_uid` | Annotation `trilio.io/backupplan-uid` | Extracted from path |
| `backupplan_name` | Annotation `trilio.io/backupplan-name` | From backup JSON spec |
| `backup_timestamp` | Annotation `trilio.io/backup-creation-timestamp` | From backup JSON metadata |

## Quick Commands

### Check ScanInstance Annotations
```bash
kubectl get scaninstance <name> -o jsonpath='{.metadata.annotations}' | jq
```

### Check ConfigMap Content
```bash
kubectl get configmap scan-config-<name> -o jsonpath='{.data.vm_artifacts_configuration\.json}' | jq '.vm_collection_metadata'
```

### Verify Generated Report
```bash
cat dashboard_reports/scan_report_*.json | jq '.backup_metadata'
```

### Query PostgreSQL
```sql
-- View all backups with scan info
SELECT 
    b.backup_uid,
    b.backup_target_name,
    b.backup_plan_name,
    b.created_at,
    COUNT(bs.scan_id) as total_scans
FROM backups b
LEFT JOIN backup_scans bs ON b.backup_uid = bs.backup_uid
GROUP BY b.backup_uid, b.backup_target_name, b.backup_plan_name, b.created_at
ORDER BY b.created_at DESC;

-- Check latest scans per backup
SELECT 
    b.backup_uid,
    b.backup_target_name,
    bs.scan_id,
    bs.scan_number,
    bs.is_latest
FROM backups b
JOIN backup_scans bs ON b.backup_uid = bs.backup_uid
WHERE bs.is_latest = TRUE
ORDER BY b.created_at DESC;
```

## Troubleshooting

### Annotations Missing on ScanInstance
- Check prescan job logs: `kubectl logs prescan-<name>`
- Verify backup.json/cluster-backup.json exists at backup path
- Confirm prescan completed successfully (not failed)

### ConfigMap Missing vm_collection_metadata
- Check if prescan annotations exist on ScanInstance
- Verify controller logs for ConfigMap creation
- Check ScanInstance has scanLocations populated

### Reports Missing backup_metadata
- Verify ConfigMap has correct structure
- Check scan job mounted ConfigMap correctly
- Review scan engine logs for config loading

## Modified Files

### Python
- `datastore-attacher/shared/backup_detection/tvk_detector.py`
- `datastore-attacher/prescan/cli.py`

### Go
- `internal/constants.go`
- `pkg/helpers/job_helper.go`

## No Changes Needed

- Controller reconciler logic (already passes full ScanInstance)
- Scan Job spec (already mounts ConfigMap)
- Scan engine (already handles `vm_collection_metadata`)
- Database setup (already handles `backup_metadata` from reports)
