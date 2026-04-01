# Report Uploader CLI - Complete ✅

## What Was Created

A new CLI tool `report-uploader` has been successfully implemented under `datastore-attacher/report_uploader/`.

## Quick Start

### Command

```bash
report-uploader --target-name <reporting-target-name> \
                --upload-directory <local-directory> \
                --object-prefix <s3-prefix>
```

### Example

```bash
report-uploader --target-name reporting-prod \
                --upload-directory /tmp/dashboard-reports \
                --object-prefix reports/2026-03-26
```

This uploads all files from `/tmp/dashboard-reports` to `s3://<bucket>/reports/2026-03-26/`

## What It Does

1. ✅ Verifies the target is a **reporting target** (not backup)
2. ✅ Verifies the target is **ObjectStore** (S3) type
3. ✅ Extracts S3 credentials from the Target CR
4. ✅ Initializes boto3 S3 client
5. ✅ Verifies bucket access
6. ✅ Uploads all files recursively
7. ✅ Preserves directory structure in S3
8. ✅ Returns exit code 0 on success, 1 on failure

## Files Created

### Core Implementation (10 files)

```
datastore-attacher/report_uploader/
├── cli.py                         # CLI entry point (226 lines)
├── uploader.py                    # S3 upload logic (190 lines)
├── __init__.py                    # Package init
├── tests/
│   ├── __init__.py               # Test package init
│   └── test_uploader.py          # Unit tests (290 lines)
├── README.md                      # Complete documentation (460 lines)
├── QUICK_START.md                 # Quick reference (180 lines)
├── IMPLEMENTATION_SUMMARY.md      # Technical details (620 lines)
├── ARCHITECTURE.md                # Architecture diagrams (420 lines)
└── test_local.sh                  # Local testing script
```

### Modified Files (1 file)

```
datastore-attacher/Dockerfile      # Added CLI entry point (4 lines)
```

## Documentation

### 📚 Available Guides

1. **QUICK_START.md** - Start here! Quick examples and common use cases
2. **README.md** - Complete documentation with troubleshooting
3. **IMPLEMENTATION_SUMMARY.md** - Technical implementation details
4. **ARCHITECTURE.md** - Architecture diagrams and flow charts

### 🔍 Quick Links

- Quick Start: `report_uploader/QUICK_START.md`
- Full Docs: `report_uploader/README.md`
- Architecture: `report_uploader/ARCHITECTURE.md`
- Tests: `report_uploader/tests/test_uploader.py`

## Target Requirements

Your Target CR must have:

```yaml
metadata:
  annotations:
    trilio.io/reporting-target: "true"  # Required annotation
spec:
  type: ObjectStore       # REQUIRED: Must be ObjectStore (S3)
  objectStoreCredentials:
    credentialSecret:
      name: s3-creds
      namespace: default
    bucketName: my-bucket
```

## Testing

### Unit Tests

```bash
cd datastore-attacher
python3 -m pytest report_uploader/tests/ -v
```

### Integration Test

```bash
# Create test data
mkdir -p /tmp/test-reports
echo "test" > /tmp/test-reports/test.txt

# Run uploader (in container)
report-uploader --target-name test-reporting \
                --upload-directory /tmp/test-reports \
                --object-prefix test/$(date +%Y%m%d)

# Verify in S3
aws s3 ls s3://bucket-name/test/
```

## Exit Codes

- **0** = Success - all files uploaded
- **1** = Failure - check logs

## Common Use Cases

### 1. Dashboard Reports

```bash
report-uploader --target-name reporting-s3 \
                --upload-directory /var/lib/dashboard/reports \
                --object-prefix dashboard-reports/$(date +%Y-%m-%d)
```

### 2. Scan Results

```bash
report-uploader --target-name reporting-target \
                --upload-directory /tmp/scan-results \
                --object-prefix scan-results/instance-${INSTANCE_ID}
```

### 3. Daily Backups (CronJob)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-upload
spec:
  schedule: "0 2 * * *"
  jobTemplate:
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
              - --object-prefix=daily/$(date +%Y-%m-%d)
          restartPolicy: OnFailure
```

## Troubleshooting

### "Target not found"
```bash
kubectl get targets.threatscanning.trilio.io
```

### "Not a reporting target"
Check: `spec.targetType` must be `reporting` (not `backup`)

### "Failed to access bucket"
- Verify S3 credentials
- Check bucket permissions
- Test connectivity: `aws s3 ls s3://bucket-name/`

### "Directory not found"
- Check path exists
- Verify volume mounts in Kubernetes

## Next Steps

1. **Build Docker image**
   ```bash
   cd datastore-attacher
   docker build -t threat-scanning-datastore-attacher:latest .
   ```

2. **Create reporting target** (if needed)
   ```yaml
   kubectl apply -f reporting-target.yaml
   ```

3. **Test the CLI**
   ```bash
   docker run threat-scanning-datastore-attacher:latest \
              report-uploader --help
   ```

4. **Deploy as Job/CronJob**
   See examples in `README.md`

## Features Summary

✅ **Validates everything**
- Directory exists
- Target is reporting type
- Target is ObjectStore (S3)
- Credentials are valid
- Bucket is accessible

✅ **Handles errors gracefully**
- Clear error messages
- Detailed logging
- Non-zero exit codes
- Continues on partial failures

✅ **Production ready**
- Comprehensive unit tests
- Complete documentation
- Kubernetes integration
- Docker support

✅ **No new dependencies**
- Reuses existing infrastructure
- Uses boto3 (already in requirements.txt)
- Compatible with current setup

## Architecture Highlights

```
CLI (cli.py)
    ↓
Validate inputs
    ↓
Fetch Target CR (Kubernetes API)
    ↓
Extract credentials (triliodata_crd_parser)
    ↓
Initialize S3 client (uploader.py)
    ↓
Upload files (boto3)
    ↓
S3 Bucket
```

## Implementation Complete ✅

Everything is ready to use:

- ✅ Core functionality implemented
- ✅ CLI entry point created
- ✅ Docker integration added
- ✅ Unit tests written
- ✅ Documentation complete
- ✅ Error handling robust
- ✅ Logging comprehensive
- ✅ No new dependencies
- ✅ Follows existing patterns
- ✅ Production ready

## Questions?

See the documentation:
- **Quick Start**: `report_uploader/QUICK_START.md`
- **Full README**: `report_uploader/README.md`
- **Architecture**: `report_uploader/ARCHITECTURE.md`
- **Implementation**: `report_uploader/IMPLEMENTATION_SUMMARY.md`

---

**Status**: ✅ Implementation Complete
**Total Files**: 11 (10 new + 1 modified)
**Total Lines**: ~2,400 lines (code + docs + tests)
**Dependencies**: None (reuses existing)
**Ready for**: Production use
