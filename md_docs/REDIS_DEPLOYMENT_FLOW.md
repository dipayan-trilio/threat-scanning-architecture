# ScanInstance Controller Flow with Redis Deployment

## Phase Progression

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          ScanInstance Created                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase: Queued                                                           │
│  Status: Queued                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase: PreScan                                                          │
│  Condition: PreScan/InProgress                                           │
│  Status: InProgress                                                      │
│  Resources: PreScan Job created                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                   ✅ Success               ❌ Failure
                        │                       │
                        ▼                       ▼
            ┌────────────────────┐    ┌────────────────────┐
            │ PreScan/Completed  │    │  PreScan/Failed    │
            └────────────────────┘    │  Status: Failed    │
                        │             │  (Terminal State)   │
                        │             └────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase: RedisDeployment                                        ⭐ NEW   │
│  Condition: RedisDeployment/InProgress                                  │
│  Status: InProgress                                                      │
│  Resources: Redis Deployment + Service created                          │
│    - Deployment: redis-deploy-<scaninstance-name>                       │
│    - Service: redis-svc-<scaninstance-name>                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                ✅ Ready                       ❌ Failure
                    │                               │
                    ▼                               ▼
    ┌────────────────────────────┐      ┌─────────────────────────┐
    │ RedisDeployment/Ready      │      │ RedisDeployment/Failed  │
    │ Status: InProgress         │      │ Status: Failed          │
    └────────────────────────────┘      │ (Terminal State)        │
                    │                   └─────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase: Scanning                                                         │
│  Condition: Scanning/InProgress                                          │
│  Status: InProgress                                                      │
│  Resources: ConfigMap + Scan Job created                                │
│    - Scan Job connects to redis-svc-<scaninstance-name>:6379           │
│    - Scan Job uses Redis for VM completion checkpointing               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                   ✅ Success               ❌ Failure
                        │                       │
                        ▼                       ▼
            ┌────────────────────┐    ┌────────────────────┐
            │ Scanning/Completed │    │  Scanning/Failed   │
            │ Status: Completed  │    │  Status: Failed    │
            └────────────────────┘    │  (Terminal State)  │
                        │             └────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Cleanup (on Completion)                                                 │
│    - PreScan Job deleted                                                │
│    - Redis Deployment deleted                                ⭐ NEW     │
│    - Redis Service deleted                                   ⭐ NEW     │
│    - ConfigMap deleted                                                  │
│    - Scan Job deleted                                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Redis Deployment Details

### Redis Pod Specification
```yaml
Image: redis:7-alpine
Resources:
  Requests:
    memory: 512Mi
    cpu: 250m
  Limits:
    memory: 1Gi
    cpu: 500m
Config:
  - maxmemory 1gb
  - maxmemory-policy allkeys-lru
  - appendonly yes
  - appendfsync everysec
Volumes:
  - name: redis-data
    emptyDir: {}
Probes:
  Liveness: redis-cli ping (every 5s)
  Readiness: redis-cli ping (every 3s)
```

### Labels (Same as Scan Job)
```yaml
app: redis
scan-instance: <scaninstance-name>
app.kubernetes.io/name: redis
app.kubernetes.io/component: cache
app.kubernetes.io/managed-by: threat-scanning-controller
trilio.io/scaninstance-name: <scaninstance-name>
```

### Service
```yaml
Type: ClusterIP
Port: 6379
Selector:
  app: redis
  scan-instance: <scaninstance-name>
```

## Idempotency Points

Throughout the flow, the controller checks conditions to ensure idempotency:

1. **PreScan Phase**
   - ✅ Check `HasCondition(PreScan, Completed)` → Skip to Redis phase
   - ✅ Check `HasCondition(PreScan, Failed)` → Terminal, stop

2. **RedisDeployment Phase** ⭐ NEW
   - ✅ Check `HasCondition(RedisDeployment, Ready)` → Skip to Scanning
   - ✅ Check `HasCondition(RedisDeployment, Failed)` → Terminal, stop
   - ✅ Check `HasCondition(RedisDeployment, InProgress)` → Don't recreate

3. **Scanning Phase**
   - ✅ Check `HasCondition(Scanning, Completed)` → Skip, already done
   - ✅ Check `HasCondition(Scanning, Failed)` → Terminal, stop
   - ✅ Check `HasCondition(Scanning, InProgress)` → Don't recreate

## Crash Resilience with Redis

### Scenario: Scan Job Pod Crashes Mid-Scan

**Without Redis (Before):**
```
VM1 ✅ → VM2 ✅ → VM3 ✅ → [CRASH] → VM1 ✅ → VM2 ✅ → VM3 ✅ → VM4 ✅
                                      ^
                                      Wasted work, rescan all VMs
```

**With Redis Deployment (After):**
```
VM1 ✅ → Redis: SADD completed_vms VM1
VM2 ✅ → Redis: SADD completed_vms VM2
VM3 ✅ → Redis: SADD completed_vms VM3
[CRASH]
[POD RESTART] → Redis: SMEMBERS completed_vms → [VM1, VM2, VM3]
VM4 ✅ → Redis: SADD completed_vms VM4
VM5 ✅ → Redis: SADD completed_vms VM5
                ^
                Resume from VM4, no wasted work
```

### Key Implementation in Scanner Code (Future)

```python
# At scan start
redis_client = redis.from_url(f"redis://redis-svc-{scan_instance_name}:6379")
completed_vms = redis_client.smembers(f"completed_vms:{backup_id}")

# For each VM
for vm_info in vms_to_scan:
    if vm_info.vm_id in completed_vms:
        logger.info(f"Skipping already scanned VM: {vm_info.vm_id}")
        continue
    
    # Scan VM
    scan_vm(vm_info)
    
    # Checkpoint completion
    redis_client.sadd(f"completed_vms:{backup_id}", vm_info.vm_id)
    logger.info(f"Checkpointed VM {vm_info.vm_id} as completed")
```

## Resource Lifecycle

```
ScanInstance Created
    │
    ├─> PreScan Job (ownerRef: ScanInstance)
    │   └─> Deleted on: Completion (success)
    │
    ├─> Redis Deployment (ownerRef: ScanInstance)  ⭐ NEW
    │   ├─> Redis Pod
    │   └─> Deleted on: Scan Completion or ScanInstance Deletion
    │
    ├─> Redis Service (ownerRef: ScanInstance)     ⭐ NEW
    │   └─> Deleted on: Scan Completion or ScanInstance Deletion
    │
    ├─> ConfigMap (ownerRef: ScanInstance)
    │   └─> Deleted on: Scan Completion
    │
    └─> Scan Job (ownerRef: ScanInstance)
        └─> Deleted on: Completion (success)

Failed resources (PreScan Job, Scan Job) kept for debugging until ScanInstance deletion
```
