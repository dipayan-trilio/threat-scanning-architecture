# Poller Flow Summary - Updated Architecture

## Overview

The poller now follows a **detect-first** approach where backup type is determined by examining the actual backup directory structure **before** creating the handler.

---

## Complete Step-by-Step Flow

### **Phase 1: Initialization**

```
1. Load environment variables
   └─ BACKUP_TARGET_NAME (required)
   └─ LOG_LEVEL (optional, default: INFO)

2. Initialize Kubernetes client
   └─ Load in-cluster config or kubeconfig
   └─ Setup CustomObjectsApi for CRs
   └─ Setup CoreV1Api for Secrets/ConfigMaps
```

### **Phase 2: Pre-flight Checks**

```
3. Check ReportingTarget availability
   └─ List all Target CRs
   └─ Find Target with annotation: trilio.io/reporting-target=true
   └─ Verify status = 'Available'
   └─ Exit if not available

4. Get BackupTarget CR
   └─ Fetch Target CR by name (from BACKUP_TARGET_NAME)
   └─ Parse using triliodata_crd_parser
   └─ Extract credentials (S3 or NFS)
   
   Note: Poller CronJob is only created when BackupTarget is 'Available',
         so we assume target is available and don't check status
```

### **Phase 3: Cleanup Phase** ✅ **IMPLEMENTED**

```
5. Detect backup type from target structure
   │
   ├─ Create BackupTypeDetector
   │
   ├─ For S3:
   │  ├─ Create boto3 client
   │  ├─ List first backupplan (max 10 results)
   │  ├─ List first backup under that backupplan
   │  ├─ Check if tvk-meta.json exists (head_object)
   │  └─ Return 'TVK' if found, 'UNKNOWN' otherwise
   │
   └─ For NFS:
      ├─ Mount NFS target
      ├─ Find first backup directory (find -mindepth 2 -maxdepth 2)
      ├─ Check if tvk-meta.json exists in that directory
      ├─ Unmount NFS
      └─ Return 'TVK' if found, 'UNKNOWN' otherwise

6. Create appropriate handler
   │
   ├─ Use BackupTargetHandlerFactory
   ├─ Pass detected backup_type
   │
   ├─ If backup_type == 'TVK':
   │  └─ Create TVKBackupTargetHandler
   │
   ├─ If backup_type == 'TVO':
   │  └─ Create TVOBackupTargetHandler
   │
   └─ If backup_type == 'UNKNOWN':
      └─ Default to TVKBackupTargetHandler (with warning)

7. Get target data (SINGLE operation)
   │
   ├─ For S3:
   │  ├─ Create boto3 client with parsed credentials
   │  ├─ Paginated list_objects_v2 call
   │  ├─ List all backupplan directories (depth 1)
   │  └─ For each backupplan, list backup directories (depth 2)
   │
   └─ For NFS:
      ├─ Mount NFS using parsed credentials
      └─ Single find command: find <mount> -mindepth 2 -maxdepth 2 -type d

8. Parse directory structure (SINGLE pass)
   │
   ├─ Iterate through all backup directories
   ├─ Extract backupplan-uid and backup-uid from path
   ├─ Build map: {backupplan-uid: {backup-uids}}
   └─ Return complete mapping

9. List ALL ScanInstances for this target (SINGLE K8s call)
   │
   ├─ Query with label_selector: "target-uid=<target-uid>"
   ├─ Get all ScanInstance CRs at once
   └─ Group by backupplan-uid

10. Compare and delete stale ScanInstances
    │
    For each backupplan in ScanInstances:
    │
    ├─ If backupplan EXISTS in target:
    │  │
    │  ├─ Get actual backup UIDs from map
    │  │
    │  └─ For each ScanInstance:
    │     ├─ Get backup-uid from labels
    │     ├─ Check if backup-uid in actual backups
    │     └─ If NOT → Delete ScanInstance (STALE)
    │        └─ Log: "STALE: backup no longer exists"
    │
    └─ If backupplan NOT in target:
       │
       ├─ Backupplan was deleted from target
       ├─ Delete ALL ScanInstances for this backupplan
       └─ Log: "AGGRESSIVE: backupplan deleted"

11. Cleanup and report
    │
    ├─ Unmount NFS (if mounted)
    │
    ├─ Calculate statistics:
    │  ├─ Backupplans processed
    │  ├─ Total backups found
    │  ├─ ScanInstances deleted
    │  └─ Failed deletions
    │
    └─ Return CleanupResult
```

### **Phase 4: Discovery Phase** ⏳ **TODO**

```
12. Discovery phase (not yet implemented)
    └─ Discover new backups since last run
    └─ Create ScanInstance CRs for unscanned backups
    └─ Handle scanOldBackups scenarios
```

### **Phase 5: Final Summary**

```
13. Print summary
    └─ Cleanup Phase: ✓ SUCCESS / ✗ FAILED
    └─ Discovery Phase: ✓ SUCCESS / ✗ FAILED

14. Exit with appropriate code
    └─ 0 if all phases succeeded
    └─ 1 if any phase failed
```

---

## Key Changes from Previous Design

### **Before (Annotation-Based)**
```
1. Check annotation: trilio.io/backup-type
2. Create handler based on annotation or default to TVK
3. Handler performs cleanup
```

### **After (Detection-Based)** ✅
```
1. Examine backup directory structure
2. Detect backup type by looking for tvk-meta.json
3. Create handler based on detected type
4. Handler performs cleanup
```

---

## Backup Type Detection Logic

### **TVK Detection**

**Indicator**: Presence of `tvk-meta.json` file

**Expected Structure**:
```
backupplan-uid/
  └─ backup-uid/
      └─ tvk-meta.json  ← TVK indicator
```

**Detection Process**:

**For S3**:
1. List first backupplan (1 API call)
2. List first backup under that backupplan (1 API call)
3. Check if `tvk-meta.json` exists using `head_object` (1 API call)
4. Return 'TVK' if found

**For NFS**:
1. Mount NFS (1 mount operation)
2. Find first backup directory (1 find command)
3. Check if `tvk-meta.json` file exists (1 file check)
4. Unmount NFS (1 unmount operation)
5. Return 'TVK' if found

**Total Operations**:
- S3: 3 API calls
- NFS: 1 mount + 1 find + 1 file check + 1 unmount

### **TVO Detection** ⏳ **TODO**

Currently not implemented. When implemented:
- Look for TVO-specific indicator files
- Similar detection process as TVK

---

## Performance Analysis

### **Detection Phase**
- **S3**: +3 API calls (before cleanup starts)
- **NFS**: +1 mount cycle (before cleanup starts)
- **One-time cost**: Only runs once at the beginning

### **Cleanup Phase** (Unchanged)
- **S3**: 1 list call + N K8s calls
- **NFS**: 1 mount + 1 find + 1 unmount + N K8s calls
- **Time**: O(B + N) where B = backups, N = backupplans
- **Space**: O(B) in memory

### **Total Operations**

**S3 Target**:
```
Detection:  3 API calls
Cleanup:    1 API call + N K8s calls
Total:      4 API calls + N K8s calls
```

**NFS Target**:
```
Detection:  1 mount cycle
Cleanup:    1 mount cycle + 1 find + N K8s calls
Total:      2 mount cycles + 1 find + N K8s calls
```

---

## Components

### **1. BackupTypeDetector** (`cleanup/detector.py`)
- **Purpose**: Detect backup type by examining directory structure
- **Methods**:
  - `detect()`: Main detection method
  - `_detect_s3()`: S3-specific detection
  - `_detect_nfs()`: NFS-specific detection
- **Returns**: 'TVK', 'TVO', or 'UNKNOWN'

### **2. BackupTargetHandlerFactory** (`cleanup/factory.py`)
- **Purpose**: Create appropriate handler based on detected type
- **Input**: backup_type parameter (no longer reads annotation)
- **Output**: TVKBackupTargetHandler or TVOBackupTargetHandler

### **3. BaseBackupTargetHandler** (`cleanup/base_handler.py`)
- **Purpose**: Abstract base class for cleanup operations
- **Changes**: Removed detection logic (now handled by detector)
- **Methods**: Cleanup orchestration only

### **4. TVKBackupTargetHandler** (`cleanup/tvk_handler.py`)
- **Purpose**: TVK-specific cleanup implementation
- **Methods**: `parse_directory_structure()`, `detect_backup_type()` (legacy)

### **5. TVOBackupTargetHandler** (`cleanup/tvo_handler.py`)
- **Purpose**: TVO-specific cleanup implementation (skeleton)
- **Status**: Returns 'UNKNOWN' until TVO structure is known

---

## Example Output

```
======================================================================
               THREAT SCANNING POLLER
======================================================================
Target: my-backup-target

Checking ReportingTarget availability...
✓ ReportingTarget 'reporting-target' is available

Fetching BackupTarget 'my-backup-target'...
✓ BackupTarget 'my-backup-target' fetched successfully

======================================================================
                    CLEANUP PHASE
======================================================================
Step 1: Detecting backup type from target structure...
Detecting backup type...
Found tvk-meta.json at backupplan-abc/backup-123/tvk-meta.json
Detected backup type: TVK
Backup type: TVK

Step 2: Creating handler...
Creating TVK handler

Step 3: Performing cleanup...
Starting cleanup for target: my-backup-target
Listed 150 backup directories from S3 bucket my-bucket
Found 10 backupplans with total 150 backups
Found 145 total ScanInstances for target
STALE: ScanInstance si-abc-123 references backup backup-xyz which no longer exists
AGGRESSIVE: Backupplan bp-old-456 deleted from target, cleaning up 3 ScanInstances
Cleanup completed: deleted 4 stale ScanInstances

----------------------------------------------------------------------
✓ CLEANUP COMPLETED SUCCESSFULLY
  - Backup type: TVK
  - Backupplans processed: 10
  - Total backups found: 150
  - Stale ScanInstances deleted: 4
  - Failed deletions: 0
----------------------------------------------------------------------

======================================================================
                    DISCOVERY PHASE
======================================================================
TODO: Discovery phase not yet implemented
======================================================================

======================================================================
                         SUMMARY
======================================================================
  Cleanup Phase:    ✓ SUCCESS
  Discovery Phase:  ✓ SUCCESS
======================================================================
Poller completed successfully
```

---

## Benefits of New Approach

1. **✅ No Annotation Required**: Users don't need to manually set backup type
2. **✅ Automatic Detection**: Poller intelligently detects backup type
3. **✅ Accurate**: Based on actual backup structure, not user input
4. **✅ Extensible**: Easy to add TVO detection in future
5. **✅ Clear Separation**: Detection logic separated from cleanup logic
6. **✅ Testable**: Each component can be tested independently

---

## Future Enhancements

### **1. TVO Detection**
Implement TVO-specific detection logic when TVO structure is known.

### **2. Detection Caching**
Cache detected type to avoid repeated detection on retries.

### **3. Multi-Type Support**
Support targets with mixed TVK/TVO backups (if needed).

### **4. Detection Metrics**
Add Prometheus metrics for detection success/failure rates.

---

**Summary**: The poller now follows a logical flow where backup type is detected first by examining the actual backup directory structure, then the appropriate handler is created based on the detected type. No annotations required! 🎯

