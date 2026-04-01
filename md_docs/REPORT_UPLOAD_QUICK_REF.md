# Report Upload Integration - Quick Reference

## Summary

Scan jobs now automatically upload reports to a cluster-wide reporting target after successful scan completion.

---

## Command Structure

```bash
# Final scan job command
scan_engine --production && \
soc_database_setup --dir dashboard_reports && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix <instance-id>/<target-uid>/<plan-uid>/<backup-uid>/<timestamp> \
  --target-name <reporting-target-name>
```

---

## S3 Path Structure

```
reports/
  └── <instance-id>/           # From label: trilio.io/instance-id
      └── <backup-target-uid>/ # From label: trilio.io/backup-target
          └── <backupplan-uid>/ # From label: trilio.io/backupplan
              └── <backup-uid>/ # From label: trilio.io/backup
                  └── <timestamp>/ # ScanInstance creation time (2006-01-02T15-04-05)
                      └── [report files]
```

---

## Key Implementation Points

### 1. Reporting Target
- **Single cluster-wide target**
- Identified by annotation: `trilio.io/reporting-target: "true"`
- Must be Available before scans run

### 2. Upload Behavior
- ✅ Upload **only if scan succeeds** (`&&` operator)
- ✅ Upload **failure = job failure**
- ✅ API-only access (no datastore mount)

### 3. Functions Added

**`getReportingTargetName()`** - Find cluster reporting target
```go
// Validates exactly one reporting target exists
// Returns target name or error
```

**`buildReportUploadCommand()`** - Build CLI command
```go
// Constructs path from ScanInstance labels
// Returns full report uploader command string
```

---

## Setup Checklist

- [ ] Create reporting target with annotation `trilio.io/reporting-target: "true"`
- [ ] Verify target status is Available
- [ ] Ensure only ONE reporting target exists
- [ ] Test scan job and verify reports uploaded
- [ ] Monitor S3 bucket for report files

---

## Reporting Target Example

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    url: "https://s3.amazonaws.com"
    bucketName: "threat-scan-reports"
    region: "us-east-1"
    credentialSecret:
      name: reporting-credentials
```

---

## Quick Test

```bash
# 1. Create reporting target
kubectl apply -f reporting-target.yaml

# 2. Verify
kubectl get target reporting-target -o jsonpath='{.metadata.annotations.trilio\.io/reporting-target}'
# Output: true

# 3. Create ScanInstance
kubectl apply -f scaninstance-sample.yaml

# 4. Check scan job command
kubectl get job <scan-job-name> -o yaml | grep -A 3 "args:"
# Should see: ... && /usr/local/bin/report-uploader ...

# 5. Monitor logs
kubectl logs -f <scan-job-pod> | grep -i upload

# 6. Verify in S3
aws s3 ls s3://threat-scan-reports/reports/ --recursive
```

---

## Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| `no reporting target found` | No target with annotation | Add annotation to target |
| `multiple reporting targets found` | Multiple targets with annotation | Keep only one |
| `failed to get reporting target` | Target list error | Check RBAC, cluster state |
| Upload fails in logs | Credentials/permissions | Check secret, IAM policy |

---

## Debugging Commands

```bash
# Check reporting target
kubectl get targets -A -o json | \
  jq '.items[] | select(.metadata.annotations."trilio.io/reporting-target" == "true")'

# View scan job full command
kubectl get job <name> -n threat-scanning-system -o jsonpath='{.spec.template.spec.containers[0].args[0]}'

# Check upload logs
kubectl logs <pod> -n threat-scanning-system | tail -50

# Verify S3 upload
aws s3 ls s3://bucket/reports/<instance-id>/ --recursive
```

---

## Modified Files

1. **`pkg/helpers/job_helper.go`**
   - Modified: `GetScanJob()` - Added reporting target lookup and command building
   - Added: `getReportingTargetName()` - Find reporting target
   - Added: `buildReportUploadCommand()` - Build upload command

---

## Build Verification

```bash
✅ go build -o /dev/null ./pkg/helpers/...
✅ go build -o /dev/null ./controllers/scaninstance/...
```

All builds successful.

---

## Key Design Decisions

1. **Why `&&` operator?**
   - Ensures upload only on scan success
   - Maintains scan failure status if scan fails
   - Fails job if upload fails (alerts on issues)

2. **Why cluster-wide reporting target?**
   - Simplifies configuration
   - Centralized report storage
   - Easy to manage access control

3. **Why API-only access for uploader?**
   - No need to mount backup datastore
   - Faster and simpler
   - Uses S3 API directly

4. **Why structured path?**
   - Easy querying by dashboard
   - Organized by hierarchy
   - Timestamp-based versioning

---

## Next Steps

After implementation:
1. Deploy updated controller
2. Create reporting target
3. Test with sample ScanInstance
4. Configure dashboard to read from S3 path
5. Set up monitoring/alerts for upload failures

---

_Quick Reference for Report Upload Integration_
_See REPORT_UPLOAD_INTEGRATION.md for full documentation_
