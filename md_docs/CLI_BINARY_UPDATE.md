# CLI Binary Update for Report Uploader

**Date:** March 26, 2026  
**Status:** ✅ Complete

---

## Change Summary

Updated the report uploader invocation to use the installed CLI binary instead of calling Python directly.

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

---

## Files Modified

### 1. Controller Implementation
- **`pkg/helpers/job_helper.go`**
  - Updated `buildReportUploadCommand()` function
  - Changed from: `python3 .../report_uploader/cli.py`
  - Changed to: `/usr/local/bin/report-uploader`

### 2. Documentation Files
All documentation files updated to reflect the new CLI binary path:
- `REPORT_UPLOAD_INTEGRATION.md`
- `REPORT_UPLOAD_QUICK_REF.md`
- `DATABASE_SETUP_UPDATE.md`
- `COMPLETE_PIPELINE_DIAGRAM.md`
- `FINAL_IMPLEMENTATION_SUMMARY.md`
- `DATABASE_SETUP_INTEGRATION.md`
- `REPORT_UPLOAD_FLOW_DIAGRAM.md`
- `REPORT_UPLOAD_IMPLEMENTATION_COMPLETE.md`

---

## Complete Command Chain

### For ObjectStore Backup Targets:
```bash
python3 /opt/threat-scanning/datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py \
  --target-name=<target-name> \
  --group=threatscanning.trilio.io \
  --version=v1 && \
python3 /app/main.py multi-vm \
  /app/config/minimal_working.json \
  /config/vm_artifacts_configuration.json \
  --production && \
/usr/local/bin/soc-db-setup \
  --dir dashboard_reports && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix <instance-id>/<target-uid>/<plan-uid>/<backup-uid>/<timestamp> \
  --target-name <reporting-target-name>
```

### For NFS Backup Targets:
```bash
python3 /app/main.py multi-vm \
  /app/config/minimal_working.json \
  /config/vm_artifacts_configuration.json \
  --production && \
/usr/local/bin/soc-db-setup \
  --dir dashboard_reports && \
/usr/local/bin/report-uploader \
  --upload-directory dashboard_reports/ \
  --object-prefix <instance-id>/<target-uid>/<plan-uid>/<backup-uid>/<timestamp> \
  --target-name <reporting-target-name>
```

---

## Assumptions

The change assumes:
1. The `report-uploader` CLI binary is installed at `/usr/local/bin/report-uploader` in the scan job container
2. The binary has the same CLI interface as the Python script
3. The binary is executable and has proper permissions
4. The container image build process includes the binary installation

---

## Verification

```bash
# 1. Check the updated command in scan job
kubectl get job <scan-job-name> -o yaml | grep -A 5 "args:"

# 2. Verify binary exists in container
kubectl exec -it <scan-pod> -- which report-uploader
# Expected: /usr/local/bin/report-uploader

# 3. Test binary execution
kubectl exec -it <scan-pod> -- /usr/local/bin/report-uploader --help

# 4. Monitor logs during scan
kubectl logs -f <scan-pod> | grep -i "report.*upload"
```

---

## Benefits

1. **Cleaner Invocation:** Shorter, more concise command
2. **Proper Packaging:** Follows standard conventions for installed binaries
3. **Better Path Management:** No need to track Python module paths
4. **Faster Execution:** Binary may have faster startup time vs. Python interpreter

---

## Rollback

If needed to revert to Python path:

```go
// In buildReportUploadCommand():
return fmt.Sprintf(
    "python3 %s/report_uploader/cli.py --upload-directory dashboard_reports/ --object-prefix %s --target-name %s",
    internal.DatastoreAttacherPathInContainer,
    objectPrefix,
    reportingTargetName,
)
```

---

**Implementation:** Complete ✅  
**Build Status:** Success ✅  
**Documentation:** Updated ✅
