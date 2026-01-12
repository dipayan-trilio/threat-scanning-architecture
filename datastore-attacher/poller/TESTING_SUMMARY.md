# Testing Summary - Discovery Lookback Configuration

## Quick Answer

### Where is the 6-hour default set?

**File**: `cleanup/base_handler.py`  
**Method**: `get_last_successful_run_time()`  
**Lines**: 608, 614

```python
return datetime.utcnow() - timedelta(hours=6)
```

### How to change it for testing?

**Set environment variable**:
```bash
export DISCOVERY_LOOKBACK_HOURS="24"  # Use 24 hours instead of 6
```

**No code changes needed!** The default is now configurable via environment variable.

## Testing from Local Machine

### Quick Start

```bash
# 1. Make the test script executable (already done)
chmod +x poller/QUICK_TEST.sh

# 2. Run with default 6 hours lookback
./poller/QUICK_TEST.sh my-backup-target

# 3. Run with custom lookback (e.g., 24 hours for testing)
./poller/QUICK_TEST.sh my-backup-target 24

# 4. Run with 7 days lookback (for testing old backups)
./poller/QUICK_TEST.sh my-backup-target 168
```

### What the Script Does

1. ✅ Sets up all required environment variables
2. ✅ Verifies kubectl access to the target
3. ✅ Runs the poller with your specified lookback hours
4. ✅ Shows colored output for easy reading
5. ✅ Exits with proper status code

### Manual Testing (Without Script)

```bash
# Set environment variables
export BACKUP_TARGET_NAME="my-backup-target"
export CRONJOB_NAME="poller-my-backup-target"
export CRONJOB_NAMESPACE="default"
export DISCOVERY_LOOKBACK_HOURS="24"  # ← Change this for testing
export LOG_LEVEL="DEBUG"
export VM_MOUNT="true"

# Run poller
cd /home/dipayanpramanik/Devops/trilio/repo/threat-scanning-architecture/datastore-attacher
python3 poller/main.py
```

## Reverting to Default After Testing

### Option 1: Unset the variable
```bash
unset DISCOVERY_LOOKBACK_HOURS
# Will use default of 6 hours
```

### Option 2: Explicitly set to 6
```bash
export DISCOVERY_LOOKBACK_HOURS="6"
```

### Option 3: Don't set it in production
In production Kubernetes CronJob, simply don't include `DISCOVERY_LOOKBACK_HOURS` in the env vars. The code will automatically use 6 hours as the default.

## Code Changes Made

### 1. Made lookback hours configurable

**Before**:
```python
return datetime.utcnow() - timedelta(hours=6)  # Hardcoded
```

**After**:
```python
lookback_hours = int(os.getenv('DISCOVERY_LOOKBACK_HOURS', '6'))  # Configurable
return datetime.utcnow() - timedelta(hours=lookback_hours)
```

### 2. Updated documentation

- ✅ `main.py` - Added `DISCOVERY_LOOKBACK_HOURS` to environment variables list
- ✅ `LOCAL_TESTING_GUIDE.md` - Comprehensive testing guide created
- ✅ `QUICK_TEST.sh` - Quick test script created
- ✅ `TESTING_SUMMARY.md` - This summary document

## Testing Scenarios

### Scenario 1: Default Behavior (6 Hours)
```bash
# Don't set DISCOVERY_LOOKBACK_HOURS
./poller/QUICK_TEST.sh my-backup-target
```
**Result**: Discovers backups from last 6 hours

### Scenario 2: Test with 24 Hours
```bash
./poller/QUICK_TEST.sh my-backup-target 24
```
**Result**: Discovers backups from last 24 hours

### Scenario 3: Test with 7 Days
```bash
./poller/QUICK_TEST.sh my-backup-target 168
```
**Result**: Discovers backups from last 7 days (168 hours)

### Scenario 4: Test with 30 Days
```bash
./poller/QUICK_TEST.sh my-backup-target 720
```
**Result**: Discovers backups from last 30 days (720 hours)

## Common Lookback Values

| Duration | Hours | Use Case |
|----------|-------|----------|
| 1 hour | 1 | Test with very recent backups |
| 6 hours | 6 | **Default** - Production use |
| 12 hours | 12 | Extended window |
| 1 day | 24 | Testing with daily backups |
| 3 days | 72 | Testing with older backups |
| 1 week | 168 | Testing with weekly backups |
| 1 month | 720 | Testing with very old backups |

## Production Deployment

### Kubernetes CronJob Example

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: poller-my-backup-target
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: poller
            image: threat-scanning-poller:latest
            env:
            - name: BACKUP_TARGET_NAME
              value: "my-backup-target"
            - name: CRONJOB_NAME
              value: "poller-my-backup-target"
            - name: CRONJOB_NAMESPACE
              value: "default"
            # DISCOVERY_LOOKBACK_HOURS not set - uses default of 6
            # Uncomment below to override:
            # - name: DISCOVERY_LOOKBACK_HOURS
            #   value: "12"
```

### When to Override in Production

You might want to set `DISCOVERY_LOOKBACK_HOURS` in production if:

1. **Longer CronJob interval**: If your CronJob runs every 12 hours, set lookback to 12+ hours
2. **Initial deployment**: Set to a larger value (e.g., 168 hours) for the first run to catch older backups
3. **Missed runs**: If CronJob might miss runs, increase the lookback window for safety

## Troubleshooting

### Issue: "No new backups found" but you know there are new backups

**Solution**: Increase `DISCOVERY_LOOKBACK_HOURS`:
```bash
./poller/QUICK_TEST.sh my-backup-target 168  # Try 7 days
```

### Issue: Too many backups being discovered

**Solution**: Decrease `DISCOVERY_LOOKBACK_HOURS`:
```bash
./poller/QUICK_TEST.sh my-backup-target 1  # Only last hour
```

### Issue: Want to test without affecting real CronJob status

**Solution**: Use a fake CronJob name:
```bash
export CRONJOB_NAME="test-fake-cronjob"
export DISCOVERY_LOOKBACK_HOURS="24"
python3 poller/main.py
```
The poller will log: "Failed to get CronJob status, defaulting to 24 hours ago"

## Files Created/Modified

### Modified
- ✅ `cleanup/base_handler.py` - Made lookback hours configurable
- ✅ `main.py` - Documented new environment variable

### Created
- ✅ `LOCAL_TESTING_GUIDE.md` - Comprehensive testing guide
- ✅ `QUICK_TEST.sh` - Quick test script with arguments
- ✅ `TESTING_SUMMARY.md` - This summary document

## Summary

✅ **Default**: 6 hours (no configuration needed)  
✅ **Configurable**: Via `DISCOVERY_LOOKBACK_HOURS` environment variable  
✅ **Testing**: Use `QUICK_TEST.sh` script for easy local testing  
✅ **Production**: Don't set the variable to use the default  
✅ **No code changes**: Just set/unset environment variable  

**Quick command to remember**:
```bash
# Test with 24 hours lookback
./poller/QUICK_TEST.sh <target-name> 24

# Revert to default (6 hours)
unset DISCOVERY_LOOKBACK_HOURS
```

