# CronJob API Version Fix

## Issue

The controller was failing to start with the following error:

```
ERROR controller-runtime.source.EventHandler if kind is a CRD, it should be installed before calling Start
{"kind": "CronJob.batch", "error": "no matches for kind \"CronJob\" in version \"batch/v1beta1\""}
```

## Root Cause

The code was using `batch/v1beta1` API for CronJobs, which is deprecated and removed in Kubernetes 1.25+.

The CronJob API graduation timeline:
- **v1beta1** (deprecated): Removed in Kubernetes 1.25
- **v1** (stable): Available since Kubernetes 1.21, default since 1.25

Since we're using Kubernetes 1.29 (`k8s.io/api v0.29.0`), we need to use `batch/v1`.

## Solution

Changed all CronJob references from `batch/v1beta1` to `batch/v1`.

### Files Modified

1. **pkg/helpers/job_helper.go**
   - Removed: `import batchv1beta1 "k8s.io/api/batch/v1beta1"`
   - Changed: `func GetTargetPollerCronJob(...) (*batchv1beta1.CronJob, error)` 
   - To: `func GetTargetPollerCronJob(...) (*batchv1.CronJob, error)`
   - Changed: `&batchv1beta1.CronJob{}` → `&batchv1.CronJob{}`
   - Changed: `batchv1beta1.CronJobSpec` → `batchv1.CronJobSpec`
   - Changed: `batchv1beta1.JobTemplateSpec` → `batchv1.JobTemplateSpec`

2. **controllers/target/controller.go**
   - Removed: `import batchv1beta1 "k8s.io/api/batch/v1beta1"`
   - Changed: `Watches(&batchv1beta1.CronJob{}, ...)` 
   - To: `Watches(&batchv1.CronJob{}, ...)`

3. **controllers/target/controller_helper.go**
   - Removed: `import batchv1beta1 "k8s.io/api/batch/v1beta1"`
   - Changed: `cronJobs := &batchv1beta1.CronJobList{}`
   - To: `cronJobs := &batchv1.CronJobList{}`

4. **config/rbac/role.yaml**
   - Added CronJob permissions under `batch` API group (v1)

## API Differences

The `batch/v1` CronJob API is fully compatible with `batch/v1beta1` for our use case. The main differences are:

| Field | v1beta1 | v1 |
|-------|---------|-----|
| `spec.schedule` | ✅ Same | ✅ Same |
| `spec.jobTemplate` | ✅ Same | ✅ Same |
| `spec.successfulJobsHistoryLimit` | ✅ Same | ✅ Same |
| `spec.failedJobsHistoryLimit` | ✅ Same | ✅ Same |
| `spec.suspend` | ✅ Same | ✅ Same |
| `spec.concurrencyPolicy` | ✅ Same | ✅ Same |
| `spec.startingDeadlineSeconds` | ✅ Same | ✅ Same |

Our implementation only uses the basic fields, so the migration is seamless.

## Verification

```bash
# Verify no v1beta1 references remain
grep -r "batchv1beta1" --include="*.go" .
# Output: (empty - no references found)

# Build succeeds
go build -o bin/manager cmd/manager/main.go
# Output: Success

# Controller starts without errors
./bin/manager
# Output: No CronJob API errors
```

## Compatibility Matrix

| Kubernetes Version | batch/v1beta1 | batch/v1 |
|-------------------|---------------|----------|
| 1.20 and earlier | ✅ Available | ❌ Not available |
| 1.21 - 1.24 | ✅ Available (deprecated) | ✅ Available |
| 1.25+ | ❌ Removed | ✅ Available (default) |

**Our target**: Kubernetes 1.29 → Must use `batch/v1` ✅

## Testing

To test the fix:

1. Start the controller:
   ```bash
   make run
   ```

2. Create a target:
   ```bash
   kubectl apply -f config/samples/threatscanning_v1_target_nfs.yaml
   ```

3. Verify CronJob is created:
   ```bash
   kubectl get cronjobs -n threat-scanning-system
   ```

Expected: CronJob created successfully with `batch/v1` API.

## References

- [Kubernetes CronJob Documentation](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/)
- [API Deprecation Guide](https://kubernetes.io/docs/reference/using-api/deprecation-guide/)
- [CronJob v1 API Reference](https://kubernetes.io/docs/reference/kubernetes-api/workload-resources/cron-job-v1/)

## Status

✅ **Fixed**: All references updated to `batch/v1`
✅ **Tested**: Build succeeds
✅ **Verified**: No `v1beta1` references remain
