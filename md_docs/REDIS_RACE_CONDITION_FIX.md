# Redis Deployment Race Condition Fix

## Problem

When the Redis deployment and service are created, Kubernetes events trigger subsequent reconciliations. Due to the asynchronous nature of the Kubernetes API and controller cache, a race condition can occur:

1. **First Reconciliation**: Redis deployment created successfully
2. **Event Recorded**: "RedisDeploymentCreated" event is emitted
3. **Cache Not Yet Updated**: Controller cache hasn't been updated with the new resource
4. **Second Reconciliation Triggered**: By the event or deployment status update
5. **GET Returns NotFound**: The GET call at line 395 returns `nil` because cache is stale
6. **CREATE Fails**: The CREATE call at line 283 fails with "AlreadyExists" error

## Error Manifestation

```
{"controller":"ScanInstance","level":"info","msg":"Created Redis service: redis-svc-test-si"}
...
{"controller":"ScanInstance","error":"error creating redis service: services \"redis-svc-test-si\" already exists","level":"error"}
```

The service WAS created successfully, but a subsequent reconciliation attempted to create it again before the cache was updated.

## Root Cause

The idempotency check in `createRedisService` and `createRedisDeployment` performs a GET before CREATE:

```go
// Line 270-280: Check if service already exists
existingSvc := &corev1.Service{}
if err := r.Client.Get(ctx, ..., existingSvc); err == nil {
    return existingSvc, nil  // Already exists, return it
}

// Line 283: Create the service
if err := r.Client.Create(ctx, svc); err != nil {
    return nil, err  // This fails with AlreadyExists!
}
```

**Problem**: Between the GET (returns NotFound due to stale cache) and CREATE (resource now exists), another reconciliation or the actual resource creation completed.

## Solution

Add explicit handling for `AlreadyExists` error during CREATE and fetch the existing resource:

### For Redis Service

```go
// Create the service
if err := r.Client.Create(ctx, svc); err != nil {
    // If service already exists, fetch and return it (race condition handling)
    if apierrors.IsAlreadyExists(err) {
        if err := r.Client.Get(ctx, types.NamespacedName{
            Namespace: svc.Namespace,
            Name:      svc.Name,
        }, existingSvc); err != nil {
            return nil, fmt.Errorf("error fetching existing redis service after AlreadyExists: %w", err)
        }
        return existingSvc, nil
    }
    
    // Other errors are real failures
    r.Recorder.Eventf(scanInstance, corev1.EventTypeWarning, "RedisServiceCreateFailed",
        "Redis service creation failed for ScanInstance: %s", scanInstance.Name)
    return nil, fmt.Errorf("error creating redis service: %w", err)
}
```

### For Redis Deployment

Same pattern applied to deployment creation (lines 196-217).

## How It Works

1. **Normal Path**: GET returns NotFound → CREATE succeeds → return new resource
2. **Race Condition Path**: GET returns NotFound → CREATE fails with AlreadyExists → GET again → return existing resource
3. **Real Error Path**: GET returns NotFound → CREATE fails with other error → return error

## Benefits

1. **Idempotent**: Multiple reconciliations are safe
2. **No Spurious Failures**: AlreadyExists is treated as success, not failure
3. **Correct State**: Controller always returns the actual resource
4. **Event Cleanup**: No misleading "CreateFailed" events for race conditions

## Testing

### Before Fix
```bash
# Create ScanInstance
kubectl apply -f scaninstance.yaml

# Logs show:
# ✅ "Created Redis service: redis-svc-test-si"
# ❌ "error creating redis service: services \"redis-svc-test-si\" already exists"
# ❌ "ScanInstance status updated to: Failed"
```

### After Fix
```bash
# Create ScanInstance
kubectl apply -f scaninstance.yaml

# Logs show:
# ✅ "Created Redis service: redis-svc-test-si"
# ✅ "Redis deployment is ready"
# ✅ "Scan job started"
# (No AlreadyExists error)
```

## Related Issues

This same race condition pattern can occur for:
- ✅ Redis Deployment (fixed)
- ✅ Redis Service (fixed)
- Jobs (already handled by job creation logic)
- ConfigMaps (already handled by configmap creation logic)

## Kubernetes Controller Best Practice

This is a common pattern in Kubernetes controllers. The standard approach is:

```go
// Try to create
if err := client.Create(ctx, resource); err != nil {
    if apierrors.IsAlreadyExists(err) {
        // Fetch existing resource
        existing := &ResourceType{}
        if err := client.Get(ctx, key, existing); err != nil {
            return err
        }
        return existing
    }
    return err  // Real error
}
```

This handles the race between:
- Multiple reconciliations of the same resource
- Cache propagation delays
- API server vs cache inconsistencies

## Files Modified

- **controllers/scaninstance/redis_helper.go**
  - `createRedisDeployment()`: Added AlreadyExists handling (lines 196-217)
  - `createRedisService()`: Added AlreadyExists handling (lines 282-300)

## Verification

After deploying the fix:

```bash
# Watch ScanInstance status
kubectl get scaninstance test-si -w

# Watch controller logs
kubectl logs -f deployment/threat-scanning-controller | grep -i redis

# Expected flow (no errors):
# 1. "Created Redis deployment"
# 2. "Created Redis service"
# 3. "Redis deployment is ready"
# 4. No "AlreadyExists" errors
```

## Additional Notes

- **Cache Delays**: Kubernetes controller-runtime caches resources. Updates may not be immediately visible.
- **Event-Driven Reconciliation**: Every event (create, update, status change) can trigger reconciliation.
- **Idempotency is Critical**: Controllers must handle being called multiple times for the same resource.
- **AlreadyExists ≠ Error**: For idempotent operations, AlreadyExists should be treated as success.

## Prevention

To prevent similar issues in the future:

1. **Always check for AlreadyExists** when creating resources
2. **Fetch and return existing resource** on AlreadyExists
3. **Use controller-runtime's CreateOrUpdate** for resources that might need updates
4. **Test with rapid reconciliations** to expose race conditions

## Related Documentation

- Kubernetes Controller Patterns: https://kubernetes.io/docs/concepts/architecture/controller/
- controller-runtime Best Practices: https://github.com/kubernetes-sigs/controller-runtime
