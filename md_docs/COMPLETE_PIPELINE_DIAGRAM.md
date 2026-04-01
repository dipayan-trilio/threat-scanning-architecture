# Complete Scan Pipeline - Visual Overview

## End-to-End Flow with All Features

```
┌──────────────────────────────────────────────────────────────────────┐
│                     ScanInstance Created                             │
│  Labels: instance-id, backup-target, backupplan, backup              │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │  Controller Reads:           │
              │  - PostgreSQL env vars       │
              │  - Reporting target          │
              └──────────────┬───────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │         PreScan Job                    │
        │  Validates backup & populates          │
        │  ScanLocations                         │
        └────────────┬───────────────────────────┘
                     │
                     ▼
    ┌────────────────────────────────────────────┐
    │     Redis Deployment & Service             │
    │  Cache for scan coordination               │
    └────────────┬───────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│              ConfigMap Created                      │
│  Name: scan-config-<name>                           │
│  Data: vm_artifacts_configuration.json              │
└────────────┬────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────┐
│              Secret Created ✨                           │
│  Name: scan-secret-<name>                                │
│  Data:                                                   │
│    DATABASE_URL: postgresql+asyncpg://...                │
│    PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB        │
└────────────┬─────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────┐
│         Reporting Target Lookup ✨                       │
│  Find cluster-wide target with annotation:               │
│    trilio.io/reporting-target: "true"                    │
│  Result: reporting-target                                │
└────────────┬─────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────┐
│              Scan Job Created                            │
│  Name: threat-scan-scanjob-<name>                        │
│  envFrom:                                                │
│    - secretRef: scan-secret-<name>                       │
│  Command:                                                │
│    1. mount_datastore                                    │
│    2. scan_engine --production                           │
│    3. soc_database_setup --dir dashboard_reports ✨      │
│    4. report_uploader --object-prefix <path> ✨          │
└────────────┬─────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────┐
│                Scan Job Execution                        │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────────────────────────────────────┐         │
│  │ Step 1: Mount Datastore (ObjectStore)      │         │
│  │   s3fuse mount → /triliodata               │         │
│  │   Exit: 0 ✅                                │         │
│  └────────────────┬───────────────────────────┘         │
│                   │ && (proceed)                        │
│                   ▼                                      │
│  ┌────────────────────────────────────────────┐         │
│  │ Step 2: Run Scan Engine                    │         │
│  │   python3 /app/main.py multi-vm ...        │         │
│  │   - Scans VM disk images                   │         │
│  │   - Generates JSON reports                 │         │
│  │   - Outputs to dashboard_reports/          │         │
│  │   Exit: 0 ✅                                │         │
│  └────────────────┬───────────────────────────┘         │
│                   │ && (proceed)                        │
│                   ▼                                      │
│  ┌────────────────────────────────────────────┐         │
│  │ Step 3: Setup Database ✨ NEW              │         │
│  │   /usr/local/bin/soc-db-setup            │         │
│  │   - Reads dashboard_reports/*.json         │         │
│  │   - Connects to PostgreSQL                 │         │
│  │   - Inserts scans, IOCs, threats           │         │
│  │   - Creates relationships                  │         │
│  │   Exit: 0 ✅                                │         │
│  └────────────────┬───────────────────────────┘         │
│                   │ && (proceed)                        │
│                   ▼                                      │
│  ┌────────────────────────────────────────────┐         │
│  │ Step 4: Upload Reports ✨ NEW              │         │
│  │   /usr/local/bin/report-uploader           │         │
│  │   - Connects to reporting target (S3)      │         │
│  │   - Uploads dashboard_reports/             │         │
│  │   - Path: instance/target/plan/backup/ts   │         │
│  │   Exit: 0 ✅                                │         │
│  └────────────────────────────────────────────┘         │
│                                                          │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │   Job Status: Succeeded    │
        │   ScanInstance: Completed  │
        └────────────┬───────────────┘
                     │
        ┌────────────┴─────────────┐
        │                          │
        ▼                          ▼
┌───────────────────┐    ┌────────────────────┐
│  PostgreSQL DB    │    │   S3 Storage       │
│  ✅ Populated     │    │   ✅ Reports       │
│                   │    │                    │
│  Dashboard        │    │   Structured       │
│  queries data     │    │   path for         │
│  in real-time     │    │   history          │
└───────────────────┘    └────────────────────┘
```

## Detailed Step-by-Step Execution

```
T+0:00  │ Pod starts
T+0:05  │ Container ready
        │
T+0:10  │ ┌──────────────────────────────────────┐
        │ │ Step 1: Mount Datastore              │
        │ │ Command: mount_datastores.py         │
        │ └───────────────┬──────────────────────┘
T+0:15  │                 │ Mounting via s3fuse
T+0:20  │                 │ Mount complete ✅
        │                 │ Exit code: 0
        │                 ▼
T+0:21  │ ┌──────────────────────────────────────┐
        │ │ Step 2: Scan Engine                  │
        │ │ Command: /app/main.py multi-vm       │
        │ └───────────────┬──────────────────────┘
T+0:25  │                 │ Loading VM artifacts
T+2:00  │                 │ Scanning VM1 disk
T+5:00  │                 │ Scanning VM1 memory
T+7:00  │                 │ Analyzing VM1
T+9:00  │                 │ Scanning VM2 disk
T+12:00 │                 │ Scanning VM2 memory
T+14:00 │                 │ Analyzing VM2
T+15:00 │                 │ Generating reports
T+15:30 │                 │ Scan complete ✅
        │                 │ Exit code: 0
        │                 ▼
T+15:31 │ ┌──────────────────────────────────────┐
        │ │ Step 3: Database Setup ✨            │
        │ │ Command: soc_database_setup.py       │
        │ └───────────────┬──────────────────────┘
T+15:32 │                 │ Reading reports
T+15:33 │                 │ Parsing VM1 report
T+15:34 │                 │ Inserting to PostgreSQL
T+15:35 │                 │   - Scan record
T+15:36 │                 │   - 15 IOCs
T+15:37 │                 │   - 8 Threats
T+15:38 │                 │ Parsing VM2 report
T+15:39 │                 │ Inserting to PostgreSQL
T+15:40 │                 │   - 12 IOCs
T+15:41 │                 │   - 5 Threats
T+15:42 │                 │ Database setup complete ✅
        │                 │ Exit code: 0
        │                 ▼
T+15:43 │ ┌──────────────────────────────────────┐
        │ │ Step 4: Report Upload ✨             │
        │ │ Command: /usr/local/bin/report-uploader │
        │ └───────────────┬──────────────────────┘
T+15:44 │                 │ Connecting to S3
T+15:45 │                 │ Listing local files
T+15:46 │                 │ Uploading scan_report_vm1.json
T+15:48 │                 │ Uploaded: 1.2 MB
T+15:49 │                 │ Uploading scan_report_vm2.json
T+15:51 │                 │ Uploaded: 850 KB
T+15:52 │                 │ Upload complete ✅
        │                 │ Exit code: 0
        │                 ▼
T+15:53 │         ┌───────────────────┐
        │         │  Job Succeeded    │
        │         └───────────────────┘
```

## Data Flow Diagram

```
┌─────────────┐
│ Scan Engine │
│   (15 min)  │
└──────┬──────┘
       │ Generates
       ▼
┌──────────────────────────────┐
│   dashboard_reports/         │
│   ├─ scan_report_vm1.json    │
│   ├─ scan_report_vm2.json    │
│   └─ summary.json            │
└──────┬────────────┬──────────┘
       │            │
       │            │ Both read from same directory
       │            │
       ▼            ▼
┌─────────────┐  ┌──────────────┐
│  Database   │  │   Report     │
│   Setup     │  │   Uploader   │
│  (10 sec)   │  │   (5 sec)    │
└──────┬──────┘  └──────┬───────┘
       │                │
       │ Writes         │ Uploads
       ▼                ▼
┌─────────────┐  ┌──────────────┐
│ PostgreSQL  │  │  S3 Storage  │
│  Database   │  │              │
│             │  │  Structured  │
│  Tables:    │  │  Path:       │
│  - scans    │  │  reports/    │
│  - iocs     │  │    └─ ...    │
│  - threats  │  │       └─ ts/ │
│  - vms      │  │         └─[files]
│             │  │              │
│  Real-time  │  │  Historical  │
│  Dashboard  │  │  Archive     │
└─────────────┘  └──────────────┘
       │                │
       └────────┬───────┘
                │
                ▼
        ┌───────────────┐
        │   Dashboard   │
        │   Frontend    │
        │               │
        │ - Queries DB  │
        │ - Views S3    │
        └───────────────┘
```

## Failure Scenarios

### Scenario 1: Scan Fails
```
Mount ✅ → Scan ❌
              ↓
         Exit code: 1
              ↓
    Database Setup: SKIPPED
              ↓
    Report Upload: SKIPPED
              ↓
    Job Status: Failed
```

### Scenario 2: Database Setup Fails
```
Mount ✅ → Scan ✅ → Database Setup ❌
                                   ↓
                              Exit code: 1
                                   ↓
                      Report Upload: SKIPPED
                                   ↓
                      Job Status: Failed
                                   ↓
                Reports exist locally but:
                - Not in PostgreSQL database
                - Not uploaded to S3
```

### Scenario 3: Upload Fails
```
Mount ✅ → Scan ✅ → Database Setup ✅ → Upload ❌
                                               ↓
                                          Exit code: 1
                                               ↓
                                     Job Status: Failed
                                               ↓
                              Data state:
                              - PostgreSQL: ✅ Populated
                              - S3: ❌ Not uploaded
```

### Scenario 4: All Success
```
Mount ✅ → Scan ✅ → Database Setup ✅ → Upload ✅
                                               ↓
                                          Exit code: 0
                                               ↓
                                     Job Status: Succeeded
                                               ↓
                              Data state:
                              - PostgreSQL: ✅ Populated
                              - S3: ✅ Uploaded
                              - Dashboard: ✅ Ready
```

## Environment Variables Flow

```
┌─────────────────────────────────────┐
│   Controller Pod Environment        │
├─────────────────────────────────────┤
│ POSTGRES_HOST=postgres.db.svc...    │
│ POSTGRES_PORT=5432                  │
│ POSTGRES_USER=scanuser              │
│ POSTGRES_PASSWORD=********          │
│ POSTGRES_DASHBOARD_DATABASE=dash_db │
│ POSTGRES_CACHE_DATABASE=cache_db    │
└────────────┬────────────────────────┘
             │
             │ Read by GetPostgres*()
             │
             ▼
┌─────────────────────────────────────┐
│   GetScanSecret() creates:          │
│   scan-secret-<name>                │
├─────────────────────────────────────┤
│ stringData:                         │
│   DATABASE_URL: postgresql+asyncpg  │
│   PG_HOST: postgres.db.svc...       │
│   PG_PORT: 5432                     │
│   PG_USER: scanuser                 │
│   PG_PASSWORD: ********             │
│   PG_DB: dash_db                    │
└────────────┬────────────────────────┘
             │
             │ Mounted via envFrom
             │
             ▼
┌─────────────────────────────────────┐
│   Scan Job Pod Environment          │
├─────────────────────────────────────┤
│ From Secret (envFrom):              │
│   DATABASE_URL=postgresql+asyncpg   │
│   PG_HOST=postgres.db.svc...        │
│   PG_PORT=5432                      │
│   PG_USER=scanuser                  │
│   PG_PASSWORD=********              │
│   PG_DB=dash_db                     │
│                                     │
│ From Job Spec (env):                │
│   REDIS_URL=redis://redis-svc...    │
│   PRODUCTION=true                   │
│   JOB_NAME=...                      │
│   JOB_NAMESPACE=...                 │
└─────────────┬───────────────────────┘
              │
              │ Used by both:
              │
    ┌─────────┴──────────┐
    │                    │
    ▼                    ▼
┌─────────────┐  ┌──────────────────┐
│ Scan Engine │  │ Database Setup   │
│             │  │                  │
│ Uses:       │  │ Uses:            │
│ - REDIS_URL │  │ - DATABASE_URL   │
│ - DATABASE_ │  │ - PG_HOST        │
│   URL       │  │ - PG_PORT        │
│             │  │ - PG_USER        │
│             │  │ - PG_PASSWORD    │
│             │  │ - PG_DB          │
└─────────────┘  └──────────────────┘
```

## Command Construction

```
┌──────────────────────────────────────┐
│  GetScanJob(scanInstance, secret)   │
└────────────┬─────────────────────────┘
             │
             ├─► Get target details
             │
             ├─► Find reporting target
             │   getReportingTargetName()
             │
             ├─► Build scan command
             │   scanEngineCmd = "python3 /app/main.py ..."
             │   + "--production" (if PRODUCTION=true)
             │
             ├─► Build database setup command
             │   dbSetupCmd = "/usr/local/bin/soc-db-setup --dir dashboard_reports"
             │
             ├─► Build upload command
             │   buildReportUploadCommand()
             │   reportUploadCmd = "python3 .../cli.py ..."
             │
             ├─► Combine commands
             │   fullScanCmd = scanEngineCmd && dbSetupCmd && reportUploadCmd
             │
             └─► Add mount (ObjectStore only)
                 scanCmd = mountCmd && fullScanCmd
                 
                 Result:
                 mount && scan && db_setup && upload
```

## Timeline Visualization

```
Time    │ Action
────────┼──────────────────────────────────────────────────────────
00:00   │ ████ Mount datastore (ObjectStore)
00:20   │ ████████████████████████████████████ Scan Engine (VMs)
15:30   │ ██ Database Setup (Parse & Insert)
15:42   │ █ Upload Reports (S3)
15:53   │ ✅ Complete
        │
        │ Legend:
        │ █ = ~30 seconds
        │
        │ Total Time: ~16 minutes
        │   - Mount: 20 sec
        │   - Scan: 15 min 10 sec (most time)
        │   - DB Setup: 12 sec (NEW)
        │   - Upload: 10 sec (NEW)
```

## Resource Lifecycle

```
Creation ──────────────────────────────► Deletion
    │                                        │
    ├─ ConfigMap ──────────────────────────► Auto-delete (owner ref)
    │                                        │
    ├─ Secret ────────────────────────────► Auto-delete (owner ref)
    │      │                                 │
    │      └─► envFrom ──► Scan Job ───────► Auto-delete (owner ref)
    │                           │            │
    │                           └─► Steps:   │
    │                               1. Mount │
    │                               2. Scan  │
    │                               3. DB    │ ← NEW
    │                               4. Upload│ ← NEW
    │                                        │
    └─ Redis Deploy ──────────────────────► Auto-delete (owner ref)
    └─ Redis Service ──────────────────────► Auto-delete (owner ref)
```

---

_Complete visual overview of the scan pipeline with all integrated features_
