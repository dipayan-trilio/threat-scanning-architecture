# PostgreSQL Secret Integration - Visual Flow Diagram

## Complete Reconciliation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          ScanInstance Created                           │
│                     (via webhook or manual creation)                    │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
                        ┌─────────────────────────┐
                        │   Status: Queued        │
                        │   Phase: -              │
                        └────────────┬────────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │    PreScan Job Created         │
                    │    Validates backup exists     │
                    │    Updates ScanLocations       │
                    └────────────┬───────────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────────────┐
                │     PreScan Job Completed              │
                │     ScanLocations populated            │
                │     Phase: PreScan → Completed         │
                └────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │   Redis Deployment & Service Created           │
        │   Phase: RedisDeployment → InProgress          │
        └────────────┬───────────────────────────────────┘
                     │
                     ▼
   ┌─────────────────────────────────────────────────────┐
   │      Redis Deployment Ready                         │
   │      Phase: RedisDeployment → Ready                 │
   └─────────────┬───────────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────────┐
│               ConfigMap Created                            │
│   Name: scan-config-<scaninstance-name>                    │
│   Data: vm_artifacts_configuration.json                    │
│   OwnerRef: ScanInstance                                   │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│               ✨ Secret Created (NEW)                            │
│   Name: scan-secret-<scaninstance-name>                          │
│   Type: Opaque                                                   │
│   OwnerRef: ScanInstance                                         │
│   StringData:                                                    │
│     - DATABASE_URL: postgresql+asyncpg://user:pass@host:port/db │
│     - PG_HOST: <from POSTGRES_HOST env>                         │
│     - PG_PORT: <from POSTGRES_PORT env or 5432>                 │
│     - PG_USER: <from POSTGRES_USER env>                         │
│     - PG_PASSWORD: <from POSTGRES_PASSWORD env>                 │
│     - PG_DB: <from POSTGRES_DASHBOARD_DATABASE env>             │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────┐
│              Scan Job Created                                  │
│   Name: threat-scan-scanjob-<scaninstance-name>               │
│   OwnerRef: ScanInstance                                       │
│   Container:                                                   │
│     envFrom:                                                   │
│       - secretRef:                                             │
│           name: scan-secret-<scaninstance-name>                │
│     env:                                                       │
│       - JOB_NAME, JOB_NAMESPACE (from field refs)              │
│       - PRODUCTION, REDIS_URL (from controller)                │
│   Phase: Scanning → InProgress                                │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────────┐
            │   Scan Job Running       │
            │   Status: InProgress     │
            └──────────┬───────────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
         ▼                           ▼
┌────────────────┐          ┌────────────────┐
│ Job Completed  │          │  Job Failed    │
│ Status: 0      │          │  Status: 1     │
└────────┬───────┘          └────────┬───────┘
         │                           │
         ▼                           ▼
┌──────────────────────┐    ┌──────────────────────┐
│ ScanInstance:        │    │ ScanInstance:        │
│   Completed          │    │   Failed             │
│ Phase: Scanning →    │    │ Phase: Scanning →    │
│   Completed          │    │   Failed             │
│                      │    │                      │
│ Janitor Job Created  │    │ Resources Kept       │
│ (cleanup resources)  │    │ (for debugging)      │
└──────────────────────┘    └──────────────────────┘
```

## Resource Relationships

```
┌─────────────────────────────────────────────────────────┐
│                    ScanInstance (CR)                    │
│                    Owner of all below                   │
└───────────────┬─────────────────────────────────────────┘
                │
        ┌───────┴────────┬─────────────┬──────────────┐
        │                │             │              │
        ▼                ▼             ▼              ▼
┌──────────────┐  ┌──────────┐  ┌─────────┐  ┌──────────────┐
│ PreScan Job  │  │ ConfigMap│  │ Secret  │  │ Scan Job     │
│              │  │          │  │         │  │              │
│ (validates)  │  │ (config) │  │ (creds) │  │ (scans VMs)  │
└──────────────┘  └──────────┘  └────┬────┘  └──────────────┘
                                      │
                                      │ envFrom
                                      │
                                      ▼
                              ┌───────────────┐
                              │   Scan Pod    │
                              │               │
                              │ Environment:  │
                              │ - DATABASE_URL│
                              │ - PG_HOST     │
                              │ - PG_PORT     │
                              │ - PG_USER     │
                              │ - PG_PASSWORD │
                              │ - PG_DB       │
                              │ - REDIS_URL   │
                              │ - PRODUCTION  │
                              └───────────────┘
```

## Controller Environment Variables Flow

```
┌──────────────────────────────────────────────────┐
│         Controller Pod Environment               │
├──────────────────────────────────────────────────┤
│  POSTGRES_HOST=postgres.db.svc.cluster.local    │
│  POSTGRES_PORT=5432                              │
│  POSTGRES_USER=scanuser                          │
│  POSTGRES_PASSWORD=********                      │
│  POSTGRES_DASHBOARD_DATABASE=dashboard_db        │
│  POSTGRES_CACHE_DATABASE=cache_db                │
└──────────────────┬───────────────────────────────┘
                   │
                   │ Read by internal.GetPostgres*()
                   │
                   ▼
┌────────────────────────────────────────────────────┐
│         helpers.GetScanSecret()                    │
│         Creates Secret Spec                        │
├────────────────────────────────────────────────────┤
│  stringData:                                       │
│    DATABASE_URL: postgresql+asyncpg://...         │
│    PG_HOST: postgres.db.svc.cluster.local         │
│    PG_PORT: 5432                                   │
│    PG_USER: scanuser                               │
│    PG_PASSWORD: ********                           │
│    PG_DB: dashboard_db                             │
└──────────────────┬─────────────────────────────────┘
                   │
                   │ Create Secret in K8s
                   │
                   ▼
┌────────────────────────────────────────────────────┐
│         Kubernetes Secret                          │
│    scan-secret-<scaninstance-name>                 │
├────────────────────────────────────────────────────┤
│  type: Opaque                                      │
│  data: (base64 encoded)                            │
│    DATABASE_URL: cG9zdGdyZXNxbCsuLi4=              │
│    PG_HOST: cG9zdGdyZXMuZGIuc3ZjLmNsdXN0ZXIubG9j  │
│    ... (all 6 fields)                              │
└──────────────────┬─────────────────────────────────┘
                   │
                   │ Referenced by Job via envFrom
                   │
                   ▼
┌────────────────────────────────────────────────────┐
│         Scan Job Pod                               │
│    (enhanced-soc-analysis scanner)                 │
├────────────────────────────────────────────────────┤
│  Environment Variables (decoded from Secret):      │
│    DATABASE_URL=postgresql+asyncpg://...           │
│    PG_HOST=postgres.db.svc.cluster.local           │
│    PG_PORT=5432                                    │
│    PG_USER=scanuser                                │
│    PG_PASSWORD=********                            │
│    PG_DB=dashboard_db                              │
│                                                    │
│  Plus additional from controller:                  │
│    REDIS_URL=redis://redis-svc-...                 │
│    PRODUCTION=true                                 │
└────────────────────────────────────────────────────┘
```

## Cleanup Flow

```
┌─────────────────────────────────────────┐
│   kubectl delete scaninstance <name>   │
└─────────────────┬───────────────────────┘
                  │
                  ▼
     ┌────────────────────────────┐
     │  Finalizer Triggered       │
     │  cleanupScanInstanceRes... │
     └────────┬───────────────────┘
              │
    ┌─────────┴──────────┬─────────────┬──────────────┐
    │                    │             │              │
    ▼                    ▼             ▼              ▼
┌──────────┐      ┌──────────┐  ┌─────────┐   ┌──────────┐
│ Delete   │      │ Delete   │  │ Delete  │   │ Delete   │
│ PreScan  │      │ ConfigMap│  │ Secret  │   │ Scan Job │
│ Job      │      │          │  │         │   │          │
└──────────┘      └──────────┘  └─────────┘   └──────────┘
                                      │
                                      │ Also cleaned via
                                      │ owner reference
                                      ▼
                              ┌───────────────┐
                              │   Resources   │
                              │   Deleted     │
                              └───────────────┘
```

## Error Handling Flow

```
Secret Creation Failed
        │
        ▼
┌─────────────────────────────┐
│ Update ScanInstance:        │
│ - Condition: Scanning/Failed│
│ - Status: ScanFailed        │
│ - Reason: Error message     │
└─────────────┬───────────────┘
              │
              ▼
    ┌──────────────────┐
    │ Generate Event   │
    │ EventType:       │
    │   Warning        │
    │ Reason:          │
    │   ScanSecretFail │
    └──────────────────┘
              │
              ▼
    ┌──────────────────┐
    │ Log Error        │
    │ "error occurred  │
    │  while creating  │
    │  scan secret"    │
    └──────────────────┘
              │
              ▼
    ┌──────────────────┐
    │ Return Error     │
    │ Stop             │
    │ Reconciliation   │
    └──────────────────┘
```

---

_This visual diagram shows the complete flow from ScanInstance creation to scan job execution with PostgreSQL secret integration._
