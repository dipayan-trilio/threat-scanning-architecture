# CLI Binary Updates & Report Path Status

**Date:** March 26, 2026  
**Status:** ✅ Complete

---

## Overview

Two key updates to the threat scanning controller:

1. **CLI Binary Updates:** Both `soc_database_setup.py` and `report_uploader/cli.py` now use installed CLI binaries
2. **Report Path in Status:** The report S3 path is now recorded in `.status.report` field upon scan completion

---

## Change 1: CLI Binary for Database Setup

### Before:
```bash
python3 soc_database_setup.py --dir dashboard_reports
```

### After:
```bash
/usr/local/bin/soc-db-setup --dir dashboard_reports
```

### Files Modified:
- **`pkg/helpers/job_helper.go`:** Updated `dbSetupCmd` variable in `GetScanJob()` function

---

## Change 2: CLI Binary for Report Uploader

### Before:
```bash
python3 /opt/threat-scanning/datastore-attacher/report_uploader/cli.py \
  --upload-directory dashboard_reports/ \
  --object-prefix <prefix> \
  --target-name <name>
```

### After:
```bash
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix <prefix> \
  --target-name <name>
```

### Files Modified:
- **`pkg/helpers/job_helper.go`:** Updated `buildReportUploadCommand()` function

---

## Change 3: Report Path in ScanInstance Status

### Implementation

When a scan completes successfully, the controller now updates the `.status.report` field with the S3 path where reports were uploaded.

#### New Helper Function:

```go
// GetReportPath constructs and returns the report path (object prefix) for a ScanInstance
// This is the S3 path where reports are uploaded
func GetReportPath(scanInstance *v1.ScanInstance) string {
	return fmt.Sprintf("reports/%s/%s/%s/%s/%s",
		scanInstance.GetInstanceID(),
		scanInstance.GetBackupTargetName(),
		scanInstance.GetBackupPlanUID(),
		scanInstance.GetBackupUID(),
		scanInstance.CreationTimestamp.Format("2006-01-02T15-04-05"),
	)
}
```

#### Status Update Logic:

```go
case v1.Completed:
	if !scanInstance.HasCondition(v1.Scanning, v1.Completed) {
		// Set report path in status before marking as completed
		reportPath := helpers.GetReportPath(scanInstance)
		if scanInstance.Status.Report != reportPath {
			scanInstance.Status.Report = reportPath
			if err := r.Client.Status().Update(ctx, scanInstance); err != nil {
				return ctrl.Result{}, fmt.Errorf("failed to update report path: %w", err)
			}
			log.Infof("Updated report path in status: %s", reportPath)
		}
		
		// ... continue with completion logic
	}
```

### Files Modified:
- **`pkg/helpers/job_helper.go`:**
  - Added `GetReportPath()` helper function
  - Refactored `buildReportUploadCommand()` to use `GetReportPath()`

- **`controllers/scaninstance/controller_helper.go`:**
  - Updated `processScanJobStatus()` to set `.status.report` field on completion

### Status Field Definition:

The `.status.report` field already existed in the CRD schema:

```go
// Report is the path to the scan report
// +nullable:true
// +kubebuilder:validation:Optional
Report string `json:"report,omitempty"`
```

---

## Complete Command Chain

### Final Pipeline (All Changes Integrated):

```bash
# For ObjectStore targets:
python3 mount_datastores.py --target-name=<target> && \
python3 /app/main.py multi-vm config.json artifacts.json --production && \
/usr/local/bin/soc-db-setup --dir dashboard_reports && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix reports/<instance>/<target>/<plan>/<backup>/<timestamp> \
  --target-name <reporting-target>

# For NFS targets:
python3 /app/main.py multi-vm config.json artifacts.json --production && \
/usr/local/bin/soc-db-setup --dir dashboard_reports && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix reports/<instance>/<target>/<plan>/<backup>/<timestamp> \
  --target-name <reporting-target>
```

---

## Benefits

### 1. CLI Binary Usage
- **Consistency:** Both utilities now use the same invocation pattern
- **Cleaner Commands:** Shorter, more readable job specifications
- **Better Packaging:** Follows standard Unix conventions for installed binaries
- **Faster Execution:** Binaries may have faster startup vs. Python interpreter

### 2. Report Path in Status
- **Discoverability:** External systems can query ScanInstance to find report location
- **Traceability:** Clear audit trail of where reports are stored
- **Integration:** Dashboard or other services can easily retrieve report paths
- **Self-Documentation:** The ScanInstance resource itself documents its output location

---

## Verification

### 1. Check Scan Job Command:
```bash
kubectl get job <scan-job-name> -o yaml | grep -A 10 "args:"

# Should see:
# - /bin/sh
# - -c
# - ... && /usr/local/bin/soc-db-setup --dir dashboard_reports && /usr/local/bin/report-uploader ...
```

### 2. Verify CLI Binaries in Container:
```bash
kubectl exec -it <scan-pod> -- which soc-db-setup
# Expected: /usr/local/bin/soc-db-setup

kubectl exec -it <scan-pod> -- which report-uploader
# Expected: /usr/local/bin/report-uploader
```

### 3. Check Report Path in Status:
```bash
kubectl get scaninstance <name> -o jsonpath='{.status.report}'

# Expected output:
# reports/instance-abc/target-def/plan-ghi/backup-jkl/2026-03-26T14-30-45
```

### 4. Verify Report Path is Set on Completion:
```bash
# Watch status updates
kubectl get scaninstance <name> -o yaml -w

# After scan completes, should see:
# status:
#   status: Completed
#   report: reports/instance-abc/target-def/.../2026-03-26T14-30-45
```

---

## Container Requirements

The scan job container must have these binaries installed:

1. **`/usr/local/bin/soc-db-setup`**
   - Python script installed as CLI binary
   - Must accept `--dir` flag
   - Should have executable permissions

2. **`/usr/local/bin/report-uploader`**
   - Python script installed as CLI binary
   - Must accept `--upload-directory`, `--object-prefix`, `--target-name` flags
   - Should have executable permissions

### Example Dockerfile Installation:
```dockerfile
# Install database setup CLI
COPY soc_database_setup.py /usr/local/bin/soc-db-setup
RUN chmod +x /usr/local/bin/soc-db-setup && \
    sed -i '1i#!/usr/bin/env python3' /usr/local/bin/soc-db-setup

# Install report uploader CLI
COPY report_uploader/cli.py /usr/local/bin/report-uploader
RUN chmod +x /usr/local/bin/report-uploader && \
    sed -i '1i#!/usr/bin/env python3' /usr/local/bin/report-uploader
```

---

## Testing

### 1. Test Database Setup Binary:
```bash
kubectl exec -it <scan-pod> -- /usr/local/bin/soc-db-setup --help
```

### 2. Test Report Uploader Binary:
```bash
kubectl exec -it <scan-pod> -- /usr/local/bin/report-uploader --help
```

### 3. Test Full Pipeline:
```bash
# Create a ScanInstance
kubectl apply -f scaninstance-sample.yaml

# Monitor logs for CLI invocations
kubectl logs -f <scan-pod> | grep -E "soc-db-setup|report-uploader"

# Verify report path is set
kubectl get scaninstance <name> -o jsonpath='{.status.report}'
```

### 4. Verify Report Path Accuracy:
```bash
# Get report path from status
REPORT_PATH=$(kubectl get scaninstance <name> -o jsonpath='{.status.report}')

# Check if reports exist at that path in S3
aws s3 ls s3://<bucket>/$REPORT_PATH/
```

---

## Files Modified Summary

### Controller Implementation:
1. **`pkg/helpers/job_helper.go`**
   - Added `GetReportPath()` helper function (exported, reusable)
   - Updated `buildReportUploadCommand()` to use `GetReportPath()`
   - Changed `dbSetupCmd` from Python call to CLI binary
   - Changed report uploader from Python call to CLI binary

2. **`controllers/scaninstance/controller_helper.go`**
   - Updated `processScanJobStatus()` to set `.status.report` on completion
   - Writes report path before marking ScanInstance as completed
   - Includes error handling and logging

### Documentation:
- Updated all documentation files to reflect CLI binary usage
- Added this summary document

---

## Rollback Instructions

If needed to revert to Python invocations:

```go
// In GetScanJob():
dbSetupCmd := "python3 soc_database_setup.py --dir dashboard_reports"

// In buildReportUploadCommand():
return fmt.Sprintf(
    "python3 %s/report_uploader/cli.py --upload-directory dashboard_reports/ --object-prefix %s --target-name %s",
    internal.DatastoreAttacherPathInContainer,
    objectPrefix,
    reportingTargetName,
)

// In processScanJobStatus():
// Remove the status.report update section
```

---

## Example ScanInstance Status After Completion

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: scan-instance-abc123
  labels:
    trilio.io/instance-id: instance-abc
    trilio.io/backup-target: target-def456
    trilio.io/backupplan: plan-ghi789
    trilio.io/backup: backup-jkl012
  creationTimestamp: "2026-03-26T14:30:45Z"
spec:
  # ... spec details ...
status:
  status: Completed
  type: TVK
  report: reports/instance-abc/target-def456/plan-ghi789/backup-jkl012/2026-03-26T14-30-45
  condition:
    - phase: Scanning
      status: Completed
      timestamp: "2026-03-26T14:35:12Z"
      reason: "Scan completed successfully"
```

---

## Integration Points

### For Dashboard or External Services:

```bash
# Get all completed scans with report paths
kubectl get scaninstance -o json | \
  jq '.items[] | select(.status.status=="Completed") | {
    name: .metadata.name,
    report: .status.report,
    completedAt: .status.condition[] | select(.phase=="Scanning" and .status=="Completed") | .timestamp
  }'
```

### For Programmatic Access (Go):

```go
// Get report path from completed ScanInstance
if scanInstance.Status.Status == v1.ScanCompleted {
    reportPath := scanInstance.Status.Report
    if reportPath != "" {
        // Use report path for further processing
        log.Infof("Reports available at: %s", reportPath)
    }
}
```

---

**Implementation:** Complete ✅  
**Build Status:** Success ✅  
**Documentation:** Updated ✅  
**Report Path Status:** Integrated ✅
