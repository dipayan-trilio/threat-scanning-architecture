# ScanInstance Label Strategy

## Overview

This document explains the label strategy for ScanInstance CRs created by targetPoller and their relationship with prescan validation.

---

## Labels Set by Target Poller

When creating a ScanInstance, the poller sets **only** the backup-target label:

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: <random-uuid>
  labels:
    trilio.io/backup-target: <target-name>      # Target NAME (not UID)
spec:
  backupTarget:
    name: <target-name>
    uid: <target-uid>
    ...
  backupRef:
    uid: <backup-uid>
    path: <backup-path>
```

---

## Labels Added by Prescan Validation

After prescan validation completes, it enriches with all labels:

```yaml
metadata:
  labels:
    # Already set by poller
    trilio.io/backup-target: <target-name>
    
    # Added by prescan
    trilio.io/backupplan: <backupplan-uid>      # Parsed from backup path
    trilio.io/backup: <backup-uid>              # Parsed from backup path
    trilio.io/instance-id: <tvk-instance-id|tvo-instance-id>  # From tvk-meta.json
  
  annotations:
    # Added by prescan
    trilio.io/vm-workload: "true|false"
```

---

## Design Decision: Minimal Labels at Creation

### Why Poller Sets Only backup-target Label

**Reason 1: Support Manual ScanInstance Creation**
- Users can manually create ScanInstances
- Prescan handles enrichment for both poller-created and manually-created ScanInstances
- Centralizes label logic in one place (prescan)

**Reason 2: Prescan is Source of Truth**
- Prescan **parses** the backup path to extract backupplan/backup UIDs
- Prescan **validates** the backup exists and is valid
- Labels reflect validated information, not assumptions

**Reason 3: Cleanup Can Wait**
- Newly created backups won't be deleted immediately anyway
- Cleanup skips ScanInstances without backupplan/backup labels (prescan incomplete)
- Next polling cycle will process them after prescan completes

```python
# Cleanup phase handles missing labels gracefully
for si in scaninstances:
    backupplan_uid = si.labels.get('trilio.io/backupplan', '')
    backup_uid = si.labels.get('trilio.io/backup', '')
    
    if not backupplan_uid or not backup_uid:
        # Prescan not completed yet, skip for now
        continue
    
    # Compare with storage state
    if not storage_state.has_backup(backupplan_uid, backup_uid):
        queue_for_deletion(si)
```

---

## Design Decision: Use Target NAME (not UID)

### Why backup-target Label Uses Name

```yaml
# ✅ Using target name
trilio.io/backup-target: my-s3-backup-target

# ❌ Not using target UID
# trilio.io/backup-target: 4d4e8073-9741-4b32-abb1-a4e4c759af76
```

**Reason 1: Better Readability**
```bash
# Easy to understand
kubectl get scaninstances -l trilio.io/backup-target=my-s3-target

# vs. Hard to remember
kubectl get scaninstances -l trilio.io/backup-target=4d4e8073-9741-4b32-abb1-a4e4c759af76
```

**Reason 2: Matches spec.backupTarget.name**
```yaml
spec:
  backupTarget:
    name: my-s3-backup-target  # Using name here
    uid: 4d4e8073-9741-4b32-abb1-a4e4c759af76
```

**Reason 3: User-Friendly**
- Users refer to targets by name, not UID
- Easier for troubleshooting and filtering
- Consistent with user expectations

**Note**: Target UID is still available in `spec.backupTarget.uid` for uniqueness.

---

## Responsibility Division

| Label | Set By | Purpose |
|-------|--------|---------|
| `trilio.io/backup-target` | Poller | Filter ScanInstances by target |
| `trilio.io/backupplan` | **Prescan** | Cleanup comparison, filtering (parsed from path) |
| `trilio.io/backup` | **Prescan** | Cleanup comparison, filtering (parsed from path) |
| `trilio.io/instance-id` | **Prescan** | Track TVK/TVO instance (from tvk-meta.json) |

### Poller's Role
- Sets **only** backup-target label for target-level filtering
- Creates ScanInstance with spec containing backup path
- Discovery and creation logic

### Prescan's Role
- **Parses** backup path to extract backupplan/backup UIDs
- **Validates** backup exists and is accessible
- **Enriches** ScanInstance with all labels (backupplan, backup, instance-id)
- **Adds** vm-workload annotation after checking metadata
- Handles both poller-created and manually-created ScanInstances

---

## Label Selector Usage

### In Cleanup Phase

```python
# List all ScanInstances for this target
label_selector = f"trilio.io/backup-target={target_name}"
scaninstances = k8s_client.list_scan_instances(label_selector)

# Compare with storage state
for si in scaninstances:
    backupplan_uid = si.labels['trilio.io/backupplan']
    backup_uid = si.labels['trilio.io/backup']
    
    if not storage_state.has_backupplan(backupplan_uid):
        # Delete all ScanInstances for this backupplan
        queue_for_deletion(si)
    elif not storage_state.has_backup(backupplan_uid, backup_uid):
        # Delete this specific ScanInstance
        queue_for_deletion(si)
```

### User Queries

```bash
# All ScanInstances for a target
kubectl get scaninstances -l trilio.io/backup-target=my-target

# All ScanInstances for a backupplan
kubectl get scaninstances -l trilio.io/backupplan=abc-123

# All ScanInstances for a specific backup
kubectl get scaninstances -l trilio.io/backup=xyz-789

# Combined filters
kubectl get scaninstances \
  -l trilio.io/backup-target=my-target,\
     trilio.io/backupplan=abc-123
```

---

## Benefits of This Approach

✅ **Supports manual creation** - Users can create ScanInstances manually  
✅ **Centralized logic** - All label enrichment in one place (prescan)  
✅ **Prescan is source of truth** - Labels reflect validated/parsed data  
✅ **Cleanup handles gracefully** - Skips ScanInstances without labels (prescan incomplete)  
✅ **User-friendly** - Target name is readable  
✅ **Consistent** - Matches spec.backupTarget.name  
✅ **No duplication** - Poller doesn't replicate prescan's parsing logic  

---

## Alternative Considered (Rejected)

### Full Labels at Creation

**What**: Poller sets all labels at creation
```yaml
# At creation (poller)
labels:
  trilio.io/backup-target: <target-name>
  trilio.io/backupplan: <backupplan-uid>    # Set by poller
  trilio.io/backup: <backup-uid>            # Set by poller

# After prescan
labels:
  trilio.io/backup-target: <target-name>
  trilio.io/backupplan: <backupplan-uid>    # Validated by prescan
  trilio.io/backup: <backup-uid>            # Validated by prescan
  trilio.io/instance-id: <instance-id>      # Added by prescan
```

**Why Rejected**:
- ❌ Doesn't support manually created ScanInstances
- ❌ Duplicates label logic in two places (poller and prescan)
- ❌ Prescan must still parse and validate, making poller's labels redundant
- ❌ Cleanup can wait for prescan - not time-critical

---

## Example Lifecycle

### 1. Creation (by Poller)
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: abc-123-def-456
  labels:
    trilio.io/backup-target: my-s3-target    # Only label set by poller
spec:
  backupTarget:
    name: my-s3-target
    uid: 4d4e8073-9741-4b32-abb1-a4e4c759af76
  backupRef:
    uid: backup-xyz
    path: backupplan-abc/backup-xyz          # Prescan will parse this
status:
  status: Queued
```

### 2. After Prescan Validation
```yaml
metadata:
  name: abc-123-def-456
  labels:
    trilio.io/backup-target: my-s3-target
    trilio.io/backupplan: backupplan-abc     # ✅ Added by prescan (parsed from path)
    trilio.io/backup: backup-xyz             # ✅ Added by prescan (parsed from path)
    trilio.io/instance-id: tvk-instance-123  # ✅ Added by prescan (from tvk-meta.json)
  annotations:
    trilio.io/vm-workload: "true"            # ✅ Added by prescan
status:
  type: TVK                                   # ✅ Set by prescan
  status: InProgress
  phase: PreScan
  phaseStatus: Completed
```

### 3. During Cleanup

If backup is deleted from target:
```python
# Poller lists ScanInstances
label_selector = "trilio.io/backup-target=my-s3-target"
scaninstances = k8s_client.list_scan_instances(label_selector)

# Check against storage state
for si in scaninstances:
    backupplan_uid = si.labels.get('trilio.io/backupplan', '')
    backup_uid = si.labels.get('trilio.io/backup', '')
    
    if not backupplan_uid or not backup_uid:
        # Prescan hasn't completed yet, skip for now
        continue
    
    if not storage_state.has_backup(backupplan_uid, backup_uid):
        delete_scaninstance(si.name)
```

### 4. Manual Creation (by User)

User can also create ScanInstances manually:
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: manual-scan-001
  labels:
    trilio.io/backup-target: my-nfs-target   # User sets this
spec:
  backupTarget:
    name: my-nfs-target
    uid: ...
  backupRef:
    path: my-backupplan/my-backup            # Prescan will parse
```

Prescan will enrich it the same way as poller-created ScanInstances.

---

## Label Enrichment by Prescan

Prescan job is responsible for parsing and adding all labels:

```python
# In prescan job
# 1. Parse backup path to extract UIDs
backup_path = scaninstance.spec.backupRef.path  # e.g., "backupplan-abc/backup-xyz"
backupplan_uid, backup_uid = parse_backup_path(backup_path)

# 2. Read tvk-meta.json to get instance ID
instance_id = read_tvk_meta_json(backup_path)

# 3. Enrich ScanInstance with labels
scaninstance.labels['trilio.io/backupplan'] = backupplan_uid
scaninstance.labels['trilio.io/backup'] = backup_uid
scaninstance.labels['trilio.io/instance-id'] = instance_id

# 4. Add annotations
scaninstance.annotations['trilio.io/vm-workload'] = "true"  # if VM workload detected
```

This centralized approach handles **both** poller-created and manually-created ScanInstances.

---

## Summary

| Aspect | Strategy | Reason |
|--------|----------|--------|
| **backup-target** | Set by poller | Target-level filtering, readability |
| **backupplan** | **Set by prescan** | Parsed from validated backup path |
| **backup** | **Set by prescan** | Parsed from validated backup path |
| **instance-id** | Set by prescan | Read from tvk-meta.json |
| **Validation** | All done by prescan | Single source of truth |
| **Ownership** | Clear separation | Poller creates, prescan enriches |

**Key Principle**: Centralize label enrichment in prescan to support both automated (poller) and manual ScanInstance creation. Cleanup can gracefully handle the delay.

This approach ensures **flexibility** (manual creation supported) with **architectural clarity** (prescan is the single source of truth for labels). ✅

