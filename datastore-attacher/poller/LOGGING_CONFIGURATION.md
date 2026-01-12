# Logging Configuration

## Overview

The poller uses structured logging with configurable log levels. By default, verbose boto3/botocore debug logs are suppressed to keep output clean and readable.

## Log Levels

The poller supports standard Python logging levels:
- **DEBUG**: Detailed information for debugging
- **INFO**: General informational messages (default)
- **WARNING**: Warning messages
- **ERROR**: Error messages

Set via environment variable:
```bash
export LOG_LEVEL="DEBUG"  # or INFO, WARNING, ERROR
```

## Suppressed Libraries

The following third-party libraries have their log levels set to WARNING by default to reduce noise:

### 1. **boto3** - AWS SDK for Python
- Suppresses verbose S3 API operation logs
- Only shows warnings and errors

### 2. **botocore** - Low-level AWS library
- Suppresses detailed HTTP request/response logs
- Suppresses signature calculation details
- Suppresses retry handler logs
- Only shows warnings and errors

### 3. **urllib3** - HTTP library
- Suppresses connection pool logs
- Suppresses SSL/TLS handshake details
- Suppresses InsecureRequestWarning (when skipCertVerification is true)
- Only shows warnings and errors

## Implementation

Located in `main.py`:

```python
import logging as python_logging

# Suppress boto3/botocore debug logs
python_logging.getLogger('boto3').setLevel(python_logging.WARNING)
python_logging.getLogger('botocore').setLevel(python_logging.WARNING)
python_logging.getLogger('urllib3').setLevel(python_logging.WARNING)
```

## Before Suppression (Verbose)

```
DEBUG - Event before-parameter-build.s3.ListObjectsV2: calling handler <function set_list_objects_encoding_type_url>
DEBUG - Event before-parameter-build.s3.ListObjectsV2: calling handler <function validate_bucket_name>
DEBUG - Making request for OperationModel(name=ListObjectsV2) with params: {...}
DEBUG - Calculating signature using v4 auth.
DEBUG - CanonicalRequest: GET /dipayan ...
DEBUG - StringToSign: AWS4-HMAC-SHA256 ...
DEBUG - Signature: ac19186cdb17893f7f0e673f6aaed8de79f8f42f89666519c304e9f036f5efc3
DEBUG - Sending http request: <AWSPreparedRequest ...>
DEBUG - Response headers: {'Date': 'Tue, 30 Dec 2025 08:50:28 GMT', ...}
DEBUG - Response body: b'<?xml version="1.0" encoding="UTF-8"?>...'
```

## After Suppression (Clean)

```
INFO - Starting cleanup for target: minio-target
INFO - Listed 3 backup directories from S3 bucket dipayan
INFO - Found 1 backupplans with total 3 backups
INFO - Found 0 total ScanInstances for target
INFO - Cleanup completed: deleted 0 stale ScanInstances
```

## Enabling Debug Logs for Troubleshooting

If you need to see boto3/botocore debug logs for troubleshooting S3 issues:

### Option 1: Modify main.py temporarily
```python
# Comment out or change to DEBUG
python_logging.getLogger('boto3').setLevel(python_logging.DEBUG)
python_logging.getLogger('botocore').setLevel(python_logging.DEBUG)
```

### Option 2: Set log level programmatically
Add this after the suppression lines:
```python
if os.getenv('BOTO_DEBUG', 'false').lower() == 'true':
    python_logging.getLogger('boto3').setLevel(python_logging.DEBUG)
    python_logging.getLogger('botocore').setLevel(python_logging.DEBUG)
```

Then run:
```bash
export BOTO_DEBUG="true"
./poller/QUICK_TEST.sh my-target
```

## Log Output Format

The poller uses JSON-structured logging from the mount_utility logger:

```json
{
  "level": "INFO",
  "file": "/path/to/file.py:123",
  "func": "function_name",
  "time": "2025-12-30T08:50:26+0000",
  "service_type": "",
  "service_id": "",
  "tvk_version": "",
  "tvk_instance_id": "",
  "transaction_type": "Target",
  "group": "",
  "transaction_id": "",
  "transaction_resource_name": "",
  "transaction_resource_namespace": "",
  "msg": "Log message here"
}
```

## Benefits of Suppression

1. **Cleaner Output**: Focus on poller-specific logs, not library internals
2. **Faster Debugging**: Easier to find relevant information
3. **Reduced Log Volume**: Less data to store and process
4. **Better Performance**: Less overhead from excessive logging
5. **Clearer Testing**: Test output is more readable

## What's Still Logged

Even with suppression, you'll still see:
- ✅ All poller-specific INFO/WARNING/ERROR messages
- ✅ S3 operation summaries (e.g., "Listed 3 backup directories")
- ✅ Boto3/botocore WARNING and ERROR messages
- ✅ Connection errors and timeouts
- ✅ Authentication failures
- ✅ Permission denied errors

## What's Suppressed

With suppression, you won't see:
- ❌ Individual HTTP request/response details
- ❌ AWS signature calculation steps
- ❌ Retry handler decisions
- ❌ Connection pool management
- ❌ SSL/TLS handshake details
- ❌ URL encoding/decoding steps
- ❌ Event handler chains

## Example: Clean Discovery Output

```
======================================================================
                    DISCOVERY PHASE
======================================================================
Starting discovery for target: minio-target
Looking for backups created since: 2025-12-29 18:30:00

Scanning S3 bucket 'my-bucket' for new backups...
S3 scan complete: checked 1523 objects, found 47 new objects
Found 3 backupplans with new backups (since 2025-12-29 18:30:00)

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

Much cleaner than the verbose boto3 debug output! 🎉

