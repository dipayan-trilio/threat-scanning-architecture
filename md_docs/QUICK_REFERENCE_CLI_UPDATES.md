# Quick Reference: CLI Binaries & Report Status

**Updated:** March 26, 2026

---

## Command Chain (Updated)

```bash
# For ObjectStore targets:
mount_datastores && \
scan_engine --production && \
/usr/local/bin/soc-db-setup --dir dashboard_reports && \
/usr/local/bin/report-uploader --upload-directory dashboard_reports/ --object-prefix <path> --target-name <name>

# For NFS targets:
scan_engine --production && \
/usr/local/bin/soc-db-setup --dir dashboard_reports && \
/usr/local/bin/report-uploader --upload-directory dashboard_reports/ --object-prefix <path> --target-name <name>
```

---

## CLI Binaries

| Binary | Location | Purpose | Flags |
|--------|----------|---------|-------|
| `soc-db-setup` | `/usr/local/bin/soc-db-setup` | Populate PostgreSQL from JSON reports | `--dir` |
| `report-uploader` | `/usr/local/bin/report-uploader` | Upload reports to S3 reporting target | `--upload-directory`, `--object-prefix`, `--target-name` |

---

## Report Path Status

### Field:
```yaml
status:
  report: "reports/instance-id/target-uid/plan-uid/backup-uid/timestamp"
```

### When Set:
- Automatically populated when scan job completes successfully
- Set BEFORE marking ScanInstance as `Completed`
- Persists for the lifetime of the ScanInstance resource

### Format:
```
reports/<instance-id>/<backup-target-uid>/<backupplan-uid>/<backup-uid>/<creation-timestamp>
```

### Example:
```
reports/instance-abc123/target-def456/plan-ghi789/backup-jkl012/2026-03-26T14-30-45
```

---

## Quick Commands

### Check CLI Binaries:
```bash
kubectl exec -it <scan-pod> -- which soc-db-setup report-uploader
```

### Check Scan Job Command:
```bash
kubectl get job <scan-job> -o yaml | grep -A 15 "args:"
```

### Get Report Path from Status:
```bash
kubectl get scaninstance <name> -o jsonpath='{.status.report}'
```

### List All Completed Scans with Report Paths:
```bash
kubectl get scaninstance -o json | jq -r '.items[] | select(.status.status=="Completed") | "\(.metadata.name): \(.status.report)"'
```

### Verify Reports in S3:
```bash
REPORT_PATH=$(kubectl get scaninstance <name> -o jsonpath='{.status.report}')
aws s3 ls s3://<bucket>/$REPORT_PATH/ --recursive
```

---

## Container Requirements

Both binaries must be installed in the scan job container image:

```dockerfile
# Install as executable binaries with shebang
COPY soc_database_setup.py /usr/local/bin/soc-db-setup
COPY report_uploader/cli.py /usr/local/bin/report-uploader
RUN chmod +x /usr/local/bin/soc-db-setup /usr/local/bin/report-uploader
```

Ensure scripts have shebang: `#!/usr/bin/env python3`

---

## Integration Examples

### Dashboard Query for Report Paths:
```python
# Get all completed scans with their report paths
scans = k8s_client.list_cluster_custom_object(
    group="threatscanning.trilio.io",
    version="v1",
    plural="scaninstances"
)

for scan in scans['items']:
    if scan['status']['status'] == 'Completed':
        name = scan['metadata']['name']
        report_path = scan['status']['report']
        print(f"Scan: {name}, Reports: s3://bucket/{report_path}/")
```

### Webhook Notification on Completion:
```go
// In controller when scan completes
if scanInstance.Status.Status == v1.ScanCompleted {
    reportPath := scanInstance.Status.Report
    notifyDashboard(scanInstance.Name, reportPath)
}
```

---

## Troubleshooting

### Report Path Not Set:
```bash
# Check if scan actually completed
kubectl get scaninstance <name> -o jsonpath='{.status.status}'

# Check scan job status
kubectl get job <scan-job> -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}'

# Check controller logs
kubectl logs -l app=threat-scanning-controller | grep "Updated report path"
```

### CLI Binary Not Found:
```bash
# Check if binaries exist
kubectl exec <scan-pod> -- ls -la /usr/local/bin/ | grep -E "soc-db-setup|report-uploader"

# Check if executable
kubectl exec <scan-pod> -- test -x /usr/local/bin/soc-db-setup && echo "Executable"
```

---

**All Changes:** Complete ✅  
**Build Status:** Success ✅  
**Documentation:** Updated ✅
