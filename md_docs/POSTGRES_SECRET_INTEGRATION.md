# PostgreSQL Secret Integration for ScanInstance

## Overview

This document describes the integration of PostgreSQL database credentials as a Kubernetes Secret for ScanInstance scan jobs.

## Changes Made

### 1. New Environment Variables

The controller now accepts the following PostgreSQL environment variables:

- `POSTGRES_HOST` - PostgreSQL server hostname
- `POSTGRES_PORT` - PostgreSQL server port (default: 5432)
- `POSTGRES_USER` - PostgreSQL username
- `POSTGRES_PASSWORD` - PostgreSQL password
- `POSTGRES_DASHBOARD_DATABASE` - Dashboard database name
- `POSTGRES_CACHE_DATABASE` - Cache database name

### 2. Secret Creation

Before creating a scan job, the controller creates a Kubernetes Secret with a 1:1 relationship to the scan job. The secret contains:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: scan-secret-<scaninstance-name>
  namespace: threat-scanning-system
  ownerReferences:
    - apiVersion: threatscanning.trilio.io/v1
      kind: ScanInstance
      name: <scaninstance-name>
      controller: true
      blockOwnerDeletion: true
type: Opaque
stringData:
  DATABASE_URL: "postgresql+asyncpg://<user>:<password>@<host>:<port>/<cache-db>"
  PG_HOST: "<host>"
  PG_PORT: "<port>"
  PG_DB: "<dashboard-db>"
  PG_PASSWORD: "<password>"
  PG_USER: "<user>"
```

### 3. Scan Job Integration

The scan job now uses `envFrom` to load all environment variables from the secret:

```yaml
apiVersion: batch/v1
kind: Job
spec:
  template:
    spec:
      containers:
      - name: scanner
        envFrom:
        - secretRef:
            name: scan-secret-<scaninstance-name>
        env:
        - name: JOB_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['job-name']
        - name: JOB_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: PRODUCTION
          value: "true"
        - name: REDIS_URL
          value: "redis://redis-svc-<scaninstance-name>.<namespace>.svc.cluster.local:6379"
```

### 4. Resource Lifecycle

- **Secret Creation**: Created after ConfigMap creation, before Job creation
- **Owner Reference**: Secret has `ownerReferences` pointing to ScanInstance (same as ConfigMap)
- **Cleanup**: Secret is automatically deleted when ScanInstance is deleted (via owner reference)
- **Finalizer Cleanup**: Secret is also explicitly deleted by the controller's finalizer for immediate cleanup

## Implementation Details

### Files Modified

1. **internal/constants.go**
   - Added PostgreSQL environment variable constants
   - Added `ScanInstanceScanSecretPrefix` constant
   - Added helper functions: `GetPostgresHost()`, `GetPostgresPort()`, `GetPostgresUser()`, `GetPostgresPassword()`, `GetPostgresDashboardDatabase()`, `GetPostgresCacheDatabase()`

2. **pkg/helpers/job_helper.go**
   - Added `GetScanSecret()` function to create the secret spec
   - Modified `GetScanJob()` to accept `secretName` parameter
   - Updated scan container to use `envFrom` with secret reference
   - Removed hardcoded `DATABASE_URL` from container env vars (now loaded from secret)

3. **controllers/scaninstance/controller_helper.go**
   - Updated `cleanupScanInstanceResources()` to delete scan secret
   - Modified `createScanJob()` to accept `secretName` parameter
   - Updated `reconcileScanPhase()` to create secret before creating scan job
   - Added events and logging for secret creation

### Reconciliation Flow

```
PreScan Completed
    ↓
Redis Deployment Ready
    ↓
Create ConfigMap (vm_artifacts_configuration.json)
    ↓
Create Secret (PostgreSQL credentials)
    ↓
Create Scan Job (with envFrom: secretRef)
    ↓
Monitor Scan Job Status
```

### Idempotency

- Secret creation uses `IsAlreadyExists` check
- If secret already exists, reconciliation continues without error
- Controller ensures secret exists before creating scan job

### Error Handling

If secret creation fails:
1. ScanInstance condition is updated to `Scanning/Failed`
2. ScanInstance status is updated to `ScanFailed`
3. Error is recorded in events
4. Error is logged

### Security Considerations

- Secret type: `Opaque`
- Secret contains sensitive database credentials
- Secret is mounted as environment variables (not as files)
- Secret follows 1:1 relationship with scan job
- Secret is cleaned up when ScanInstance is deleted
- RBAC: Controller needs `secrets` create/delete permissions

## Testing

### Prerequisites

Set the following environment variables in the controller deployment:

```yaml
env:
- name: POSTGRES_HOST
  value: "postgres.database.svc.cluster.local"
- name: POSTGRES_PORT
  value: "5432"  # Optional, defaults to 5432
- name: POSTGRES_USER
  value: "scanuser"
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: postgres-credentials
      key: password
- name: POSTGRES_DASHBOARD_DATABASE
  value: "dashboard_db"
- name: POSTGRES_CACHE_DATABASE
  value: "cache_db"
```

### Verification Steps

1. **Create a ScanInstance**:
   ```bash
   kubectl apply -f scaninstance-sample.yaml
   ```

2. **Check Secret Creation**:
   ```bash
   kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system -o yaml
   ```

3. **Verify Secret Data**:
   ```bash
   kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system -o jsonpath='{.data}' | base64 -d
   ```

4. **Check Scan Job**:
   ```bash
   kubectl get job threat-scan-scanjob-<scaninstance-name> -n threat-scanning-system -o yaml
   ```
   
   Verify `envFrom` block contains secret reference.

5. **Check Scan Job Pod**:
   ```bash
   kubectl get pod -l job-name=threat-scan-scanjob-<scaninstance-name> -n threat-scanning-system
   kubectl exec -it <pod-name> -n threat-scanning-system -- env | grep PG_
   ```

6. **Check Cleanup**:
   ```bash
   kubectl delete scaninstance <scaninstance-name>
   kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system
   # Should return "NotFound"
   ```

## Backward Compatibility

This change maintains backward compatibility:
- If PostgreSQL environment variables are not set, the secret will contain empty values
- Scan job will still be created and can fall back to other database configurations
- No breaking changes to existing ScanInstance CRD schema

## Future Enhancements

1. **Secret Rotation**: Implement secret rotation without recreating scan jobs
2. **Secret Validation**: Validate PostgreSQL connection before creating scan job
3. **Multi-Database Support**: Support multiple database backends per scan job
4. **Secret Encryption**: Use encrypted secrets or external secret management (Vault, etc.)

## Related Documentation

- [Controller README](CONTROLLER_README.md)
- [ScanInstance Controller](SCANINSTANCE_CONTROLLER.md)
- [Environment Variables](ENVIRONMENT_VARIABLES.md)
