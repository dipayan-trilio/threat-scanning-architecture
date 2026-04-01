# Redis Deployment Per ScanInstance - Implementation Summary

## Overview
This implementation adds a dedicated Redis Deployment and Service for each ScanInstance to enable stateful checkpointing across scan job restarts. The Redis infrastructure is created after PreScan completes and before the main Scan Job starts.

## Changes Made

### 1. API Types (`api/v1/`)

#### `scaninstance_types.go`
- **Added new phase**: `RedisDeployment` to the `ScanPhase` enum
  - Enum values: `Queued`, `PreScan`, `RedisDeployment`, `Scanning`
  
#### `target_types.go`
- **Added new status**: `Ready` to the `Status` enum
  - Enum values: `InProgress`, `Available`, `Unavailable`, `Completed`, `Failed`, `Ready`

### 2. Internal Constants (`internal/constants.go`)
- **Added**: `ScanInstanceRedisDeployPrefix = "redis-deploy"`
- **Added**: `ScanInstanceRedisServicePrefix = "redis-svc"`
- **Added**: `RelatedImageRedis = "RELATED_IMAGE_REDIS"` - Environment variable name for Redis image
- **Added**: `DefaultRedisImage = "redis:7-alpine"` - Default Redis image if env var not set
- **Added**: `GetRedisImage()` - Helper function to get Redis image from env var or default

### 3. New Redis Helper File (`controllers/scaninstance/redis_helper.go`)
Created comprehensive Redis management functions:

#### Functions:
- `getRedisDeployment()` - Retrieves existing Redis deployment for a ScanInstance
- `getRedisService()` - Retrieves existing Redis service for a ScanInstance
- `createRedisDeployment()` - Creates Redis deployment with:
  - Image: `redis:7-alpine`
  - Resources: 512Mi/1Gi memory, 250m/500m CPU
  - Persistence: EmptyDir volume at `/data`
  - Redis config: maxmemory 1GB, AOF persistence enabled
  - Liveness and Readiness probes
  - Owner reference to ScanInstance (auto-cleanup)
  - Labels matching scan job pattern
- `createRedisService()` - Creates ClusterIP service exposing Redis port 6379
  - Owner reference to ScanInstance
  - Selector matches Redis deployment
- `isRedisDeploymentReady()` - Checks if Redis deployment has at least 1 ready replica

#### Naming Convention:
- Deployment: `redis-deploy-<scaninstance-name>`
- Service: `redis-svc-<scaninstance-name>`

### 4. Controller Helper Updates (`controllers/scaninstance/controller_helper.go`)

#### Imports:
- Added `time` package for RequeueAfter
- Added `appsv1` for Deployment resources

#### New Function: `reconcileRedisDeployment()`
Handles the Redis deployment lifecycle:
1. Checks if RedisDeployment phase is Ready (idempotency)
2. Checks if RedisDeployment phase has Failed (terminal state)
3. Updates condition to `RedisDeployment/InProgress` if not set
4. Gets or creates Redis Deployment
5. Gets or creates Redis Service
6. Checks deployment readiness using `isRedisDeploymentReady()`
7. Updates condition to `RedisDeployment/Ready` when deployment is available
8. Requeues after 5 seconds if deployment not ready yet

#### Updated Function: `reconcileScanPhase()`
Modified to check for Redis deployment completion before creating ConfigMap and Scan Job:
```go
// Check if Redis deployment phase is completed (idempotency)
if !scanInstance.HasCondition(v1.RedisDeployment, v1.Ready) {
    return r.reconcileRedisDeployment(ctx, scanInstance, originalScanInstance)
}
// Redis is ready, proceed to create configmap and scan job
```

#### Updated Function: `cleanupScanInstanceResources()`
Added cleanup for Redis resources:
- Deletes Redis Deployment (with Background propagation)
- Deletes Redis Service

#### Updated Function: `cleanupScanInstanceJobs()`
Added cleanup for Redis resources on successful scan completion:
- Deletes Redis Deployment (with Foreground propagation)
- Deletes Redis Service

### 5. Main Controller Updates (`controllers/scaninstance/controller.go`)

#### Imports:
- Added `appsv1` for Deployment watching

#### RBAC Markers:
- Added: `+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete`
- Added: `+kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete`

#### Event Filtering:
Updated `createFunction`, `deleteFunction`, and `updateFunction` predicates to:
- Filter Deployment events (only process if managed by threat-scanning-controller)
- Reconcile on Deployment status changes (ReadyReplicas, AvailableReplicas, Conditions)

#### New Handler: `deploymentHandler()`
Maps Deployment events to ScanInstance reconciliation requests:
- Filters by `app.kubernetes.io/managed-by` label
- Extracts ScanInstance name from `trilio.io/scaninstance-name` label
- Returns reconcile request for the owning ScanInstance

#### Updated `SetupWithManager()`:
- Added watcher for Deployments using `deploymentHandler`

### 6. CRD Manifests
Auto-generated manifests updated via `make manifests`:
- `config/crd/bases/threatscanning.trilio.io_scaninstances.yaml`
  - Added `RedisDeployment` to phase enum
  - Added `Ready` to status enum

## Execution Flow

### Successful Flow:
1. **PreScan Phase**: Job completes successfully → `PreScan/Completed`
2. **Redis Deployment Phase**:
   - Condition updated to `RedisDeployment/InProgress`
   - Status remains `InProgress`
   - Redis Deployment created
   - Redis Service created
   - Controller watches Deployment status
   - When deployment becomes Available, condition updated to `RedisDeployment/Ready`
   - Status remains `InProgress`
3. **Scanning Phase**:
   - ConfigMap created with VM info
   - Scan Job created (can now connect to Redis at `redis-svc-<si-name>:6379`)
   - Scan Job uses Redis for checkpointing VM completion
   - If Scan Job pod crashes, Kubernetes restarts it
   - Job resumes from Redis checkpoint (skips completed VMs)
   - On Scan Job success → `Scanning/Completed`, status → `Completed`
4. **Cleanup**: Resources are NOT automatically cleaned up
   - All resources remain (PreScan Job, Redis Deployment, Redis Service, ConfigMap, Scan Job)
   - A separate Janitor service will handle cleanup of completed ScanInstances
   - Resources are only cleaned up when ScanInstance is deleted (via finalizer)

### Failure Scenarios:
- **Redis creation fails**: 
  - Condition: `RedisDeployment/Failed`
  - Overall Status: `Failed`
  - ScanInstance moves to terminal Failed state
  - Reconciliation stops
  - Resources remain for debugging
- **Redis deployment not ready**: Controller requeues every 5 seconds until ready
- **Scan Job fails**: 
  - All resources (Redis Deployment/Service, Jobs, ConfigMap) kept for debugging
  - Only cleaned up when ScanInstance is deleted via finalizer

## Idempotency Guarantees
- All resource creation checks for existing resources before creating
- All status/condition updates check current state before updating
- Controller can safely restart at any point without duplicating resources
- Each phase has terminal state checks to prevent re-execution

## Ownership and Lifecycle
- Redis Deployment has OwnerReference to ScanInstance
- Redis Service has OwnerReference to ScanInstance
- Kubernetes garbage collection automatically deletes Redis resources when ScanInstance is deleted
- **Successful scan completion does NOT trigger automatic cleanup**
- All resources (jobs, Redis, configmap) remain after completion for debugging/analysis
- A separate Janitor service will be responsible for cleaning up completed ScanInstances
- Manual cleanup occurs when ScanInstance CR is deleted (finalizer runs `cleanupScanInstanceResources`)

## Redis Configuration
- **Image**: Configurable via `RELATED_IMAGE_REDIS` environment variable
  - Default: `redis:7-alpine` (lightweight, production-ready)
  - Set via: `internal.GetRedisImage()` helper function
- **Memory**: 1GB limit with LRU eviction policy
- **Persistence**: AOF enabled with `everysec` fsync
- **Probes**: Liveness and Readiness using `redis-cli ping`
- **Storage**: EmptyDir (ephemeral but survives pod restarts in same node)

## Testing Considerations
1. Test Redis deployment creation and readiness detection
2. Test scan job connecting to Redis service
3. Test scan job crash and restart (verify checkpointing works)
4. Test resources remain after successful completion
5. Test cleanup on ScanInstance deletion (finalizer)
6. Test multiple concurrent ScanInstances (each gets isolated Redis)
7. Verify Janitor service can identify and clean up completed ScanInstances

## Future Enhancements
- Consider PersistentVolumeClaim for Redis data if node-level persistence is needed
- Add Redis resource requests/limits configuration via ScanInstance spec
- Add Redis metrics collection for monitoring
- Add Redis connection testing in scan job before starting scan
