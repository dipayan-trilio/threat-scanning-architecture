# Backupplan-Level Owner Reference Filtering - Design Decision

## Overview

This document explains why we filter at the **backupplan level** instead of the **backup level** when detecting child backups of cluster-backups.

---

## 📚 Background

When a ClusterBackupPlan creates backups, it generates:
1. **ClusterBackupPlan** (cluster-scoped)
2. **Namespace-level BackupPlans** (one per namespace) - **owned by ClusterBackupPlan**
3. **ClusterBackup** (cluster-scoped)
4. **Namespace-level Backups** (one per namespace) - **owned by ClusterBackup**

### Hierarchy Structure

```
ClusterBackupPlan (cluster-scoped)
├── owns → BackupPlan (ns1) ← Child backupplan
│   ├── Backup (ns1)
│   ├── Backup (ns1)
│   └── Backup (ns1)
├── owns → BackupPlan (ns2) ← Child backupplan
│   ├── Backup (ns2)
│   ├── Backup (ns2)
│   └── Backup (ns2)
└── ... more namespaces

ClusterBackup (cluster-scoped)
├── owns → Backup (ns1) ← Child of ClusterBackup
├── owns → Backup (ns2) ← Child of ClusterBackup
└── ...
```

---

## ❌ Previous Approach (Inefficient)

### Backup-Level Filtering

```python
def _queue_backup_for_creation(backupplan_uid, backup):
    # Check EVERY backup's ownerReferences
    backup_json = read_json(backup_json_path)
    owner_refs = backup_json.get('metadata', {}).get('ownerReferences', [])
    
    if any(owner.get('kind') == 'ClusterBackup' for owner in owner_refs):
        # Skip this backup
        return
    
    # Queue for creation
    worker_pool.creation_queue.put(message)
```

**Problems:**
1. ❌ Reads `backup.json` for EVERY backup (expensive I/O)
2. ❌ Checks ownerReferences for EVERY backup (100s or 1000s of checks)
3. ❌ Inefficient - if 10 backups under a backupplan, checks 10 times
4. ❌ Only works when backup files are accessible (NFS) - harder for S3

---

## ✅ Current Approach (Efficient)

### Backupplan-Level Filtering

```python
def _read_scan_config(backupplan_uid, backup):
    # Read backupplan.json (already reading for scanConfig anyway)
    backupplan_json = read_json(backupplan_json_path)
    
    # Check backupplan ownerReferences ONCE
    owner_refs = backupplan_json.get('metadata', {}).get('ownerReferences', [])
    
    if any(owner.get('kind') == 'ClusterBackupPlan' for owner in owner_refs):
        # Skip ENTIRE backupplan - all backups are cluster-backup children
        return None
    
    # Read scanConfig and return
    return ScanConfig.from_dict(backupplan_json.get('spec', {}).get('scanConfig'))
```

**Benefits:**
1. ✅ Reads `backupplan.json` only ONCE per backupplan (already needed for scanConfig)
2. ✅ One check per backupplan (not per backup) - 10-100x fewer checks
3. ✅ No additional I/O operations
4. ✅ Works for both NFS and S3 (backupplan always mounted/accessible)
5. ✅ Logical grouping - entire backupplan is child or not

---

## 📊 Performance Comparison

### Example: Target with 50 backupplans, 500 backups

| Approach | Checks | File Reads | Efficiency |
|----------|--------|------------|------------|
| **Backup-Level** | 500 checks | 500 backup.json reads | ❌ Slow |
| **Backupplan-Level** | 50 checks | 0 extra reads* | ✅ Fast |

\* Already reading backupplan.json for scanConfig, so no extra I/O

### Time Saved

Assuming:
- 500 backups across 50 backupplans
- Average 10 backups per backupplan
- File read + JSON parse = ~10ms each

**Backup-level approach:**
- 500 backups × 10ms = **5,000ms (5 seconds)**

**Backupplan-level approach:**
- 50 backupplans × 0ms extra = **0ms additional (instant)**

**Time saved: 5 seconds per polling cycle!**

---

## 🔍 Evidence from Test Files

### Namespace BackupPlan (Child)

```json
{
  "kind": "BackupPlan",
  "metadata": {
    "namespace": "ns1",
    "ownerReferences": [
      {
        "apiVersion": "triliovault.trilio.io/v1",
        "kind": "ClusterBackupPlan",  ← Has ClusterBackupPlan owner!
        "name": "minio-ts-bplan",
        "uid": "90f59617-4101-4492-9bca-1dd621050c10",
        "controller": true
      }
    ]
  }
}
```

### Namespace Backup (Child)

```json
{
  "kind": "Backup",
  "metadata": {
    "namespace": "ns1",
    "ownerReferences": [
      {
        "kind": "ClusterBackup",  ← Has ClusterBackup owner
        "name": "cluster-backup-xyz"
      }
    ]
  }
}
```

**Key Insight:**
- **BackupPlan** has `ClusterBackupPlan` owner
- **Backup** has `ClusterBackup` owner
- Both indicate child relationship, but **BackupPlan check is more efficient!**

---

## 🎯 Implementation Details

### Discovery Flow

```
1. Populate storage state (finds all backups including children)
   ↓
2. For each backupplan:
   ↓
3. Get latest backup
   ↓
4. _read_scan_config(backupplan_uid, backup)  ← Filter happens HERE!
   ├─→ Read backupplan.json
   ├─→ Check ownerReferences
   ├─→ If ClusterBackupPlan owner → return None (skip backupplan)
   └─→ If no cluster owner → return ScanConfig (proceed)
   ↓
5. If scan_config is None → Skip to next backupplan
   ↓
6. If scan_config.enabled → Queue backup for ScanInstance creation
```

**Filter Point:** Step 4 - before even checking if scanning is enabled!

---

## 🚀 Additional Benefits

### 1. **Early Exit**
If backupplan is a child, we exit before:
- Checking scanConfig
- Checking if backup is available
- Checking if ScanInstance exists
- Queuing for creation

### 2. **Cleaner Logs**
```
Processing backupplan 1/50: backupplan-abc-123
  BackupPlan is child of ClusterBackupPlan 'minio-cluster-plan', skipping entire backupplan
```

vs.

```
Processing backupplan 1/50: backupplan-abc-123
  Backup 1: Skipping - child of ClusterBackup
  Backup 2: Skipping - child of ClusterBackup
  Backup 3: Skipping - child of ClusterBackup
  ...
  Backup 10: Skipping - child of ClusterBackup
```

### 3. **Works for All Storage Types**
- ✅ NFS: backupplan.json is always accessible
- ✅ S3: backupplan.json is mounted via s3fuse
- ✅ No special handling needed

---

## 📋 Summary

**Old approach:** Check backup.json ownerReferences for each backup
**New approach:** Check backupplan.json ownerReferences once per backupplan

**Result:**
- ✅ 10-100x fewer checks
- ✅ No additional I/O
- ✅ Cleaner code
- ✅ Better performance
- ✅ Simpler to understand

---

## 🧪 Test Scenarios

### Scenario 1: Standalone BackupPlan
```json
{
  "kind": "BackupPlan",
  "metadata": {
    "ownerReferences": []  // No owner
  }
}
```
**Result:** Process normally, create ScanInstances

### Scenario 2: Child BackupPlan
```json
{
  "kind": "BackupPlan",
  "metadata": {
    "ownerReferences": [
      {"kind": "ClusterBackupPlan"}  // Has cluster owner
    ]
  }
}
```
**Result:** Skip entire backupplan, no ScanInstances created

### Scenario 3: Mixed Target
- 10 standalone backupplans → Process all
- 5 child backupplans (owned by ClusterBackupPlan) → Skip all
- 1 cluster-backupplan → Process (handles children in prescan)

**Result:** 11 backupplans processed (10 standalone + 1 cluster)

---

## ✅ Conclusion

Filtering at the backupplan level is:
- More efficient (fewer checks)
- More logical (entire backupplan is either child or not)
- Simpler to implement
- Better performance
- Cleaner code

This optimization was suggested by the user and is a significant improvement over the initial backup-level filtering approach.
