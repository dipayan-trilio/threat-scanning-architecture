# Target Poller - Testing Guide

## Test Scripts

### `test_discovery.py` - Backup Discovery Test

A dry-run test script that displays all detected backups without creating ScanInstances.

**Features**:
- ✅ Detects backup type (TVK/TVO)
- ✅ Populates storage state
- ✅ Lists all backupplans
- ✅ Shows backup details (UID, type, status, timestamp)
- ✅ Displays scan configuration
- ✅ Provides summary statistics
- ❌ Does NOT create ScanInstances (dry-run only)

---

## Quick Start

### Using Shell Script (Easiest)

```bash
cd datastore-attacher/targetPoller
./TEST_DISCOVERY.sh <target-name>
```

**Example**:
```bash
./TEST_DISCOVERY.sh my-s3-target
```

### Using Python Directly

```bash
cd datastore-attacher/targetPoller
export TARGET_NAME=my-backup-target
python3 test_discovery.py
```

---

## Sample Output

```
================================================================================
  TARGET POLLER - BACKUP DISCOVERY TEST
================================================================================

Target: my-s3-target
Namespace: trilio-system

================================================================================
  BACKUP TYPE: TVK
================================================================================

✓ Storage state populated successfully
  - BackupPlans found: 3
  - Total backups: 12

================================================================================
  BACKUP DETAILS BY BACKUPPLAN
================================================================================

────────────────────────────────────────────────────────────────────────────────
[1/3] BackupPlan: abc-123-def-456-ghi-789
────────────────────────────────────────────────────────────────────────────────

Total backups: 5

Scan Config:
  - Enabled: True
  - Scan Old Backups: False

────────────────────────────────────────────────────────────────────────────────
Backup UID                               Type                 Status       Timestamp           
────────────────────────────────────────────────────────────────────────────────
backup-001-latest                        backup               ✓ Available  2026-01-13 10:30:00 UTC
backup-002-prev                          backup               ✓ Available  2026-01-13 09:15:00 UTC
backup-003-old                           backup               ✓ Available  2026-01-13 08:00:00 UTC
backup-004-failed                        backup               ✗ Failed     2026-01-13 07:00:00 UTC
backup-005-inprogress                    backup               ⋯ InProgress 2026-01-13 06:00:00 UTC

────────────────────────────────────────────────────────────────────────────────
[2/3] BackupPlan: xyz-789-abc-123
────────────────────────────────────────────────────────────────────────────────

Total backups: 4

Scan Config:
  - Enabled: True
  - Scan Old Backups: True

────────────────────────────────────────────────────────────────────────────────
Backup UID                               Type                 Status       Timestamp           
────────────────────────────────────────────────────────────────────────────────
snapshot-001                             snapshot             ✓ Available  2026-01-13 11:00:00 UTC
snapshot-002                             snapshot             ✓ Available  2026-01-13 10:00:00 UTC
cluster-backup-001                       cluster-backup       ✓ Available  2026-01-13 09:30:00 UTC
cluster-snapshot-001                     cluster-snapshot     ✓ Available  2026-01-13 08:30:00 UTC

────────────────────────────────────────────────────────────────────────────────
[3/3] BackupPlan: def-456-ghi-789
────────────────────────────────────────────────────────────────────────────────

Total backups: 3

Scan Config: Not configured

────────────────────────────────────────────────────────────────────────────────
Backup UID                               Type                 Status       Timestamp           
────────────────────────────────────────────────────────────────────────────────
backup-006                               backup               ✓ Available  2026-01-13 12:00:00 UTC
backup-007                               backup               ✓ Available  2026-01-13 11:30:00 UTC
backup-008                               backup               ✗ Failed     2026-01-13 11:00:00 UTC

================================================================================
  SUMMARY
================================================================================
BackupPlans: 3
Total Backups: 12
  - Available: 9
  - Failed: 2
  - Other: 1

✓ Discovery test completed successfully
================================================================================
```

---

## Output Explanation

### Section 1: Target Information
```
Target: my-s3-target
Namespace: trilio-system
```
Shows which target is being tested.

### Section 2: Backup Type Detection
```
BACKUP TYPE: TVK
```
Detected backup format (TVK or TVO).

### Section 3: Storage State
```
✓ Storage state populated successfully
  - BackupPlans found: 3
  - Total backups: 12
```
Number of backupplans and backups found in target.

### Section 4: Backup Details

For each backupplan:

**Header**:
```
[1/3] BackupPlan: abc-123-def-456-ghi-789
Total backups: 5
```

**Scan Configuration** (from backupplan.json):
```
Scan Config:
  - Enabled: True
  - Scan Old Backups: False
```

**Backup Table**:
```
Backup UID                    Type          Status       Timestamp
backup-001                    backup        ✓ Available  2026-01-13 10:30:00 UTC
```

**Status Indicators**:
- ✓ Available - Ready for scanning
- ✗ Failed/Error - Backup failed
- ⋯ Other - In progress or unknown

### Section 5: Summary
```
BackupPlans: 3
Total Backups: 12
  - Available: 9
  - Failed: 2
  - Other: 1
```
Overall statistics across all backupplans.

---

## Use Cases

### 1. Verify Backup Detection

Check if targetPoller can detect all your backups:
```bash
./TEST_DISCOVERY.sh my-backup-target
```

Look for:
- Correct number of backupplans
- All expected backups listed
- Correct status for each backup

### 2. Check Scan Configuration

Verify scanConfig is read correctly:
```bash
./TEST_DISCOVERY.sh my-backup-target | grep -A 2 "Scan Config"
```

Expected output:
```
Scan Config:
  - Enabled: True
  - Scan Old Backups: False
```

### 3. Find Available Backups

List only Available backups:
```bash
./TEST_DISCOVERY.sh my-backup-target | grep "✓ Available"
```

### 4. Debug Missing Backups

If backups are missing:
1. Check "Total backups" count
2. Verify backup directories exist in target
3. Check if backups are too recent (<5 minutes)
4. Verify metadata files exist (backup.json, etc.)

### 5. Compare with Old Poller

Run both test scripts and compare:
```bash
# Old poller
cd datastore-attacher/poller
./QUICK_TEST.sh <target-name>

# Target poller
cd datastore-attacher/targetPoller
./TEST_DISCOVERY.sh <target-name>
```

---

## Environment Variables

### Required
- `TARGET_NAME`: Name of the BackupTarget CR

### Optional
- `TARGET_NAMESPACE`: Namespace (default: `trilio-system`)
- `LOG_LEVEL`: Logging level (default: `INFO`)
  - Set to `DEBUG` for detailed logs

### Example with Custom Settings
```bash
export TARGET_NAME=my-backup-target
export TARGET_NAMESPACE=custom-namespace
export LOG_LEVEL=DEBUG
python3 test_discovery.py
```

---

## Troubleshooting

### Issue: "TARGET_NAME environment variable is required"

**Fix**: Provide target name
```bash
./TEST_DISCOVERY.sh my-backup-target
```

### Issue: "BackupTarget 'xxx' not found"

**Fix**: Check target exists
```bash
kubectl get targets.triliovault.trilio.io
```

### Issue: "No backupplans found in target"

**Possible causes**:
1. Target is empty (no backups)
2. Mount failed (for NFS)
3. S3 credentials incorrect
4. All backups filtered out (too recent)

**Debug**:
```bash
export LOG_LEVEL=DEBUG
./TEST_DISCOVERY.sh my-backup-target 2>&1 | grep -i error
```

### Issue: "Could not read backupplan.json"

**Possible causes**:
1. Backup incomplete (still running)
2. Corrupted metadata
3. Wrong file format (manifest vs plain)

**Debug**:
Check if files exist in target storage directly.

### Issue: All backups show status "ERROR"

**Possible causes**:
1. Cannot read metadata files
2. Mount point incorrect
3. File permissions issue

**Debug**:
```bash
# For NFS
ls -la /triliodata/backupplan-uid/backup-uid/

# Check mount
mount | grep triliodata
```

---

## Advanced Usage

### Save Output to File
```bash
./TEST_DISCOVERY.sh my-backup-target > test_results.txt 2>&1
```

### Filter Specific BackupPlan
```bash
./TEST_DISCOVERY.sh my-backup-target | grep -A 20 "BackupPlan: abc-123"
```

### Count Available Backups
```bash
./TEST_DISCOVERY.sh my-backup-target | grep -c "✓ Available"
```

### Debug Logging
```bash
export LOG_LEVEL=DEBUG
./TEST_DISCOVERY.sh my-backup-target 2>&1 | tee debug.log
```

---

## Comparison with Old Poller Test

| Feature | Old Poller `QUICK_TEST.sh` | Target Poller `TEST_DISCOVERY.sh` |
|---------|---------------------------|----------------------------------|
| **Backup Detection** | ✅ Yes | ✅ Yes |
| **Status Display** | ✅ Yes | ✅ Yes |
| **Timestamp Display** | ✅ Yes | ✅ Yes |
| **Scan Config** | ❌ No | ✅ Yes |
| **Storage State** | ❌ Temporary | ✅ Persistent |
| **Summary Stats** | ⚠️ Basic | ✅ Detailed |
| **Sorted by Time** | ✅ Yes | ✅ Yes |
| **Dry-Run** | ✅ Yes | ✅ Yes |

---

## Next Steps

After running the test:

1. ✅ Verify all backups are detected
2. ✅ Check scan configurations are correct
3. ✅ Confirm statuses match expected values
4. ✅ Compare with old poller output (if available)
5. ✅ Run full poller with actual ScanInstance creation:
   ```bash
   cd datastore-attacher/targetPoller
   export TARGET_NAME=my-backup-target
   python3 main.py
   ```

---

## Files

- `test_discovery.py` - Python test script
- `TEST_DISCOVERY.sh` - Shell wrapper for easy execution
- `TESTING_GUIDE.md` - This guide

---

## Tips

💡 **Run test before running main poller** to verify discovery works

💡 **Use DEBUG logging** to troubleshoot issues

💡 **Compare with old poller** to ensure compatibility

💡 **Save output** for documentation/reporting

💡 **Run periodically** to verify new backups are detected

---

## Summary

The test script provides a **safe, dry-run way** to verify backup discovery without creating any ScanInstances. Use it to:

✅ Validate backup detection  
✅ Check scan configurations  
✅ Debug discovery issues  
✅ Compare with old poller  
✅ Document backup state  

Happy testing! 🧪

