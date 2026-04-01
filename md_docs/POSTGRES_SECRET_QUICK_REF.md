# PostgreSQL Secret Integration - Quick Reference

## Summary of Changes

The threat-scanning-architecture controller has been updated to create a Kubernetes Secret with PostgreSQL credentials before creating scan jobs. The secret is mounted via `envFrom` in the scan job container.

## Files Modified

### 1. `/internal/constants.go`
**Added:**
- Constants for PostgreSQL environment variables
- `ScanInstanceScanSecretPrefix` constant
- Helper functions: `GetPostgresHost()`, `GetPostgresPort()`, `GetPostgresUser()`, `GetPostgresPassword()`, `GetPostgresDashboardDatabase()`, `GetPostgresCacheDatabase()`

**Key additions:**
```go
// PostgreSQL environment variables
PostgresHost              = "POSTGRES_HOST"
PostgresPort              = "POSTGRES_PORT"
PostgresUser              = "POSTGRES_USER"
PostgresPassword          = "POSTGRES_PASSWORD"
PostgresDashboardDatabase = "POSTGRES_DASHBOARD_DATABASE"
PostgresCacheDatabase     = "POSTGRES_CACHE_DATABASE"
DefaultPostgresPort       = "5432"

// Secret prefix
ScanInstanceScanSecretPrefix = "scan-secret"
```

### 2. `/pkg/helpers/job_helper.go`
**Added:**
- `GetScanSecret()` function to create secret with PostgreSQL credentials

**Modified:**
- `GetScanJob()` signature now accepts `secretName` parameter
- Scan container now uses `envFrom` to load environment variables from secret
- Removed hardcoded `DATABASE_URL` from container env vars

**Key changes:**
```go
// New function
func GetScanSecret(scanInstance *v1.ScanInstance) (*corev1.Secret, error)

// Modified signature
func GetScanJob(ctx context.Context, cl client.Client, scanInstance *v1.ScanInstance, secretName string) (*batchv1.Job, error)

// Container now has envFrom
EnvFrom: []corev1.EnvFromSource{
    {
        SecretRef: &corev1.SecretEnvSource{
            LocalObjectReference: corev1.LocalObjectReference{
                Name: secretName,
            },
        },
    },
},
```

### 3. `/controllers/scaninstance/controller_helper.go`
**Modified:**
- `cleanupScanInstanceResources()` now deletes scan secret
- `createScanJob()` signature now accepts `secretName` parameter
- `reconcileScanPhase()` creates secret before creating scan job

**Key changes:**
```go
// Secret creation in reconcileScanPhase()
scanSecret, err := helpers.GetScanSecret(scanInstance)
// Set owner reference
ctrl.SetControllerReference(scanInstance, scanSecret, r.Scheme)
// Create secret
r.Client.Create(ctx, scanSecret)
// Create job with secret name
newScanJob, err := r.createScanJob(ctx, scanInstance, scanSecret.Name)
```

## Environment Variables Required

Set these environment variables in the controller deployment:

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

## Secret Structure

The created secret contains:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: scan-secret-<scaninstance-name>
  namespace: threat-scanning-system
  ownerReferences: [...]
type: Opaque
stringData:
  DATABASE_URL: "postgresql+asyncpg://<user>:<password>@<host>:<port>/<cache-db>"
  PG_HOST: "<host>"
  PG_PORT: "<port>"
  PG_DB: "<dashboard-db>"
  PG_PASSWORD: "<password>"
  PG_USER: "<user>"
```

## Reconciliation Order

1. PreScan job completes
2. Redis deployment becomes ready
3. **ConfigMap created** (vm_artifacts_configuration.json)
4. **Secret created** (PostgreSQL credentials) ← NEW
5. **Scan job created** (with envFrom: secretRef) ← UPDATED
6. Scan job runs with database credentials loaded from secret

## Testing Commands

```bash
# Check controller has environment variables
kubectl get deployment threat-scanning-controller -n threat-scanning-system -o yaml | grep -A 20 "env:"

# Create a scan instance
kubectl apply -f scaninstance-sample.yaml

# Check secret was created
kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system

# View secret data (base64 encoded)
kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system -o yaml

# Decode secret data
kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system -o jsonpath='{.data.DATABASE_URL}' | base64 -d

# Check scan job has envFrom
kubectl get job threat-scan-scanjob-<scaninstance-name> -n threat-scanning-system -o yaml | grep -A 10 "envFrom"

# Verify environment variables in pod
kubectl get pod -l job-name=threat-scan-scanjob-<scaninstance-name> -n threat-scanning-system
kubectl exec -it <pod-name> -n threat-scanning-system -- env | grep -E "DATABASE_URL|PG_"

# Check cleanup
kubectl delete scaninstance <scaninstance-name>
kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system
# Should return: Error from server (NotFound)
```

## RBAC Requirements

Ensure the controller's ServiceAccount has permissions for secrets:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: threat-scanning-controller
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

## Troubleshooting

### Secret not created
1. Check controller logs:
   ```bash
   kubectl logs -f deployment/threat-scanning-controller -n threat-scanning-system
   ```
2. Verify environment variables are set in controller
3. Check RBAC permissions for secrets

### Scan job fails with database connection error
1. Verify secret contains correct values:
   ```bash
   kubectl get secret scan-secret-<name> -o yaml
   ```
2. Check PostgreSQL is accessible from the cluster
3. Verify credentials are correct

### Secret not cleaned up after deletion
1. Check owner references:
   ```bash
   kubectl get secret scan-secret-<name> -o yaml | grep -A 5 ownerReferences
   ```
2. Check finalizer logs for cleanup errors
3. Manually delete if needed:
   ```bash
   kubectl delete secret scan-secret-<name> -n threat-scanning-system
   ```

## Build Verification

All changes compile successfully:

```bash
cd /path/to/threat-scanning-architecture

# Build internal package
go build -o /dev/null ./internal/...

# Build helpers package
go build -o /dev/null ./pkg/helpers/...

# Build controllers
go build -o /dev/null ./controllers/scaninstance/...
go build -o /dev/null ./controllers/target/...

# All builds should complete with exit code 0
```

## Related Files

- Full documentation: `POSTGRES_SECRET_INTEGRATION.md`
- Controller README: `CONTROLLER_README.md`
- ScanInstance types: `api/v1/scaninstance_types.go`
- Environment variables: `ENVIRONMENT_VARIABLES.md`
