# Scan Job Privileged Mode Requirement

## Issue: Loop Device Not Available

### Error Message
```
ERROR - VM test-vm_dp: Failed to mount vol-src-as-dv: Failed to mount /triliodata/.../vol-src-as-dv: 
Failed to mount raw image: Command failed: losetup -f --show /triliodata/.../vol-src-as-dv, 
Error: losetup: cannot find an unused loop device: No such file or directory
```

### Root Cause

The scan engine needs to mount actual disk images (QCOW2, RAW, VDI, VMDK) from backup data to analyze them. This requires:

1. **Loop devices** (`/dev/loop*`) for RAW disk images
2. **NBD devices** (`/dev/nbd*`) for QCOW2/VDI/VMDK disk images
3. **Kernel modules** (`nbd`, `loop`) that need to be loaded
4. **Device access** to create and manage block devices

**Without privileged mode**, containers cannot:
- Access `/dev/loop*` or `/dev/nbd*` devices
- Load kernel modules via `modprobe`
- Create block device mappings
- Mount filesystems from disk images

---

## Solution: Always Run Scan Jobs in Privileged Mode

### Controller Change

**File:** `pkg/helpers/job_helper.go`

**Before (INCORRECT):**
```go
// Add privileged security context only for ObjectStore targets (needed for s3fuse)
if target.IsObjectStoreTarget() {
    privileged := true
    scanContainer.SecurityContext.Privileged = &privileged
    scanContainer.SecurityContext.Capabilities = &corev1.Capabilities{
        Add: []corev1.Capability{"SYS_ADMIN"},
    }
}
```

**After (CORRECT):**
```go
// CRITICAL: Always add privileged security context for scan jobs
// Privileged mode is required for:
// 1. s3fuse mounting (ObjectStore targets)
// 2. qemu-nbd for QCOW2 disk images (ALL targets)
// 3. losetup for RAW disk images (ALL targets)
// 4. modprobe for loading nbd/loop kernel modules (ALL targets)
// Without privileged mode, loop devices won't be available and mounting will fail
privileged := true
scanContainer.SecurityContext.Privileged = &privileged
scanContainer.SecurityContext.Capabilities = &corev1.Capabilities{
    Add: []corev1.Capability{"SYS_ADMIN"},
}
```

---

## Why Privileged Mode is Required

### Disk Mounting Requirements

| Operation | Tool | Requires | Used For |
|-----------|------|----------|----------|
| **QCOW2 mounting** | `qemu-nbd` | `/dev/nbd*`, `modprobe nbd` | QCOW2, VDI, VMDK disk images |
| **RAW mounting** | `losetup` | `/dev/loop*`, `modprobe loop` | RAW disk images |
| **Partition access** | `mount` | Block device access | Mounting filesystems |
| **S3 mounting** | `s3fuse` | FUSE, `SYS_ADMIN` | ObjectStore targets only |

### Scan Engine Operations

```python
# From forensics/disk_analyzer.py

def _mount_qcow2(self, image_path: str, mount_point: MountPoint):
    # Load NBD kernel module - REQUIRES PRIVILEGED
    cmd = ['sudo', 'modprobe', 'nbd', 'max_part=8']
    
    # Connect to NBD device - REQUIRES PRIVILEGED
    cmd = ['sudo', 'qemu-nbd', '--fork', '-c', device, image_path]

def _mount_raw_image(self, image_path: str, mount_point: MountPoint):
    # Setup loop device - REQUIRES PRIVILEGED  
    cmd = ['sudo', 'losetup', '-f', '--show', image_path]
```

---

## Impact Analysis

### NFS Targets

**Previous assumption:** NFS targets don't need privileged mode because PVC handles mounting.

**Reality:** While the NFS share itself is mounted via PVC, the **disk images stored on NFS** (QCOW2/RAW files) still need to be mounted using loop/NBD devices.

**Workflow:**
1. NFS share mounted at `/triliodata` ✅ (via PVC, no privilege needed)
2. Backup files accessible at `/triliodata/uuid/.../*.qcow2` ✅
3. **Scan engine mounts QCOW2 file** ❌ (NEEDS loop/NBD devices - privileged required)

### ObjectStore Targets

**Previous:** Already had privileged mode for s3fuse

**Now:** Still privileged, but also for disk mounting (not just s3fuse)

**Workflow:**
1. S3 bucket mounted via s3fuse ✅ (privileged for FUSE)
2. Backup files accessible ✅
3. **Scan engine mounts QCOW2 file** ✅ (same privileged mode covers this)

---

## Security Implications

### Privileged Container Risks

Running in privileged mode grants the container nearly root-level access to the host. This is necessary but requires proper security controls:

1. **Network Segmentation**: Scan jobs run in isolated namespace
2. **RBAC**: Service account has minimal permissions
3. **Pod Security**: No HostNetwork, HostPID, or HostIPC
4. **Resource Limits**: CPU and memory limits enforced
5. **TTL**: Jobs are cleaned up after completion

### Mitigation Strategies

1. **Dedicated Nodes**: Run scan jobs on dedicated worker nodes
   ```yaml
   nodeSelector:
     workload-type: threat-scanning
   ```

2. **Taints and Tolerations**: Isolate scan workloads
   ```yaml
   tolerations:
   - key: "threat-scanning"
     operator: "Equal"
     value: "true"
     effect: "NoSchedule"
   ```

3. **Network Policies**: Restrict scan job network access
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: scan-job-netpol
   spec:
     podSelector:
       matchLabels:
         app.kubernetes.io/component: scan
     policyTypes:
     - Egress
     egress:
     - to:
       - podSelector:
           matchLabels:
             app: redis
   ```

4. **Audit Logging**: Monitor privileged container usage

---

## Alternative Approaches Considered

### 1. Use HostPath for /dev

**Approach:**
```yaml
volumes:
- name: dev
  hostPath:
    path: /dev
```

**Problem:** Still can't load kernel modules without privileged mode

**Verdict:** ❌ Doesn't solve the problem

### 2. Pre-load Modules on Host

**Approach:** Load `nbd` and `loop` modules on all nodes via DaemonSet

**Problem:** 
- Still need device access
- Can't create new loop/nbd mappings without privilege
- Doesn't scale across different node types

**Verdict:** ❌ Partial solution, still needs privileged mode

### 3. Use libguestfs

**Approach:** Use libguestfs for disk mounting instead of qemu-nbd/losetup

**Problem:**
- libguestfs itself requires privileged mode
- More complex, heavier weight
- Still needs device access

**Verdict:** ❌ Same requirement, more complexity

### 4. Privileged Mode (CHOSEN)

**Approach:** Run scan jobs in privileged mode with security controls

**Benefits:**
- ✅ Works reliably
- ✅ Supports all disk formats (QCOW2, RAW, VDI, VMDK)
- ✅ Mature tooling (qemu-nbd, losetup)
- ✅ Can be secured with proper controls

**Trade-offs:**
- ⚠️ Requires privileged containers
- ⚠️ Needs careful security planning

**Verdict:** ✅ Best available option

---

## Testing

### Verify Privileged Mode

```bash
# Check scan job has privileged mode
kubectl get pod -l job-name=scan-job-xxx -o jsonpath='{.spec.containers[0].securityContext.privileged}'
# Should output: true

# Check capabilities
kubectl get pod -l job-name=scan-job-xxx -o jsonpath='{.spec.containers[0].securityContext.capabilities.add}'
# Should output: ["SYS_ADMIN"]
```

### Verify Device Access

```bash
# Exec into scan job pod
kubectl exec -it scan-job-xxx-yyy -- /bin/bash

# Check loop devices
ls -la /dev/loop*
# Should show /dev/loop0 through /dev/loop7 (or more)

# Check NBD devices (after loading module)
modprobe nbd max_part=8
ls -la /dev/nbd*
# Should show /dev/nbd0 through /dev/nbd15

# Test losetup
losetup -f
# Should show available loop device, e.g., /dev/loop0

# Test qemu-nbd
qemu-nbd --version
# Should show version info
```

---

## Migration Guide

### For Existing Deployments

1. **Update controller image** with the fix
2. **Restart controller** to apply changes
3. **Delete old scan jobs** (if any stuck)
4. **Create new ScanInstance** to test

```bash
# Update controller
kubectl set image deployment/threat-scanning-controller \
  manager=your-registry/threat-scanning-controller:v1.x.x

# Restart controller
kubectl rollout restart deployment/threat-scanning-controller

# Check controller logs
kubectl logs -f deployment/threat-scanning-controller

# Clean up old scan jobs
kubectl delete jobs -l app.kubernetes.io/component=scan

# Test with new ScanInstance
kubectl apply -f scaninstance-test.yaml

# Verify scan job is privileged
kubectl get pod -l scan-instance=test -o yaml | grep -A 5 securityContext
```

---

## Documentation Updates

### README Updates Required

- [ ] Add security section explaining privileged mode requirement
- [ ] Document node isolation strategies
- [ ] Update troubleshooting guide with loop device errors
- [ ] Add network policy examples

### Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│            Scan Job Pod (Privileged)            │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │  Scan Engine Container                    │ │
│  │  ┌─────────────────────────────────────┐  │ │
│  │  │  Privileged Security Context        │  │ │
│  │  │  - Privileged: true                 │  │ │
│  │  │  - Capabilities: [SYS_ADMIN]        │  │ │
│  │  └─────────────────────────────────────┘  │ │
│  │                                             │ │
│  │  Operations:                                │ │
│  │  1. modprobe nbd/loop ────┐                │ │
│  │  2. qemu-nbd -c /dev/nbd0 │                │ │
│  │  3. losetup /dev/loop0     ├──► Host       │ │
│  │  4. mount disk partitions  │    Kernel     │ │
│  └────────────────────────────┴────────────────┘ │
│                                                  │
│  Volumes:                                        │
│  - /triliodata (NFS PVC or s3fuse mount)        │
│  - /config (ConfigMap with scan config)         │
└──────────────────────────────────────────────────┘
```

---

## References

- **Issue**: Loop device not found error
- **Root Cause**: Non-privileged container can't access loop/NBD devices
- **Solution**: Always use privileged mode for scan jobs
- **Affected Files**:
  - `pkg/helpers/job_helper.go` - Scan job creation
  - `forensics/disk_analyzer.py` - Disk mounting operations
  - `agents/disk_agent.py` - Disk analysis agent

---

**Status:** ✅ Fixed in controller code  
**Testing:** Required after controller deployment  
**Security Review:** Recommended for production deployments
