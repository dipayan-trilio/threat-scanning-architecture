# Sample Poller Output

## Discovery Phase Output with Enhanced Logging

### Example 1: S3 Target with Multiple Backupplans

```
======================================================================
                    DISCOVERY PHASE
======================================================================
Starting discovery for target: my-s3-target
Looking for backups created since: 2024-12-29 18:30:00

Scanning S3 bucket 'my-bucket' for new backups...
S3 scan complete: checked 1523 objects, found 47 new objects
Found 3 backupplans with new backups (since 2024-12-29 18:30:00)

Backupplans with new backups:
  1. backupplan-abc-123
  2. backupplan-def-456
  3. backupplan-ghi-789

Processing backupplan 1/3: backupplan-abc-123
  ✓ Latest backup: backup-xyz-001
  → Would create ScanInstance for backup backup-xyz-001

Processing backupplan 2/3: backupplan-def-456
  ✓ Latest backup: backup-xyz-002
  → Would create ScanInstance for backup backup-xyz-002

Processing backupplan 3/3: backupplan-ghi-789
  ✓ Latest backup: backup-xyz-003
  → Would create ScanInstance for backup backup-xyz-003

----------------------------------------------------------------------
✓ DISCOVERY COMPLETED SUCCESSFULLY
  - New backups found: 3
  - Backupplans processed: 3
  - ScanInstances created: 3
  - Failed creations: 0
----------------------------------------------------------------------
```

### Example 2: NFS Target with New Backups

```
======================================================================
                    DISCOVERY PHASE
======================================================================
Starting discovery for target: my-nfs-target
Looking for backups created since: 2024-12-30 00:00:00

Mounted NFS nfs-server:/export/backups at /triliodata
Scanning NFS mount '/triliodata' for new backups...
NFS scan complete: found 12 directories modified since 2024-12-30 00:00:00
Found 2 backupplans with new backups

Backupplans with new backups:
  1. backupplan-aaa-111
  2. backupplan-bbb-222

Processing backupplan 1/2: backupplan-aaa-111
  ✓ Latest backup: backup-ccc-333
  → Would create ScanInstance for backup backup-ccc-333

Processing backupplan 2/2: backupplan-bbb-222
  ✓ Latest backup: backup-ddd-444
  → Would create ScanInstance for backup backup-ddd-444

----------------------------------------------------------------------
✓ DISCOVERY COMPLETED SUCCESSFULLY
  - New backups found: 2
  - Backupplans processed: 2
  - ScanInstances created: 2
  - Failed creations: 0
----------------------------------------------------------------------
```

### Example 3: No New Backups Found (S3)

```
======================================================================
                    DISCOVERY PHASE
======================================================================
Starting discovery for target: my-s3-target
Looking for backups created since: 2024-12-30 12:00:00

Scanning S3 bucket 'my-bucket' for new backups...
S3 scan complete: checked 1523 objects, found 0 new objects
Found 0 backupplans with new backups (since 2024-12-30 12:00:00)

No new backups found, skipping mount

----------------------------------------------------------------------
✓ DISCOVERY COMPLETED SUCCESSFULLY
  - New backups found: 0
  - Backupplans processed: 0
  - ScanInstances created: 0
  - Failed creations: 0
----------------------------------------------------------------------
```

### Example 4: Backupplan with No Latest Backup (Error Case)

```
======================================================================
                    DISCOVERY PHASE
======================================================================
Starting discovery for target: my-s3-target
Looking for backups created since: 2024-12-29 18:30:00

Scanning S3 bucket 'my-bucket' for new backups...
S3 scan complete: checked 1523 objects, found 15 new objects
Found 2 backupplans with new backups (since 2024-12-29 18:30:00)

Backupplans with new backups:
  1. backupplan-abc-123
  2. backupplan-xyz-999

Processing backupplan 1/2: backupplan-abc-123
  ✓ Latest backup: backup-xyz-001
  → Would create ScanInstance for backup backup-xyz-001

Processing backupplan 2/2: backupplan-xyz-999
  ✗ No latest backup found for backupplan backupplan-xyz-999

----------------------------------------------------------------------
✓ DISCOVERY COMPLETED SUCCESSFULLY
  - New backups found: 2
  - Backupplans processed: 1
  - ScanInstances created: 1
  - Failed creations: 0
----------------------------------------------------------------------
```

### Example 5: Processing Error

```
======================================================================
                    DISCOVERY PHASE
======================================================================
Starting discovery for target: my-s3-target
Looking for backups created since: 2024-12-29 18:30:00

Scanning S3 bucket 'my-bucket' for new backups...
S3 scan complete: checked 1523 objects, found 25 new objects
Found 3 backupplans with new backups (since 2024-12-29 18:30:00)

Backupplans with new backups:
  1. backupplan-abc-123
  2. backupplan-def-456
  3. backupplan-ghi-789

Processing backupplan 1/3: backupplan-abc-123
  ✓ Latest backup: backup-xyz-001
  → Would create ScanInstance for backup backup-xyz-001

Processing backupplan 2/3: backupplan-def-456
  ✗ Failed to process backupplan backupplan-def-456: Permission denied

Processing backupplan 3/3: backupplan-ghi-789
  ✓ Latest backup: backup-xyz-003
  → Would create ScanInstance for backup backup-xyz-003

----------------------------------------------------------------------
✓ DISCOVERY COMPLETED SUCCESSFULLY
  - New backups found: 3
  - Backupplans processed: 2
  - ScanInstances created: 2
  - Failed creations: 1
----------------------------------------------------------------------
```

## Key Features of Enhanced Logging

### 1. **Initial Scan Information**
- Shows what's being scanned (S3 bucket name or NFS mount path)
- Displays the since_time for filtering

### 2. **Scan Statistics**
- **S3**: Total objects checked and new objects found
- **NFS**: Total directories found modified since the given time

### 3. **Backupplan List**
- Numbered list of all backupplans with new backups
- Easy to see at a glance which backupplans will be processed

### 4. **Progress Tracking**
- Shows current backupplan being processed (e.g., "Processing backupplan 2/3")
- Clear progress indicator throughout the iteration

### 5. **Visual Status Indicators**
- ✓ Success indicators for completed operations
- ✗ Error indicators for failures
- → Action indicators for operations being performed

### 6. **Indented Details**
- Backup-level details are indented for better readability
- Clear hierarchy: backupplan → backup → action

### 7. **Summary Statistics**
- Total backupplans with new backups
- Successfully processed backupplans
- Failed operations (if any)

## Log Levels

All the enhanced logging uses appropriate log levels:

- **INFO**: Normal progress and success messages
- **WARNING**: Non-critical issues (e.g., no latest backup found)
- **ERROR**: Critical failures during processing

## Testing the Output

Run the poller with DEBUG log level to see even more details:

```bash
export LOG_LEVEL="DEBUG"
./poller/QUICK_TEST.sh my-backup-target 24
```

This will show additional debug information including:
- Detailed S3 API calls
- NFS mount operations
- Metadata file parsing
- Timestamp comparisons

