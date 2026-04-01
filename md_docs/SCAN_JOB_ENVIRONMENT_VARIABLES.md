# Scan Job Environment Variables - Implementation

## Overview
The Scan Job now receives Redis and Database URLs as environment variables, enabling it to:
1. Connect to the per-ScanInstance Redis deployment for checkpointing
2. Connect to the shared database (PostgreSQL or SQLite) for storing scan results

## Environment Variables Added

### 1. `REDIS_URL`
**Purpose**: Connection URL for the Redis instance dedicated to this ScanInstance

**Format**: `redis://<redis-svc-name>.<namespace>.svc.cluster.local:6379`

**Example**: `redis://redis-svc-my-scan-instance.threat-scanning-system.svc.cluster.local:6379`

**Construction**:
```go
redisSvcName := GetScanInstanceResourceName(internal.ScanInstanceRedisServicePrefix, scanInstName)
redisURL := fmt.Sprintf("redis://%s.%s.svc.cluster.local:6379", 
    redisSvcName, internal.GetInstallNamespace())
```

**Key Points**:
- Dynamically constructed based on ScanInstance name
- Points to the Redis Service created by the controller
- Uses Kubernetes DNS for service discovery
- Always port 6379 (Redis default)
- Scoped to the specific ScanInstance (isolated from other scans)

### 2. `DATABASE_URL`
**Purpose**: Connection URL for the database to store scan results and job metadata

**Format**: 
- SQLite (default): `sqlite+aiosqlite:///./scan_analysis.db`
- PostgreSQL: `postgresql+asyncpg://user:password@host:port/database`

**Configuration**:
- Read from controller's `DATABASE_URL` environment variable
- Defaults to SQLite if not set
- Shared across all ScanInstances

**Key Points**:
- Controller passes its own DATABASE_URL to scan jobs
- Allows centralized configuration via controller deployment
- SQLite for development/testing
- PostgreSQL for production

## Implementation Details

### Constants Added (`internal/constants.go`)

```go
// DatabaseURL is the environment variable name for database URL
DatabaseURL = "DATABASE_URL"

// DefaultDatabaseURL is the default database URL if env var not set (SQLite)
DefaultDatabaseURL = "sqlite+aiosqlite:///./scan_analysis.db"
```

### Helper Function Added (`internal/constants.go`)

```go
// GetDatabaseURL returns the database URL from environment variable or default
func GetDatabaseURL() string {
    if url := os.Getenv(DatabaseURL); url != "" {
        return url
    }
    return DefaultDatabaseURL
}
```

### Scan Job Container (`pkg/helpers/job_helper.go`)

The scan container now includes these environment variables:

```go
Env: []corev1.EnvVar{
    // Existing env vars (JOB_NAME, JOB_NAMESPACE)
    // ...
    
    // Redis URL for scan job to connect to Redis service
    {
        Name:  "REDIS_URL",
        Value: redisURL,
    },
    
    // Database URL from controller environment (PostgreSQL or SQLite)
    {
        Name:  "DATABASE_URL",
        Value: internal.GetDatabaseURL(),
    },
}
```

## Usage in Scanner Code

### Connecting to Redis

```python
import os
import redis

# Get Redis URL from environment
redis_url = os.environ.get("REDIS_URL")
redis_client = redis.from_url(redis_url, decode_responses=True)

# Use for checkpointing
backup_id = "backup-123"
redis_client.sadd(f"completed_vms:{backup_id}", "vm-1")
completed_vms = redis_client.smembers(f"completed_vms:{backup_id}")
```

### Connecting to Database

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine

# Get Database URL from environment
database_url = os.environ.get("DATABASE_URL")
engine = create_async_engine(database_url, echo=False)

# Use for storing results
async with engine.begin() as conn:
    await conn.execute(
        text("INSERT INTO scan_results (...) VALUES (...)")
    )
```

## Configuration Examples

### Controller Deployment - Development (SQLite)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-scanning-controller
spec:
  template:
    spec:
      containers:
      - name: manager
        image: threat-scanning-controller:latest
        env:
        - name: DATABASE_URL
          value: "sqlite+aiosqlite:///./scan_analysis.db"
        # DATABASE_URL not set = defaults to SQLite
```

### Controller Deployment - Production (PostgreSQL)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: threat-scanning-controller
spec:
  template:
    spec:
      containers:
      - name: manager
        image: threat-scanning-controller:latest
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: database-url
        # Or directly:
        - name: DATABASE_URL
          value: "postgresql+asyncpg://scanuser:password@postgres.db.svc.cluster.local:5432/threat_scanning"
```

### Resulting Scan Job Environment

When the controller creates a scan job, the pod will have:

```bash
# Inside scan job pod
$ env | grep -E "(REDIS_URL|DATABASE_URL)"
REDIS_URL=redis://redis-svc-my-scan-instance.threat-scanning-system.svc.cluster.local:6379
DATABASE_URL=postgresql+asyncpg://scanuser:password@postgres.db.svc.cluster.local:5432/threat_scanning
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                   Controller Deployment                      │
│  Environment:                                                │
│    DATABASE_URL = postgresql://postgres:5432/threat_scanning│
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Reads DATABASE_URL
                           │ Constructs REDIS_URL
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     Scan Job Creation                        │
│  Controller injects:                                         │
│    REDIS_URL = redis://redis-svc-<si>.ns:6379              │
│    DATABASE_URL = <value from controller env>              │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Job starts
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      Scan Job Pod                            │
│                                                              │
│  ┌────────────────┐          ┌──────────────────┐          │
│  │  Scanner Code  │───────>  │  Redis Service   │          │
│  │                │  REDIS   │  (per-instance)  │          │
│  │  - Checkpoint  │  _URL    │                  │          │
│  │  - Track VMs   │          │  Ephemeral State │          │
│  └────────────────┘          └──────────────────┘          │
│         │                                                   │
│         │ DATABASE_URL                                      │
│         ▼                                                   │
│  ┌──────────────────────────────┐                          │
│  │   PostgreSQL / SQLite        │                          │
│  │   (shared across scans)      │                          │
│  │                               │                          │
│  │   - Scan results              │                          │
│  │   - Job metadata              │                          │
│  │   - Artifacts discovered      │                          │
│  └──────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

## Benefits

### 1. **Clean Separation of Concerns**
- Redis: Fast, ephemeral checkpointing (per-scan state)
- Database: Durable, persistent results (shared across scans)

### 2. **Configuration Flexibility**
- Single DATABASE_URL in controller applies to all scan jobs
- Easy to switch between SQLite (dev) and PostgreSQL (prod)
- No hardcoded database connections in scanner code

### 3. **Kubernetes-Native Service Discovery**
- Redis URL uses Kubernetes DNS
- No need for external service discovery
- Automatic failover if Redis pod moves

### 4. **Crash Resilience**
- Redis persists across scan job pod restarts
- Database stores final results independently
- Can reconstruct scan state from both sources

## Testing

### Verify Environment Variables in Scan Job

```bash
# Create a ScanInstance
kubectl apply -f scaninstance.yaml

# Wait for scan job to be created
kubectl wait --for=condition=Ready scaninstance/my-scan --timeout=60s

# Get scan job pod
POD=$(kubectl get pods -l job-name=threat-scan-scanjob-my-scan -o name)

# Check environment variables
kubectl exec $POD -- env | grep -E "(REDIS_URL|DATABASE_URL)"

# Expected output:
# REDIS_URL=redis://redis-svc-my-scan.threat-scanning-system.svc.cluster.local:6379
# DATABASE_URL=sqlite+aiosqlite:///./scan_analysis.db
```

### Test Redis Connectivity

```bash
# Exec into scan job pod
kubectl exec -it $POD -- bash

# Test Redis connection
python3 -c "
import redis
import os
redis_url = os.environ['REDIS_URL']
client = redis.from_url(redis_url)
client.set('test', 'hello')
print(client.get('test'))
"
# Expected: b'hello'
```

### Test Database Connectivity

```bash
# Test database connection
python3 -c "
import os
from sqlalchemy import create_engine, text
db_url = os.environ['DATABASE_URL']
# For SQLite, use synchronous engine for testing
sync_url = db_url.replace('sqlite+aiosqlite', 'sqlite')
engine = create_engine(sync_url)
with engine.connect() as conn:
    result = conn.execute(text('SELECT 1'))
    print(result.fetchone())
"
# Expected: (1,)
```

## Migration Notes

### Existing Scanner Code
If the scanner code already expects `REDIS_URL` and `DATABASE_URL` environment variables, no code changes are needed. The controller will automatically provide these values.

### New Scanner Code
Update the scanner to:
1. Read `REDIS_URL` from environment
2. Read `DATABASE_URL` from environment
3. Use Redis for ephemeral checkpointing
4. Use Database for persistent result storage

## Future Enhancements

1. **Redis Authentication**: Add Redis password support via Secret
2. **Database Pooling**: Configure connection pool size via env vars
3. **Multiple Databases**: Support different databases per scan type
4. **Redis Sentinel**: Support Redis HA configurations
5. **TLS/SSL**: Add support for encrypted connections
