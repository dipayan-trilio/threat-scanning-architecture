# Report Uploader

CLI tool for uploading files from local directories to S3 reporting targets.

## Overview

The `report-uploader` tool enables uploading files (such as scan reports, dashboard data, or analysis results) to S3 buckets associated with reporting targets. It validates that the target is a reporting target, extracts S3 credentials from the Target CR, and uploads all files from the specified directory.

## Features

- ✅ Validates target is a reporting target (not a backup target)
- ✅ Validates target is an object store (S3) target
- ✅ Extracts S3 credentials from Target CR using existing datastore-attacher functionality
- ✅ Initializes boto3 S3 client with proper configuration
- ✅ Verifies S3 bucket access before uploading
- ✅ Recursively uploads all files from specified directory
- ✅ Maintains directory structure in S3 under object prefix
- ✅ Returns non-zero exit code on failure
- ✅ Detailed logging for troubleshooting

## Usage

### Command Line Arguments

```bash
report-uploader --target-name <name> \
                --upload-directory <path> \
                --object-prefix <prefix>
```

#### Required Arguments

| Argument | Description |
|----------|-------------|
| `--target-name` | Name of the reporting Target CR (cluster-scoped) |
| `--upload-directory` | Local directory containing files to upload |
| `--object-prefix` | S3 object prefix where files will be uploaded |

### Examples

#### Upload Dashboard Reports

```bash
report-uploader --target-name reporting-prod \
                --upload-directory /tmp/dashboard-reports \
                --object-prefix reports/dashboard/2026-03
```

This will upload all files from `/tmp/dashboard-reports` to:
- `s3://<bucket>/reports/dashboard/2026-03/file1.json`
- `s3://<bucket>/reports/dashboard/2026-03/file2.csv`
- etc.

#### Upload Scan Results

```bash
report-uploader --target-name reporting-s3 \
                --upload-directory /opt/scan-results \
                --object-prefix scan-results/instance-abc123
```

#### Upload with Nested Directory Structure

```bash
# Local structure:
# /data/reports/
#   ├── summary.json
#   ├── details/
#   │   ├── report1.json
#   │   └── report2.json
#   └── charts/
#       └── graph.png

report-uploader --target-name reporting-target \
                --upload-directory /data/reports \
                --object-prefix monthly-reports/2026-03

# Results in S3:
# s3://<bucket>/monthly-reports/2026-03/summary.json
# s3://<bucket>/monthly-reports/2026-03/details/report1.json
# s3://<bucket>/monthly-reports/2026-03/details/report2.json
# s3://<bucket>/monthly-reports/2026-03/charts/graph.png
```

## Target Requirements

### Target Type

The target must be a **reporting target**. The Target CR must have the annotation:

```yaml
metadata:
  annotations:
    trilio.io/reporting-target: "true"  # Required annotation to mark as reporting target
spec:
  type: ObjectStore      # Must be ObjectStore (S3)
```

### Storage Type

Only **ObjectStore (S3)** targets are supported. NFS targets are not supported.

### Credentials

The target must have valid S3 credentials configured:

```yaml
metadata:
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  objectStoreCredentials:
    credentialSecret:
      name: reporting-secret
      namespace: default
    bucketName: my-reports-bucket
    region: us-west-2  # Optional
    url: https://s3.amazonaws.com  # Optional (for S3-compatible stores)
```

## Exit Codes

| Exit Code | Description |
|-----------|-------------|
| `0` | Success - all files uploaded |
| `1` | Failure - see error logs |

## Error Handling

The tool validates inputs and provides clear error messages:

### Target Not Found

```
RuntimeError: Target my-target not found
```

**Solution**: Verify the target name and ensure it exists in the cluster.

### Not a Reporting Target

```
ValueError: Target my-target is not a reporting target.
Expected annotation 'trilio.io/reporting-target=true', found 'trilio.io/reporting-target=(not set)'
```

**Solution**: Add the annotation `trilio.io/reporting-target: "true"` to your Target CR metadata.

### Not an Object Store

```
ValueError: Target my-target is not an object store target.
Found type='NFS', expected 'objectstore'.
```

**Solution**: Only S3 targets are supported for report uploading.

### Directory Not Found

```
ValueError: Upload directory does not exist: /tmp/reports
```

**Solution**: Verify the upload directory path exists and is accessible.

### S3 Access Failure

```
RuntimeError: Failed to access S3 bucket: my-bucket
```

**Solution**: Check credentials, bucket permissions, and network connectivity.

### Upload Failures

If some files fail to upload, the tool will:
1. Log each failed file
2. Continue uploading remaining files
3. Exit with code 1
4. Display summary of failures

## Implementation Details

### Architecture

The report-uploader consists of two main modules:

1. **`report_uploader/cli.py`**: Command-line interface and validation logic
2. **`report_uploader/uploader.py`**: Core upload functionality using boto3

### Dependencies

The tool reuses existing datastore-attacher functionality:

- `mount_utility.mount_by_target_crd.triliodata_crd_parser`: Target CR parsing and credential extraction
- `mount_utility.logger`: Logging infrastructure
- `mount_utility.constants`: Constants and configuration
- `boto3`: AWS SDK for S3 operations

### Credentials Flow

```
Target CR → triliodata_crd_parser.get_ds_from_target_crds()
         → triliodata_crd_parser.parse_cr_response()
         → Extract metaData (accessKeyID, accessKey, s3Bucket, etc.)
         → Initialize boto3 S3 client
         → Upload files
```

### File Upload Process

1. **Validate** upload directory exists
2. **Fetch** Target CR from Kubernetes
3. **Validate** target is reporting and object store
4. **Extract** S3 credentials from Target CR
5. **Initialize** boto3 S3 client
6. **Verify** S3 bucket access (list objects)
7. **Scan** upload directory recursively for files
8. **Upload** each file to S3 under object prefix
9. **Report** summary (success/failures)

### S3 Key Construction

Files are uploaded with keys that preserve directory structure:

```
Local: /data/reports/subdir/file.json
Prefix: monthly-reports/2026-03

S3 Key: monthly-reports/2026-03/subdir/file.json
```

## Development

### Running Tests

```bash
# Run from datastore-attacher directory
python3 -m pytest report_uploader/tests/
```

### Manual Testing

```bash
# Create test files
mkdir -p /tmp/test-upload
echo "test data" > /tmp/test-upload/test.txt

# Run uploader
python3 -m report_uploader.cli \
  --target-name test-reporting-target \
  --upload-directory /tmp/test-upload \
  --object-prefix test-uploads/$(date +%Y%m%d)

# Verify in S3
aws s3 ls s3://my-bucket/test-uploads/
```

### Adding New Features

To extend the uploader:

1. Update `report_uploader/uploader.py` for core functionality
2. Update `report_uploader/cli.py` for CLI arguments
3. Add tests in `report_uploader/tests/`
4. Update this README

## Logging

The tool uses the existing datastore-attacher logging infrastructure:

```python
from mount_utility import logger
logging = logger.logger

logging.info("Info message")
logging.warning("Warning message")
logging.error("Error message")
```

Logs include:
- Target validation steps
- Credential extraction
- S3 client initialization
- Each file upload (source → destination)
- Upload summary (success/failure counts)
- Detailed error traces

## Integration with Kubernetes

### Job Example

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: upload-reports
spec:
  template:
    spec:
      containers:
      - name: uploader
        image: threat-scanning-datastore-attacher:latest
        command:
          - report-uploader
          - --target-name
          - reporting-prod
          - --upload-directory
          - /data/reports
          - --object-prefix
          - scan-reports/2026-03-26
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
            command:
              - report-uploader
              - --target-name
              - reporting-s3
              - --upload-directory
              - /data/daily-reports
              - --object-prefix
              - daily-reports/$(date +%Y-%m-%d)
          restartPolicy: OnFailure
```

## Troubleshooting

### Problem: "Target not found"

**Check**: Target exists and is cluster-scoped
```bash
kubectl get targets.threatscanning.trilio.io
```

### Problem: "Failed to access bucket"

**Check**: Credentials and bucket permissions
```bash
# Verify secret exists
kubectl get secret reporting-secret -o yaml

# Test bucket access manually
aws s3 ls s3://my-bucket/ --endpoint-url=https://...
```

### Problem: "Permission denied" on upload directory

**Check**: Directory permissions and Pod security context
```bash
ls -la /path/to/upload-directory
```

### Problem: SSL certificate errors

**Check**: Target has skipCertVerification or SSL cert configured
```yaml
spec:
  objectStoreCredentials:
    skipCertVerification: true  # For testing only
```

## See Also

- [Prescan CLI](../prescan/README.md) - For backup validation and metadata extraction
- [Target Poller](../targetPoller/README.md) - For continuous backup discovery
- [Mount Utility](../mount_utility/README.md) - For mounting targets
