# Report Uploader Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     report-uploader CLI                         │
│                                                                 │
│  Usage:                                                         │
│  report-uploader --target-name <name>                          │
│                  --upload-directory <path>                      │
│                  --object-prefix <prefix>                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Validation Phase                             │
│                                                                 │
│  1. Upload directory exists?                                    │
│  2. Target CR exists?                                           │
│  3. Target type = "reporting"?                                  │
│  4. Storage type = "ObjectStore"?                               │
│  5. Has S3 credentials?                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Credential Extraction Flow                         │
│                                                                 │
│  Target CR (Kubernetes)                                         │
│       │                                                         │
│       ▼                                                         │
│  triliodata_crd_parser.get_ds_from_target_crds()               │
│       │                                                         │
│       ▼                                                         │
│  triliodata_crd_parser.parse_cr_response()                     │
│       │                                                         │
│       ▼                                                         │
│  Extract metaData:                                              │
│    - accessKeyID                                                │
│    - accessKey                                                  │
│    - s3Bucket                                                   │
│    - regionName                                                 │
│    - s3EndpointUrl                                              │
│    - skipCertVerification                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                S3 Client Initialization                         │
│                                                                 │
│  boto3.client('s3',                                             │
│      endpoint_url=s3EndpointUrl,                                │
│      aws_access_key_id=accessKeyID,                             │
│      aws_secret_access_key=accessKey,                           │
│      config=Config(                                             │
│          region_name=regionName,                                │
│          signature_version='s3v4',                              │
│          max_pool_connections=100                               │
│      ),                                                         │
│      verify=not skipCertVerification                            │
│  )                                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Bucket Access Verification                         │
│                                                                 │
│  s3_client.list_objects_v2(                                     │
│      Bucket=bucket_name,                                        │
│      MaxKeys=1                                                  │
│  )                                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   File Upload Process                           │
│                                                                 │
│  1. Scan directory recursively                                  │
│  2. For each file:                                              │
│     - Calculate relative path                                   │
│     - Construct S3 key: prefix/relative/path                    │
│     - Upload file to S3                                         │
│     - Log success/failure                                       │
│  3. Report summary                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      S3 Bucket                                  │
│                                                                 │
│  s3://bucket-name/                                              │
│    └── object-prefix/                                           │
│        ├── file1.txt                                            │
│        ├── file2.json                                           │
│        └── subdir/                                              │
│            └── file3.csv                                        │
└─────────────────────────────────────────────────────────────────┘
```

## Component Interaction

```
┌────────────────┐
│  Kubernetes    │
│  Target CR     │
└───────┬────────┘
        │
        │ read
        ▼
┌────────────────┐       ┌──────────────────┐
│ triliodata_    │       │  ReportUploader  │
│ crd_parser     │──────▶│  uploader.py     │
│ (existing)     │       │  (new)           │
└────────────────┘       └────────┬─────────┘
                                  │
                                  │ uses
                                  ▼
                         ┌──────────────────┐
                         │  boto3 S3 Client │
                         └────────┬─────────┘
                                  │
                                  │ upload
                                  ▼
                         ┌──────────────────┐
                         │   S3 Bucket      │
                         └──────────────────┘
```

## Module Structure

```
datastore-attacher/
│
├── report_uploader/              # New module
│   ├── __init__.py               # Package init
│   ├── cli.py                    # CLI entry point
│   │   ├── parse arguments
│   │   ├── validate inputs
│   │   ├── fetch Target CR
│   │   ├── verify target type
│   │   └── call uploader
│   │
│   ├── uploader.py               # Core logic
│   │   ├── ReportUploader class
│   │   ├── _initialize_s3_client()
│   │   ├── verify_bucket_access()
│   │   └── upload_files()
│   │
│   ├── tests/                    # Unit tests
│   │   ├── __init__.py
│   │   └── test_uploader.py
│   │
│   └── README.md                 # Documentation
│
├── mount_utility/                # Existing (reused)
│   ├── constants.py              # Constants
│   ├── logger.py                 # Logging
│   └── mount_by_target_crd/
│       └── triliodata_crd_parser.py  # Target parsing
│
└── Dockerfile                    # Modified (added CLI)
```

## Data Flow

```
Input:
  --target-name: reporting-prod
  --upload-directory: /tmp/reports
  --object-prefix: reports/2026-03

Local Files:
  /tmp/reports/
    ├── summary.json
    ├── data.csv
    └── charts/
        └── graph.png

Target CR:
  spec:
    targetType: reporting
    type: ObjectStore
    objectStoreCredentials:
      credentialSecret:
        name: s3-creds
      bucketName: my-bucket

S3 Result:
  s3://my-bucket/
    └── reports/2026-03/
        ├── summary.json
        ├── data.csv
        └── charts/
            └── graph.png
```

## Error Handling Flow

```
┌─────────────────┐
│  Validation     │
│  Errors         │
└────────┬────────┘
         │
         ├─ Directory not found ──┐
         ├─ Target not found ─────┤
         ├─ Wrong target type ────┤
         └─ Not ObjectStore ───────┤
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  Log error       │
                         │  Exit code 1     │
                         └──────────────────┘

┌─────────────────┐
│  S3 Errors      │
└────────┬────────┘
         │
         ├─ Bucket access denied ─┐
         ├─ Network error ─────────┤
         └─ Upload failed ─────────┤
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  Log error       │
                         │  Continue others │
                         │  Exit code 1     │
                         └──────────────────┘
```

## Success Path

```
CLI invoked
    ↓
Validate arguments ✓
    ↓
Validate directory ✓
    ↓
Fetch Target CR ✓
    ↓
Verify reporting target ✓
    ↓
Verify ObjectStore ✓
    ↓
Extract credentials ✓
    ↓
Initialize S3 client ✓
    ↓
Verify bucket access ✓
    ↓
Scan files (3 found)
    ↓
Upload file 1 ✓
    ↓
Upload file 2 ✓
    ↓
Upload file 3 ✓
    ↓
Log summary: 3/3 ✓
    ↓
Exit code 0
```

## Integration Points

### Kubernetes
- Reads Target CRs via K8s API
- Uses in-cluster or kubeconfig auth
- Cluster-scoped resource access

### Existing Modules
- `mount_utility.mount_by_target_crd.triliodata_crd_parser`
  - get_ds_from_target_crds()
  - parse_cr_response()
- `mount_utility.logger`
  - logger instance
- `mount_utility.constants`
  - TVK_CRD_GROUP, TVK_CRD_VERSION
  - TARGET_TYPE_REPORTING, OBJECT_STORE

### AWS S3
- boto3 SDK
- Standard S3 API
- S3-compatible storage support

## Deployment

### Docker Image
```dockerfile
FROM python:3.12-slim

# ... existing setup ...

# Add report-uploader CLI
RUN echo '#!/bin/bash\n\
python3 -m report_uploader.cli "$@"' \
> /usr/local/bin/report-uploader && \
chmod +x /usr/local/bin/report-uploader
```

### Kubernetes Job
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
        command: [report-uploader]
        args:
          - --target-name=reporting-prod
          - --upload-directory=/data
          - --object-prefix=reports/date
```

## Logging Output

```
==================================================================
Report Uploader - Starting
==================================================================
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
------------------------------------------------------------------
Found 3 file(s) to upload
Uploading: file1.txt → s3://my-bucket/reports/2026-03/file1.txt
✓ Uploaded successfully
Uploading: file2.json → s3://my-bucket/reports/2026-03/file2.json
✓ Uploaded successfully
Uploading: subdir/file3.txt → s3://my-bucket/reports/2026-03/subdir/file3.txt
✓ Uploaded successfully
Upload summary: 3/3 files uploaded successfully
------------------------------------------------------------------

==================================================================
✓ Report upload completed successfully
==================================================================
```
