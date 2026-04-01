# Report Upload Integration - Flow Diagram

## Complete Scan and Upload Flow

```
┌─────────────────────────────────────────────────────────┐
│              ScanInstance Created                       │
│  (with labels: instance-id, target-uid, plan-uid, etc) │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │  Controller Reconciles     │
        │  - Fetches backup target   │
        │  - Finds reporting target  │
        └────────────┬───────────────┘
                     │
                     ▼
   ┌─────────────────────────────────────────────┐
   │  Find Cluster-Wide Reporting Target         │
   │  getReportingTargetName()                   │
   ├─────────────────────────────────────────────┤
   │  1. List all Target CRs                     │
   │  2. Filter by annotation:                   │
   │     trilio.io/reporting-target=true         │
   │  3. Validate exactly ONE found              │
   │  4. Return target name                      │
   └─────────────┬───────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────┐
│  Build Report Upload Command                           │
│  buildReportUploadCommand()                            │
├────────────────────────────────────────────────────────┤
│  object_prefix = instance-id/target-uid/               │
│                  plan-uid/backup-uid/timestamp         │
│                                                        │
│  command = /usr/local/bin/report-uploader \           │
│    --upload-directory dashboard_reports/ \            │
│    --object-prefix <prefix> \                         │
│    --target-name <reporting-target-name>              │
└─────────────┬──────────────────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────────────────┐
│  Create Scan Job with Full Command                     │
│  GetScanJob()                                          │
├────────────────────────────────────────────────────────┤
│  Full Command:                                         │
│  mount_datastore &&                                    │
│  scan_engine --production &&                           │
│  report_uploader <args>                                │
│                                                        │
│  - Mount: Only for ObjectStore backup targets          │
│  - Scan: Enhanced SOC analysis scanner                 │
│  - Upload: Report uploader with API access             │
└─────────────┬──────────────────────────────────────────┘
              │
              ▼
     ┌────────────────────┐
     │  Scan Job Starts   │
     └────────┬───────────┘
              │
              ▼
┌──────────────────────────────────────────────────────┐
│         Step 1: Mount Datastore (if ObjectStore)     │
│  python3 .../mount_datastores.py --target-name=...   │
│  - Mounts backup target at /triliodata               │
│  - Uses s3fuse for ObjectStore                       │
│  - Skip for NFS (already mounted via PVC)            │
└──────────────┬───────────────────────────────────────┘
               │
               ▼ (via && operator)
┌──────────────────────────────────────────────────────┐
│         Step 2: Run Scan Engine                      │
│  python3 /app/main.py multi-vm ... --production      │
│  - Scans VM disk images                              │
│  - Performs threat analysis                          │
│  - Generates reports in dashboard_reports/           │
│  - Exit code: 0 = success, 1 = failure               │
└──────────────┬───────────────────────────────────────┘
               │
               ▼ (via && operator - only if scan succeeds)
┌──────────────────────────────────────────────────────┐
│         Step 3: Upload Reports                       │
│  /usr/local/bin/report-uploader                      │
│    --upload-directory dashboard_reports/             │
│    --object-prefix <prefix>                          │
│    --target-name reporting-target                    │
│  - Uses S3 API (no mount needed)                     │
│  - Uploads all files from dashboard_reports/         │
│  - Structured path in S3                             │
└──────────────┬───────────────────────────────────────┘
               │
      ┌────────┴─────────┐
      │                  │
      ▼                  ▼
┌───────────┐      ┌─────────────┐
│  SUCCESS  │      │   FAILURE   │
│  Exit: 0  │      │   Exit: 1   │
└─────┬─────┘      └──────┬──────┘
      │                   │
      ▼                   ▼
┌─────────────────┐  ┌──────────────────┐
│ ScanInstance:   │  │ ScanInstance:    │
│   Completed     │  │   Failed         │
│                 │  │                  │
│ Reports in S3   │  │ No upload done   │
└─────────────────┘  └──────────────────┘
```

## Upload Execution Flow

```
┌─────────────────────────────────────────┐
│  Scan Engine Execution                  │
├─────────────────────────────────────────┤
│  [2026-03-26 14:35:00] Starting scan   │
│  [2026-03-26 14:40:00] Processing VM1  │
│  [2026-03-26 14:45:00] Processing VM2  │
│  [2026-03-26 14:50:00] Generating      │
│                        report files    │
│  [2026-03-26 14:50:15] Scan complete   │
│  Exit code: 0                           │
└─────────────┬───────────────────────────┘
              │ && (AND operator)
              │ Only proceeds if exit 0
              ▼
┌─────────────────────────────────────────┐
│  Report Uploader Execution              │
├─────────────────────────────────────────┤
│  [2026-03-26 14:50:16] Connecting to   │
│                        reporting target │
│  [2026-03-26 14:50:17] Listing files   │
│                        in dashboard_    │
│                        reports/         │
│  [2026-03-26 14:50:18] Uploading:      │
│    - scan_report_vm1.json (1.2 MB)     │
│  [2026-03-26 14:50:20] Uploading:      │
│    - scan_report_vm2.json (850 KB)     │
│  [2026-03-26 14:50:22] Upload complete │
│  Exit code: 0                           │
└─────────────────────────────────────────┘
```

## S3 Storage Structure

```
S3 Bucket: threat-scan-reports
│
└── reports/
    └── instance-abc123/              ← From label: trilio.io/instance-id
        └── target-def456/            ← From label: trilio.io/backup-target
            └── plan-ghi789/          ← From label: trilio.io/backupplan
                └── backup-jkl012/    ← From label: trilio.io/backup
                    └── 2026-03-26T14-30-00/  ← ScanInstance.CreationTimestamp
                        ├── scan_report_2026-03-26T14-50-18_vm1.json
                        ├── scan_report_2026-03-26T14-50-20_vm2.json
                        └── summary.json
```

## Error Handling Flow

### Case 1: No Reporting Target

```
GetScanJob()
    ↓
getReportingTargetName()
    ↓
List all Targets
    ↓
Filter by annotation
    ↓
Found: 0 targets
    ↓
Return Error: "no reporting target found"
    ↓
Scan Job Creation FAILS
    ↓
ScanInstance Status: Failed
```

### Case 2: Multiple Reporting Targets

```
GetScanJob()
    ↓
getReportingTargetName()
    ↓
List all Targets
    ↓
Filter by annotation
    ↓
Found: 2 targets [target1, target2]
    ↓
Return Error: "multiple reporting targets found"
    ↓
Scan Job Creation FAILS
    ↓
ScanInstance Status: Failed
```

### Case 3: Scan Fails

```
Scan Job Starts
    ↓
Mount Datastore: SUCCESS
    ↓
Scan Engine: FAILURE (exit code 1)
    ↓
&& operator checks exit code
    ↓
Upload NOT executed (skipped)
    ↓
Job Status: Failed
    ↓
ScanInstance Status: Failed
```

### Case 4: Upload Fails

```
Scan Job Starts
    ↓
Mount Datastore: SUCCESS
    ↓
Scan Engine: SUCCESS (exit code 0)
    ↓
&& operator proceeds
    ↓
Upload: FAILURE (exit code 1)
    ↓
Job Status: Failed
    ↓
ScanInstance Status: Failed
```

## Reporting Target Discovery

```
┌──────────────────────────────────────────┐
│  getReportingTargetName(ctx, client)     │
└────────────────┬─────────────────────────┘
                 │
                 ▼
        ┌────────────────┐
        │  List Targets  │
        └────────┬───────┘
                 │
                 ▼
┌────────────────────────────────────────────┐
│  For each target:                          │
│    if target.IsReportingTarget():          │
│      reportingTargets.append(target.Name)  │
└────────────────┬───────────────────────────┘
                 │
                 ▼
        ┌────────────────────┐
        │  Validate Count    │
        └────────┬───────────┘
                 │
        ┌────────┴─────────┐
        │                  │
        ▼                  ▼
    ┌──────┐          ┌───────┐          ┌─────────┐
    │ == 0 │          │ == 1  │          │  > 1    │
    └───┬──┘          └───┬───┘          └────┬────┘
        │                 │                   │
        ▼                 ▼                   ▼
    ┌──────┐          ┌──────┐           ┌───────┐
    │ ERROR│          │  OK  │           │ ERROR │
    └──────┘          └──────┘           └───────┘
                          │
                          ▼
                  ┌───────────────┐
                  │ Return Name   │
                  └───────────────┘
```

## Path Construction Flow

```
┌────────────────────────────────────────┐
│  buildReportUploadCommand()            │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────┐
│  Extract from ScanInstance Labels:             │
│  - instance-id     = "instance-abc123"         │
│  - target-uid      = "target-def456"           │
│  - plan-uid        = "plan-ghi789"             │
│  - backup-uid      = "backup-jkl012"           │
│  - timestamp       = 2026-03-26T14:30:00       │
└────────────────┬───────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────┐
│  Build Path String:                            │
│  fmt.Sprintf("%s/%s/%s/%s/%s",                 │
│    instanceID, targetUID, planUID,             │
│    backupUID, timestamp)                       │
└────────────────┬───────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────┐
│  Result:                                       │
│  "instance-abc123/target-def456/               │
│   plan-ghi789/backup-jkl012/                   │
│   2026-03-26T14-30-00"                         │
└────────────────┬───────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────┐
│  Build Full Command:                           │
│  "python3 .../cli.py                           │
│   --upload-directory dashboard_reports/        │
│   --object-prefix <path>                       │
│   --target-name reporting-target"              │
└────────────────────────────────────────────────┘
```

## Timeline Example

```
Time: 14:30:00 - ScanInstance created
                 └─ CreationTimestamp: 2026-03-26T14:30:00

Time: 14:30:05 - Controller reconciles
                 └─ Finds reporting target
                 └─ Builds path: .../2026-03-26T14-30-00
                 └─ Creates scan job

Time: 14:30:10 - Scan job pod starts
                 └─ Container: threat-scan-scanner

Time: 14:30:15 - Mount datastore (ObjectStore only)
                 └─ s3fuse mount at /triliodata

Time: 14:35:00 - Scan engine starts
                 └─ Processing disk images

Time: 14:50:00 - Scan engine completes
                 └─ Reports in dashboard_reports/
                 └─ Exit code: 0

Time: 14:50:01 - Report uploader starts (via &&)
                 └─ Connecting to reporting-target
                 └─ Using S3 API

Time: 14:50:05 - Uploading files
                 └─ scan_report_vm1.json → S3
                 └─ scan_report_vm2.json → S3

Time: 14:50:10 - Upload complete
                 └─ Exit code: 0

Time: 14:50:15 - Job status: Succeeded
                 └─ ScanInstance status: Completed

Result in S3:
s3://threat-scan-reports/reports/
  instance-abc123/target-def456/plan-ghi789/
  backup-jkl012/2026-03-26T14-30-00/
    ├─ scan_report_2026-03-26T14-50-05_vm1.json
    └─ scan_report_2026-03-26T14-50-06_vm2.json
```

---

_Visual flow diagram for Report Upload Integration_
