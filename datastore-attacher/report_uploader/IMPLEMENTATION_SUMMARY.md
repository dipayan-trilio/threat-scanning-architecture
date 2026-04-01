# Report Uploader Implementation Summary

## Overview

A new CLI tool `report-uploader` has been created under the `datastore-attacher` module in the threat-scanning-architecture repository. This tool enables uploading files from local directories to S3 reporting targets.

## What Was Created

### 1. Core Modules

#### `/datastore-attacher/report_uploader/`
New Python package containing:

- **`__init__.py`**: Package initialization
- **`uploader.py`**: Core `ReportUploader` class with S3 upload functionality
- **`cli.py`**: Command-line interface and argument parsing
- **`tests/`**: Unit tests for the uploader functionality
  - `__init__.py`: Test package initialization
  - `test_uploader.py`: Comprehensive unit tests with mocked S3 operations

### 2. Documentation

- **`README.md`**: Complete documentation with:
  - Feature overview
  - Usage examples
  - Target requirements
  - Error handling
  - Troubleshooting guide
  - Kubernetes integration examples

- **`QUICK_START.md`**: Quick reference guide for common use cases

### 3. Docker Integration

Updated **`Dockerfile`** to include the new CLI:
```bash
RUN echo '#!/bin/bash\n\
python3 -m report_uploader.cli "$@"' \
> /usr/local/bin/report-uploader && chmod +x /usr/local/bin/report-uploader
```

## Architecture

### Design Decisions

1. **Reuses Existing Infrastructure**
   - Leverages `triliodata_crd_parser` for target CR parsing
   - Uses existing logger from `mount_utility`
   - Follows same patterns as `prescan` CLI

2. **Separation of Concerns**
   - `uploader.py`: Core business logic (S3 operations)
   - `cli.py`: CLI interface, validation, error handling
   - Clean separation enables easy testing and maintenance

3. **Boto3 S3 Client**
   - Initializes boto3 client using credentials from Target CR
   - Supports custom endpoints (S3-compatible storage)
   - Handles SSL verification settings
   - Uses S3v4 signature version for compatibility

### Key Features

✅ **Target Validation**
- Verifies target is a reporting target (not backup)
- Validates target is object store (S3)
- Extracts credentials from Target CR

✅ **S3 Operations**
- Initializes boto3 S3 client with proper configuration
- Verifies bucket access before uploading
- Recursive directory upload with structure preservation
- Detailed logging for each operation

✅ **Error Handling**
- Returns non-zero exit code on failure
- Continues uploading remaining files if one fails
- Comprehensive error messages with troubleshooting hints
- Full stack traces in logs for debugging

✅ **Directory Structure Preservation**
```
Local:  /data/reports/subdir/file.txt
Prefix: monthly/2026-03

Result: s3://bucket/monthly/2026-03/subdir/file.txt
```

## Usage

### Command Line

```bash
report-uploader --target-name <reporting-target-name> \
                --upload-directory <directory-path> \
                --object-prefix <s3-object-prefix>
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--target-name` | ✅ Yes | Name of reporting Target CR |
| `--upload-directory` | ✅ Yes | Local directory with files to upload |
| `--object-prefix` | ✅ Yes | S3 prefix for uploaded files |

### Exit Codes

- `0`: Success - all files uploaded
- `1`: Failure - validation errors or upload failures

## Technical Implementation

### Credentials Flow

```
Target CR (reporting type)
    ↓
triliodata_crd_parser.get_ds_from_target_crds()
    ↓
triliodata_crd_parser.parse_cr_response()
    ↓
Extract metaData: {
    accessKeyID: "...",
    accessKey: "...",
    s3Bucket: "...",
    regionName: "...",
    s3EndpointUrl: "...",
    skipCertVerification: false
}
    ↓
Initialize boto3 S3 client
    ↓
Upload files to S3
```

### Upload Process

1. **Validate** upload directory exists
2. **Fetch** Target CR from Kubernetes API
3. **Validate** target type is `reporting`
4. **Validate** storage type is `ObjectStore`
5. **Extract** S3 credentials from Target CR
6. **Initialize** boto3 S3 client
7. **Verify** bucket access (list_objects_v2)
8. **Scan** directory recursively for files
9. **Upload** each file with preserved structure
10. **Report** summary (success/failure counts)

### S3 Client Configuration

```python
s3_config = Config(
    region_name=metadata.get('regionName', ''),
    signature_version='s3v4',
    max_pool_connections=100
)

s3_client = boto3.client(
    's3',
    endpoint_url=metadata.get('s3EndpointUrl'),
    aws_access_key_id=metadata.get('accessKeyID'),
    aws_secret_access_key=metadata.get('accessKey'),
    config=s3_config,
    verify=not metadata.get('skipCertVerification', False)
)
```

## Testing

### Unit Tests

Created comprehensive unit tests in `test_uploader.py`:

- ✅ S3 client initialization with correct parameters
- ✅ Bucket name extraction from target
- ✅ Successful file uploads with structure preservation
- ✅ Empty directory handling
- ✅ Non-existent directory error handling
- ✅ Invalid path error handling
- ✅ Partial upload failure handling
- ✅ Bucket access verification (success/failure)
- ✅ Object prefix normalization (trailing slash handling)

### Running Tests

```bash
cd datastore-attacher
python3 -m pytest report_uploader/tests/ -v
```

## Integration

### Kubernetes Job Example

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: upload-dashboard-reports
spec:
  template:
    spec:
      containers:
      - name: uploader
        image: threat-scanning-datastore-attacher:latest
        command: [report-uploader]
        args:
          - --target-name=reporting-prod
          - --upload-directory=/data/reports
          - --object-prefix=dashboard-reports/2026-03-26
        volumeMounts:
        - name: reports
          mountPath: /data/reports
      volumes:
      - name: reports
        emptyDir: {}
      restartPolicy: OnFailure
```

### CronJob Example

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-report-upload
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: uploader
            image: threat-scanning-datastore-attacher:latest
            command: [report-uploader]
            args:
              - --target-name=reporting-s3
              - --upload-directory=/data/daily-reports
              - --object-prefix=daily-reports/$(date +%Y-%m-%d)
          restartPolicy: OnFailure
```

## Target Requirements

### Required Target Configuration

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-prod
  annotations:
    trilio.io/reporting-target: "true"  # Required annotation
spec:
  type: ObjectStore       # REQUIRED: must be ObjectStore (S3)
  vendor: AWS
  objectStoreCredentials:
    credentialSecret:
      name: s3-credentials
      namespace: default
    bucketName: my-reports-bucket
    region: us-west-2     # Optional
```

### Validation Checks

The CLI performs these validations:

1. ✅ Upload directory exists and is a directory
2. ✅ Target CR exists
3. ✅ Target has annotation `trilio.io/reporting-target: "true"`
4. ✅ Target has `spec.type: ObjectStore` (not NFS)
5. ✅ Target has required credentials (accessKeyID, accessKey, s3Bucket)
6. ✅ S3 bucket is accessible (can list objects)

## Dependencies

### Existing Dependencies (Already in requirements.txt)

- `boto3>=1.34.0`: AWS SDK for S3 operations
- `botocore>=1.34.0`: Core boto3 functionality
- `kubernetes>=28.1.0`: Kubernetes API client

### Reused Modules

- `mount_utility.mount_by_target_crd.triliodata_crd_parser`: Target CR parsing
- `mount_utility.logger`: Logging infrastructure
- `mount_utility.constants`: Constants and configuration
- `shared.k8s.client`: Kubernetes operations (via parser)

No new dependencies required!

## Error Handling

### Validation Errors

```python
# Directory not found
ValueError: Upload directory does not exist: /tmp/reports

# Not a directory
ValueError: Upload path is not a directory: /tmp/file.txt

# Target not found
RuntimeError: Target my-target not found

# Wrong target type
ValueError: Target my-target is not a reporting target.
Expected annotation 'trilio.io/reporting-target=true', found 'trilio.io/reporting-target=(not set)'

# Wrong storage type
ValueError: Target my-target is not an object store target.
Found type='NFS', expected 'objectstore'.
```

### Upload Errors

```python
# Bucket access failure
RuntimeError: Failed to access S3 bucket: my-bucket

# Partial upload failure
RuntimeError: File upload failed - see errors above
# Logs will show which files failed and why
```

## Logging Example

```
==============================================================
Report Uploader - Starting
==============================================================
Target: reporting-prod
Upload directory: /tmp/reports
Object prefix: reports/2026-03

✓ Validated upload directory exists
Fetching target CR: reporting-prod
✓ Retrieved target CR
Validating target type...
✓ Verified target reporting-prod is a reporting target
Validating storage type...
✓ Verified target reporting-prod is an object store
Extracting credentials from target...
✓ Extracted credentials (bucket: my-reports-bucket)
Initializing S3 uploader...
✓ S3 client initialized successfully
Verifying S3 bucket access...
✓ Verified access to bucket: my-reports-bucket

Starting file upload...
------------------------------------------------------------
Found 3 file(s) to upload
Uploading: report1.json → s3://my-reports-bucket/reports/2026-03/report1.json
✓ Uploaded successfully
Uploading: report2.csv → s3://my-reports-bucket/reports/2026-03/report2.csv
✓ Uploaded successfully
Uploading: data/summary.txt → s3://my-reports-bucket/reports/2026-03/data/summary.txt
✓ Uploaded successfully
Upload summary: 3/3 files uploaded successfully
------------------------------------------------------------

==============================================================
✓ Report upload completed successfully
==============================================================
```

## Files Changed/Created

### New Files
```
datastore-attacher/
├── report_uploader/
│   ├── __init__.py
│   ├── cli.py                 (CLI entry point)
│   ├── uploader.py            (Core S3 upload logic)
│   ├── README.md              (Complete documentation)
│   ├── QUICK_START.md         (Quick reference)
│   └── tests/
│       ├── __init__.py
│       └── test_uploader.py   (Unit tests)
```

### Modified Files
```
datastore-attacher/
└── Dockerfile                  (Added report-uploader CLI entry point)
```

## Next Steps

### Recommended Testing

1. **Unit Tests**: Run pytest on the test suite
   ```bash
   cd datastore-attacher
   python3 -m pytest report_uploader/tests/ -v
   ```

2. **Integration Test**: Create a reporting target and test upload
   ```bash
   # Create test files
   mkdir -p /tmp/test-reports
   echo "test data" > /tmp/test-reports/test.txt
   
   # Run uploader
   report-uploader --target-name test-reporting \
                   --upload-directory /tmp/test-reports \
                   --object-prefix test-uploads
   
   # Verify in S3
   aws s3 ls s3://bucket-name/test-uploads/
   ```

3. **Kubernetes Test**: Deploy as a Job and verify logs

### Potential Enhancements

Future improvements could include:

1. **Progress Reporting**: Add progress bars for large uploads
2. **Parallel Uploads**: Use threading for faster uploads
3. **Resume Support**: Skip already-uploaded files
4. **Checksums**: Verify uploaded file integrity
5. **Compression**: Optional gzip compression before upload
6. **Filtering**: Include/exclude patterns for files
7. **Dry Run Mode**: Show what would be uploaded without uploading
8. **Metrics**: Export upload metrics (count, size, duration)

## Conclusion

The `report-uploader` CLI tool is fully implemented and ready for use. It:

✅ Validates reporting targets
✅ Extracts S3 credentials from Target CRs
✅ Initializes boto3 S3 clients
✅ Uploads files recursively with structure preservation
✅ Returns proper exit codes
✅ Provides comprehensive logging
✅ Includes unit tests
✅ Has complete documentation

The implementation follows existing patterns in the codebase, reuses infrastructure, and integrates seamlessly with the Docker image build process.
