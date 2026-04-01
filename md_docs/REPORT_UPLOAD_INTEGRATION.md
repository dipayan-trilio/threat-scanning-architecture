# Report Upload Integration for Scan Jobs

## Overview

The scan job now automatically uploads scan reports to the reporting target after successful scan completion. This integration ensures that all scan reports are stored in a structured S3 path for dashboard consumption.

---

## Implementation Details

### Report Upload Flow

```
Scan Engine Completes Successfully
            ↓
      (via && operator)
            ↓
Report Uploader CLI Executed
            ↓
Uploads dashboard_reports/ to S3
            ↓
Structured Path in Reporting Target
```

### Command Structure

The scan job executes the following command:

```bash
# For ObjectStore targets:
mount_datastore && \
python3 /app/main.py multi-vm ... --production && \
/usr/local/bin/soc-db-setup --dir dashboard_reports && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix <prefix> \
  --target-name <reporting-target-name>

# For NFS targets:
python3 /app/main.py multi-vm ... --production && \
/usr/local/bin/soc-db-setup --dir dashboard_reports && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix <prefix> \
  --target-name <reporting-target-name>
```

### S3 Storage Structure

Reports are uploaded to the reporting target with the following path structure:

```
reports/
  └── <instance-id>/
      └── <backup-target-uid>/
          └── <backupplan-uid>/
              └── <backup-uid>/
                  └── <scan-timestamp>/
                      └── [report files from dashboard_reports/]
```

**Path Components:**
- `instance-id`: From ScanInstance label `trilio.io/instance-id`
- `backup-target-uid`: From ScanInstance label `trilio.io/backup-target`
- `backupplan-uid`: From ScanInstance label `trilio.io/backupplan`
- `backup-uid`: From ScanInstance label `trilio.io/backup`
- `scan-timestamp`: ScanInstance creation timestamp (format: `2006-01-02T15-04-05`)

**Example Path:**
```
reports/
  └── instance-abc123/
      └── target-def456/
          └── plan-ghi789/
              └── backup-jkl012/
                  └── 2026-03-26T14-30-45/
                      ├── scan_report_2026-03-26T14-35-12_vm1.json
                      ├── scan_report_2026-03-26T14-35-15_vm2.json
                      └── summary.json
```

---

## Key Features

### 1. Upload Only on Scan Success
- Uses `&&` operator to chain commands
- Report upload **only executes if scan completes successfully**
- If scan fails, upload is skipped
- Maintains scan job failure status

### 2. API-Only Access
- Report uploader uses **API-only access** to reporting target
- No datastore mounting required for upload
- Uses Target CR credentials (accessKey/secretKey)
- Supports all S3-compatible object stores

### 3. Cluster-Wide Reporting Target
- **Single reporting target** per cluster
- Identified by annotation: `trilio.io/reporting-target: "true"`
- Controller validates exactly one reporting target exists
- Error if no reporting target or multiple reporting targets found

### 4. Structured Storage
- Reports organized by instance → target → plan → backup → timestamp
- Enables easy querying by any level of hierarchy
- Timestamp-based versioning for multiple scans of same backup
- Dashboard can query reports by path structure

---

## Implementation Components

### Modified Function: `GetScanJob()`

**Location:** `pkg/helpers/job_helper.go`

**Changes:**
1. Fetches cluster-wide reporting target name
2. Builds report upload command with structured path
3. Appends upload command to scan command (with `&&`)
4. Updated for both NFS and ObjectStore backup targets

### New Function: `getReportingTargetName()`

**Purpose:** Find the cluster-wide reporting target

**Logic:**
```go
func getReportingTargetName(ctx context.Context, cl client.Client) (string, error) {
    // List all targets
    // Filter targets with IsReportingTarget() == true
    // Validate exactly one found
    // Return target name
}
```

**Error Cases:**
- No reporting target found → Error
- Multiple reporting targets found → Error

### New Function: `buildReportUploadCommand()`

**Purpose:** Construct the report uploader CLI command

**Logic:**
```go
func buildReportUploadCommand(scanInstance *v1.ScanInstance, reportingTargetName string) string {
    // Build object prefix from ScanInstance labels and timestamp
    objectPrefix := fmt.Sprintf("%s/%s/%s/%s/%s",
        instanceID, targetUID, planUID, backupUID, timestamp)
    
    // Return CLI command
    return fmt.Sprintf("python3 .../cli.py --upload-directory dashboard_reports/ --object-prefix %s --target-name %s",
        objectPrefix, reportingTargetName)
}
```

---

## Configuration

### Reporting Target Setup

Create a reporting target with the annotation:

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  vendor: AWS  # or MinIO, S3-compatible, etc.
  objectStoreCredentials:
    url: "https://s3.amazonaws.com"
    bucketName: "threat-scan-reports"
    region: "us-east-1"
    credentialSecret:
      name: reporting-target-credentials
```

**Credentials Secret:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: reporting-target-credentials
  namespace: threat-scanning-system
type: Opaque
stringData:
  accessKey: "AKIAIOSFODNN7EXAMPLE"
  secretKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
```

### Validation

The controller validates:
- ✅ Exactly one reporting target exists
- ✅ Reporting target is Available
- ✅ ScanInstance has all required labels

---

## Error Handling

### No Reporting Target

**Error:** `failed to get reporting target: no reporting target found`

**Resolution:**
1. Create a Target CR with annotation `trilio.io/reporting-target: "true"`
2. Ensure target is validated and Available
3. Retry ScanInstance creation

### Multiple Reporting Targets

**Error:** `failed to get reporting target: multiple reporting targets found: [target1, target2]`

**Resolution:**
1. Remove annotation from extra targets
2. Keep only one reporting target
3. Retry ScanInstance creation

### Scan Failure

**Behavior:** Report upload is **not attempted**

**Reason:** Uses `&&` operator, so upload only runs if scan succeeds

**Debugging:**
```bash
kubectl logs <scan-job-pod> -n threat-scanning-system
# Check scan logs, upload will not be in logs if scan failed
```

### Upload Failure

**Behavior:** Scan job **fails** (exit code != 0)

**Reason:** Upload is part of job command, failure propagates

**Debugging:**
```bash
kubectl logs <scan-job-pod> -n threat-scanning-system
# Look for report uploader error messages
# Common issues: credentials, network, bucket permissions
```

**Temporary Workaround:** If upload issues are blocking scans, you can modify the command to continue on upload failure:
```bash
# Change && to ; or || true (not recommended for production)
scanCmd && reportUploadCmd || true
```

---

## Testing

### Prerequisites

1. **Create Reporting Target:**
   ```bash
   kubectl apply -f reporting-target.yaml
   kubectl get target reporting-target -o yaml
   # Verify annotation: trilio.io/reporting-target: "true"
   # Verify status: Available
   ```

2. **Verify Target Credentials:**
   ```bash
   kubectl get secret reporting-target-credentials -n threat-scanning-system
   ```

### Test Scan with Report Upload

1. **Create ScanInstance:**
   ```bash
   kubectl apply -f scaninstance-sample.yaml
   ```

2. **Monitor Scan Job:**
   ```bash
   kubectl get job -n threat-scanning-system -l trilio.io/scaninstance-name=<name>
   kubectl logs -f job/<scan-job-name> -n threat-scanning-system
   ```

3. **Verify Command:**
   ```bash
   kubectl get job <scan-job-name> -n threat-scanning-system -o yaml | grep -A 5 "args:"
   # Should see:
   # - python3 /app/main.py ... && /usr/local/bin/report-uploader ...
   ```

4. **Check Report Upload:**
   ```bash
   # View logs to see upload progress
   kubectl logs <scan-job-pod> -n threat-scanning-system | grep -i "upload"
   
   # Expected output:
   # Scan completed successfully
   # Uploading reports to s3://bucket/reports/instance-id/...
   # Upload complete: X files uploaded
   ```

5. **Verify in S3:**
   ```bash
   # Using AWS CLI or MinIO client
   aws s3 ls s3://threat-scan-reports/reports/
   # Should see directory structure with timestamps
   
   aws s3 ls s3://threat-scan-reports/reports/<instance-id>/<target-uid>/<plan-uid>/<backup-uid>/<timestamp>/
   # Should see report JSON files
   ```

### Test Failure Scenarios

1. **Scan Failure (Upload Should Not Run):**
   ```bash
   # Cause scan to fail (e.g., invalid config)
   # Check logs: upload command should not appear
   kubectl logs <scan-job-pod> | grep "report_uploader"
   # Should be empty if scan failed before upload
   ```

2. **Upload Failure (Job Should Fail):**
   ```bash
   # Use invalid reporting target credentials
   # Scan completes but upload fails
   # Job status should be Failed
   kubectl get job <scan-job-name> -o yaml | grep -A 5 "status:"
   ```

---

## Monitoring and Observability

### Metrics to Track

1. **Report Upload Success Rate**
   - Track job completion vs. failure
   - Filter by upload-related errors

2. **Upload Duration**
   - Time between scan completion and upload completion
   - Helps identify performance bottlenecks

3. **Storage Growth**
   - Monitor S3 bucket size
   - Alert on rapid growth or storage limits

### Logging

**Scan Job Logs:**
```
[2026-03-26 14:35:12] Starting scan...
[2026-03-26 14:40:45] Scan completed successfully
[2026-03-26 14:40:46] Uploading reports to s3://bucket/reports/instance-abc/...
[2026-03-26 14:40:48] Uploaded: scan_report_vm1.json (1.2 MB)
[2026-03-26 14:40:49] Uploaded: scan_report_vm2.json (850 KB)
[2026-03-26 14:40:50] Upload complete: 2 files, 2.05 MB total
```

**Controller Logs:**
```
[2026-03-26 14:30:00] Creating scan job for ScanInstance: scan-instance-xyz
[2026-03-26 14:30:00] Reporting target found: reporting-target
[2026-03-26 14:30:00] Report path: instance-abc/target-def/plan-ghi/backup-jkl/2026-03-26T14-30-00
[2026-03-26 14:30:01] Scan job created: threat-scan-scanjob-scan-instance-xyz
```

---

## Troubleshooting

### Issue: "No reporting target found"

**Cause:** No Target CR with `trilio.io/reporting-target: "true"` annotation

**Solution:**
```bash
# List all targets
kubectl get targets -A

# Check annotations
kubectl get target <name> -o yaml | grep -A 5 "annotations:"

# Add annotation if missing
kubectl annotate target <name> trilio.io/reporting-target=true
```

### Issue: "Multiple reporting targets found"

**Cause:** Multiple Target CRs have the reporting annotation

**Solution:**
```bash
# Find all reporting targets
kubectl get targets -A -o json | jq '.items[] | select(.metadata.annotations."trilio.io/reporting-target" == "true") | .metadata.name'

# Remove annotation from extras
kubectl annotate target <extra-target> trilio.io/reporting-target-
```

### Issue: Upload fails with "Access Denied"

**Cause:** Reporting target credentials lack permissions

**Solution:**
```bash
# Verify credentials
kubectl get secret reporting-target-credentials -n threat-scanning-system -o yaml

# Test credentials manually
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
aws s3 ls s3://threat-scan-reports/reports/

# Update IAM policy to allow:
# - s3:PutObject
# - s3:ListBucket
# - s3:GetObject (for verification)
```

### Issue: Reports not appearing in expected path

**Cause:** Path construction issue or incorrect labels

**Solution:**
```bash
# Check ScanInstance labels
kubectl get scaninstance <name> -o yaml | grep -A 10 "labels:"

# Verify all required labels exist:
# - trilio.io/instance-id
# - trilio.io/backup-target
# - trilio.io/backupplan
# - trilio.io/backup

# Check actual upload path in logs
kubectl logs <scan-job-pod> | grep "object-prefix"
```

---

## Performance Considerations

1. **Report Size:** Large reports (>10 MB) may slow upload
2. **Network:** Upload speed depends on network to S3
3. **Concurrent Scans:** Multiple scans can upload simultaneously
4. **S3 Limits:** Be aware of S3 request rate limits

---

## Security Considerations

1. **Credentials:** Reporting target credentials stored in Kubernetes Secret
2. **Access Control:** Use IAM policies to restrict S3 access
3. **Encryption:** Enable S3 server-side encryption
4. **Audit:** Enable S3 access logging for compliance

---

## Future Enhancements

1. **Retry Logic:** Retry failed uploads with exponential backoff
2. **Compression:** Compress reports before upload
3. **Streaming:** Stream large reports instead of buffering
4. **Multi-Target:** Support multiple reporting targets (per-region, per-tier)
5. **Report Cleanup:** Automatic deletion of old reports (retention policy)

---

## Related Documentation

- [Report Uploader CLI](../datastore-attacher/REPORT_UPLOADER_README.md)
- [PostgreSQL Secret Integration](POSTGRES_SECRET_INTEGRATION.md)
- [ScanInstance Controller](SCANINSTANCE_CONTROLLER.md)
- [Architecture Overview](architecture.md)

---

_Generated: 2026-03-26_
_Feature: Report Upload Integration_
_Status: Implemented and Tested_
