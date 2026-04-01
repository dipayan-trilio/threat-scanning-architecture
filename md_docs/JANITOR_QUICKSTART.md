# Janitor CLI - Quick Reference

## Build Commands

```bash
# Build janitor binary
make build-janitor

# Build janitor Docker image
make docker-build-janitor

# Build all (manager + janitor)
make build-all
make docker-build-all
```

## Running Locally

```bash
# Dry-run cleanup of a specific completed ScanInstance
go run ./cmd/janitor/main.go --scan-instance=my-scan --status=Available --dry-run

# Cleanup a specific completed ScanInstance
go run ./cmd/janitor/main.go --scan-instance=my-scan --status=Available

# Cleanup all failed ScanInstances (periodic mode, default 3 days threshold)
go run ./cmd/janitor/main.go --status=Failed

# Cleanup failed ScanInstances with custom threshold (1 day)
go run ./cmd/janitor/main.go --status=Failed --threshold-minutes=1440

# Cleanup failed ScanInstances with custom threshold (7 days)
go run ./cmd/janitor/main.go --status=Failed --threshold-minutes=10080

# Dry-run periodic cleanup
go run ./cmd/janitor/main.go --status=Failed --dry-run
```

## Deployment

### Deploy CronJob
```bash
kubectl apply -f config/manager/janitor-cronjob.yaml
```

### Check CronJob
```bash
kubectl get cronjobs -n threat-scanning-system
kubectl get jobs -n threat-scanning-system | grep janitor
```

### View Logs
```bash
# Get janitor pod logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scan-janitor

# Follow logs
kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scan-janitor -f
```

## Testing

```bash
# Run test script
./test-janitor.sh
```

## Architecture

### On-Demand Janitor (Controller-Triggered)
```
ScanInstance Completes → Controller creates janitor Job → Janitor cleans up resources
```

Resources cleaned:
- ✅ Pre-scan Job
- ✅ Scan Job
- ✅ Redis Deployment
- ✅ Redis Service
- ✅ Scan ConfigMap
- ❌ ScanInstance (kept as audit trail)

### Periodic Janitor (CronJob)
```
Every 6 hours → CronJob runs → Janitor processes failed ScanInstances
```

Immediate cleanup (all failed ScanInstances):
- ✅ Redis Deployment
- ✅ Redis Service

Immediate cleanup (all failed ScanInstances):
- ✅ Redis Deployment
- ✅ Redis Service

Cleanup for failures older than threshold (default: 3 days / 4320 minutes):
- ✅ Pre-scan Job
- ✅ Scan Job
- ✅ Scan ConfigMap

## Environment Variables

The following environment variables can be set in the deployment:

```yaml
env:
- name: RELATED_IMAGE_JANITOR
  value: "my-registry/threat-scan-janitor:v1.0.0"
```

## Troubleshooting

### Janitor not cleaning up resources

1. Check if janitor job was created:
```bash
kubectl get jobs -n threat-scanning-system | grep janitor
```

2. Check janitor logs:
```bash
kubectl logs -n threat-scanning-system <janitor-pod-name>
```

3. Verify RBAC permissions:
```bash
kubectl auth can-i delete jobs --as=system:serviceaccount:threat-scanning-system:trilio-threat-scanning -n threat-scanning-system
```

### CronJob not running

1. Check CronJob status:
```bash
kubectl describe cronjob threat-scan-janitor -n threat-scanning-system
```

2. Manually trigger CronJob:
```bash
kubectl create job --from=cronjob/threat-scan-janitor manual-janitor-test -n threat-scanning-system
```

### Resources still present after cleanup

1. Check if resources have finalizers:
```bash
kubectl get job <job-name> -n threat-scanning-system -o yaml | grep finalizers
```

2. Verify ownership (janitor may not delete resources not owned by ScanInstance):
```bash
kubectl get job <job-name> -n threat-scanning-system -o yaml | grep ownerReferences
```

## Best Practices

1. **Monitor janitor execution** - Set up alerts for failed janitor jobs
2. **Review logs periodically** - Check for patterns in cleanup failures
3. **Test in non-production first** - Use dry-run mode to verify cleanup behavior
4. **Adjust schedule if needed** - Modify CronJob schedule based on ScanInstance creation rate
5. **Keep audit trail** - ScanInstance objects are never deleted automatically

## Integration Points

### Controller Integration
File: `controllers/scaninstance/controller_helper.go`
```go
// After scan completes
if err := r.createJanitorJob(ctx, scanInstance); err != nil {
    log.WithError(err).Warn("Failed to create janitor job")
}
```

### Helper Function
File: `pkg/helpers/job_helper.go`
```go
func GetJanitorJob(scanInstance *v1.ScanInstance) (*batchv1.Job, error)
```

### Constants
File: `internal/constants.go`
```go
const ScanInstanceJanitorJobPrefix = "threat-scan-janitor"
```
