# Report Upload Integration - Implementation Complete

## ✅ Changes Successfully Implemented

The scan job now automatically uploads reports to the reporting target after successful scan completion.

---

## What Was Implemented

### 1. Report Upload Command Integration

The scan job command now includes report upload:

**Before:**
```bash
scan_engine --production
```

**After:**
```bash
scan_engine --production && report_uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix <instance-id>/<target-uid>/<plan-uid>/<backup-uid>/<timestamp> \
  --target-name <reporting-target-name>
```

### 2. Reporting Target Discovery

Added automatic discovery of cluster-wide reporting target:
- Searches for Target CR with annotation `trilio.io/reporting-target: "true"`
- Validates exactly one reporting target exists
- Returns error if none or multiple found

### 3. Structured S3 Path Generation

Reports uploaded to structured path:
```
reports/
  └── <instance-id>/
      └── <backup-target-uid>/
          └── <backupplan-uid>/
              └── <backup-uid>/
                  └── <timestamp>/
                      └── [report files]
```

Path built from ScanInstance labels and creation timestamp.

---

## Files Modified

### `pkg/helpers/job_helper.go`

**Modified Function:**
- `GetScanJob()` - Added reporting target lookup and command construction

**New Functions:**
- `getReportingTargetName()` - Find cluster-wide reporting target
- `buildReportUploadCommand()` - Build report uploader CLI command

**Changes:**
```diff
+ // Find reporting target
+ reportingTargetName, err := getReportingTargetName(ctx, cl)

+ // Build report upload command
+ reportUploadCmd := buildReportUploadCommand(scanInstance, reportingTargetName)
+ fullScanCmd := fmt.Sprintf("%s && %s", scanEngineCmd, reportUploadCmd)

- scanCmd = scanEngineCmd
+ scanCmd = fullScanCmd  // or with mount: mountCmd && fullScanCmd
```

---

## Key Features

### ✅ Upload Only on Scan Success
- Uses `&&` operator to chain commands
- Upload only executes if scan succeeds (exit code 0)
- If scan fails, upload is skipped
- Maintains proper job failure status

### ✅ API-Only Access
- Report uploader uses S3 API directly
- No datastore mounting required for upload
- Uses reporting target credentials
- Works with all S3-compatible storage

### ✅ Cluster-Wide Reporting Target
- Single reporting target per cluster
- Identified by annotation
- Controller validates exactly one exists
- Simplifies configuration management

### ✅ Structured Storage
- Hierarchical path organization
- Easy querying by any level
- Timestamp-based versioning
- Dashboard-friendly structure

---

## Configuration Requirements

### 1. Create Reporting Target

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"  # REQUIRED
spec:
  type: ObjectStore
  vendor: AWS  # or MinIO, etc.
  objectStoreCredentials:
    url: "https://s3.amazonaws.com"
    bucketName: "threat-scan-reports"
    region: "us-east-1"
    credentialSecret:
      name: reporting-credentials
```

### 2. Create Credentials Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: reporting-credentials
  namespace: threat-scanning-system
type: Opaque
stringData:
  accessKey: "<access-key>"
  secretKey: "<secret-key>"
```

### 3. Validation Rules

The controller enforces:
- ✅ Exactly ONE reporting target with annotation
- ✅ Reporting target must be Available
- ✅ ScanInstance must have all required labels

---

## Error Handling

### No Reporting Target Found

**Error Message:**
```
failed to get reporting target: no reporting target found (target with annotation trilio.io/reporting-target=true)
```

**Resolution:**
1. Create Target CR with the annotation
2. Wait for target to become Available
3. Retry ScanInstance creation

### Multiple Reporting Targets Found

**Error Message:**
```
failed to get reporting target: multiple reporting targets found: [target1, target2] (expected exactly one)
```

**Resolution:**
1. Remove annotation from all but one target
2. Retry ScanInstance creation

### Upload Failure

**Behavior:** Job fails with exit code != 0

**Common Causes:**
- Invalid credentials
- Insufficient S3 permissions
- Network connectivity issues
- Bucket doesn't exist

**Debugging:**
```bash
kubectl logs <scan-job-pod> -n threat-scanning-system | tail -50
# Look for upload-related errors
```

---

## Testing

### 1. Verify Reporting Target

```bash
# Check annotation
kubectl get target reporting-target -o yaml | grep -A 2 "annotations:"

# Verify status
kubectl get target reporting-target -o jsonpath='{.status.status}'
# Should output: Available
```

### 2. Create Test ScanInstance

```bash
kubectl apply -f scaninstance-sample.yaml
```

### 3. Verify Job Command

```bash
JOB_NAME=$(kubectl get job -n threat-scanning-system -l trilio.io/scaninstance-name=<name> -o jsonpath='{.items[0].metadata.name}')

kubectl get job $JOB_NAME -n threat-scanning-system -o jsonpath='{.spec.template.spec.containers[0].args[0]}' | grep "report_uploader"

# Should see:
# ... && /usr/local/bin/report-uploader ...
```

### 4. Monitor Upload

```bash
POD_NAME=$(kubectl get pod -l job-name=$JOB_NAME -n threat-scanning-system -o jsonpath='{.items[0].metadata.name}')

kubectl logs -f $POD_NAME -n threat-scanning-system

# Look for:
# - "Scan completed successfully"
# - "Uploading reports to..."
# - "Upload complete"
```

### 5. Verify in S3

```bash
aws s3 ls s3://threat-scan-reports/reports/ --recursive | grep "$(date +%Y-%m-%d)"

# Should see reports with today's date in path
```

---

## Build Status

All packages compile successfully:

```bash
✅ go build -o /dev/null ./pkg/helpers/...
   Exit code: 0

✅ go build -o /dev/null ./controllers/scaninstance/...
   Exit code: 0
```

No compilation errors detected.

---

## Documentation Created

1. **REPORT_UPLOAD_INTEGRATION.md** - Full implementation guide
2. **REPORT_UPLOAD_QUICK_REF.md** - Quick reference
3. **REPORT_UPLOAD_IMPLEMENTATION_COMPLETE.md** - This summary

---

## Comparison: Before vs After

### Before Implementation

```bash
# Scan job only ran scanning
python3 /app/main.py multi-vm config.json artifacts.json --production

# Reports stayed in container, lost when pod deleted
```

### After Implementation

```bash
# Scan job runs scanning AND uploads reports
python3 /app/main.py multi-vm config.json artifacts.json --production && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix instance-abc/target-def/plan-ghi/backup-jkl/2026-03-26T14-30-45 \
  --target-name reporting-target

# Reports persist in S3, accessible to dashboard
```

---

## Benefits

1. **Automated Upload**: No manual intervention needed
2. **Structured Storage**: Easy to query and organize
3. **Persistent Reports**: Survives pod deletion
4. **Dashboard Ready**: Direct S3 access for dashboard
5. **Version Control**: Timestamp-based report versioning
6. **Fail-Safe**: Upload only on scan success

---

## Next Steps

### For Deployment

1. **Update Controller**
   ```bash
   # Build and push new controller image
   make docker-build docker-push
   
   # Update deployment
   kubectl rollout restart deployment/threat-scanning-controller -n threat-scanning-system
   ```

2. **Create Reporting Target**
   ```bash
   kubectl apply -f reporting-target.yaml
   
   # Verify
   kubectl get target reporting-target
   ```

3. **Test with Sample ScanInstance**
   ```bash
   kubectl apply -f scaninstance-sample.yaml
   
   # Monitor
   kubectl get scaninstance -w
   ```

4. **Verify Reports in S3**
   ```bash
   aws s3 ls s3://threat-scan-reports/reports/ --recursive
   ```

### For Dashboard Integration

1. Configure dashboard to read from S3 bucket
2. Use path structure to query reports
3. Implement report parsing and visualization
4. Set up monitoring/alerts for new reports

---

## Additional Considerations

### S3 Permissions Required

The reporting target credentials need:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::threat-scan-reports",
        "arn:aws:s3:::threat-scan-reports/*"
      ]
    }
  ]
}
```

### Monitoring Recommendations

1. Track upload success/failure rates
2. Monitor S3 bucket size and growth
3. Alert on upload failures
4. Track upload duration for performance

### Future Enhancements

1. Retry logic for failed uploads
2. Compression before upload
3. Streaming for large reports
4. Report retention/cleanup policy
5. Multi-region reporting targets

---

## Summary

**Status:** ✅ **IMPLEMENTATION COMPLETE**

All requested features successfully implemented:
- ✅ Report uploader integrated into scan job command
- ✅ Cluster-wide reporting target discovery
- ✅ Structured S3 path generation from ScanInstance labels
- ✅ Upload only on scan success (via `&&` operator)
- ✅ API-only access (no datastore mount needed)
- ✅ Error handling and validation
- ✅ All code compiles successfully
- ✅ Comprehensive documentation created

**Ready for:** Testing, deployment, and dashboard integration

---

_Generated: 2026-03-26_
_Project: threat-scanning-architecture_
_Feature: Report Upload Integration_
_Implementation: Complete_
