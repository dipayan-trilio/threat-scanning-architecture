# Report Uploader - Quick Start Guide

## What is it?

`report-uploader` is a CLI tool that uploads files from a local directory to S3 reporting targets. It's designed for uploading scan results, dashboard reports, or any other files to S3.

## Quick Example

```bash
# Basic usage
report-uploader --target-name my-reporting-target \
                --upload-directory /tmp/reports \
                --object-prefix reports/2026-03-26

# This uploads all files from /tmp/reports to:
# s3://<bucket>/reports/2026-03-26/file1.json
# s3://<bucket>/reports/2026-03-26/file2.csv
# etc.
```

## Prerequisites

1. **Reporting Target**: You need a Target CR with:
   - Annotation: `trilio.io/reporting-target: "true"`
   - `spec.type: ObjectStore` (S3)
   - Valid S3 credentials configured

2. **Files to Upload**: A local directory containing the files

## Usage

```bash
report-uploader --target-name <target-name> \
                --upload-directory <local-dir> \
                --object-prefix <s3-prefix>
```

### Arguments

| Argument | Required | Description | Example |
|----------|----------|-------------|---------|
| `--target-name` | ✅ Yes | Name of reporting Target CR | `reporting-prod` |
| `--upload-directory` | ✅ Yes | Local directory with files | `/data/reports` |
| `--object-prefix` | ✅ Yes | S3 prefix for uploaded files | `scan-results/2026-03` |

## Common Use Cases

### 1. Upload Dashboard Reports

```bash
report-uploader --target-name reporting-s3 \
                --upload-directory /var/lib/dashboard/reports \
                --object-prefix dashboard-reports/$(date +%Y-%m-%d)
```

### 2. Upload Scan Results

```bash
report-uploader --target-name reporting-target \
                --upload-directory /tmp/scan-results \
                --object-prefix scan-results/instance-${INSTANCE_ID}
```

### 3. Upload with Nested Structure

```bash
# Local: /data/reports/subdir/file.txt
# Uploads to: s3://<bucket>/monthly/2026-03/subdir/file.txt

report-uploader --target-name reporting-s3 \
                --upload-directory /data/reports \
                --object-prefix monthly/2026-03
```

## Exit Codes

- **0**: Success - all files uploaded
- **1**: Failure - check logs for details

## Troubleshooting

### "Target not found"
```bash
# Check target exists
kubectl get targets.threatscanning.trilio.io
```

### "Target is not a reporting target"
```bash
# Verify target has correct annotation
kubectl get target <name> -o yaml | grep -A 2 annotations
# Should show: trilio.io/reporting-target: "true"
```

### "Failed to access bucket"
```bash
# Check credentials
kubectl get secret <secret-name> -o yaml

# Test bucket access
aws s3 ls s3://<bucket-name>/
```

### "Upload directory does not exist"
```bash
# Check directory
ls -la <upload-directory>
```

## Example Target CR

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-prod
  annotations:
    trilio.io/reporting-target: "true"  # Required for reporting target
spec:
  type: ObjectStore      # Must be ObjectStore
  vendor: AWS
  objectStoreCredentials:
    credentialSecret:
      name: s3-credentials
      namespace: default
    bucketName: my-reports-bucket
    region: us-west-2
```

## Using in Kubernetes Jobs

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
        args:
          - --target-name=reporting-prod
          - --upload-directory=/data/reports
          - --object-prefix=reports/2026-03-26
        volumeMounts:
        - name: reports
          mountPath: /data/reports
      volumes:
      - name: reports
        hostPath:
          path: /var/lib/reports
      restartPolicy: OnFailure
```

## Logging

The tool provides detailed logs:

```
==============================================================
Report Uploader - Starting
==============================================================
Target: reporting-prod
Upload directory: /tmp/reports
Object prefix: reports/2026-03

✓ Validated upload directory exists
✓ Retrieved target CR
✓ Verified target reporting-prod is a reporting target
✓ Verified target reporting-prod is an object store
✓ Extracted credentials (bucket: my-bucket)
✓ S3 client initialized successfully
✓ Verified access to bucket: my-bucket

Starting file upload...
------------------------------------------------------------
Found 3 file(s) to upload
Uploading: file1.txt → s3://my-bucket/reports/2026-03/file1.txt
✓ Uploaded successfully
Uploading: file2.json → s3://my-bucket/reports/2026-03/file2.json
✓ Uploaded successfully
Uploading: subdir/file3.txt → s3://my-bucket/reports/2026-03/subdir/file3.txt
✓ Uploaded successfully
Upload summary: 3/3 files uploaded successfully
------------------------------------------------------------

==============================================================
✓ Report upload completed successfully
==============================================================
```

## See Also

- [Full README](README.md) - Complete documentation
- [Prescan CLI](../prescan/README.md) - Backup validation tool
- [Target Poller](../targetPoller/README.md) - Backup discovery service
