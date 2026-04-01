# ✅ Loop Device Issue - FIXED

## Issue Summary

**Error:**
```
losetup: cannot find an unused loop device: No such file or directory
```

**Root Cause:** Scan job was only running in privileged mode for ObjectStore targets, but **ALL targets** (including NFS) need privileged mode because the scan engine must mount disk images (QCOW2/RAW files) using loop/NBD devices.

---

## What Was Fixed

### Controller Code Change

**File:** `pkg/helpers/job_helper.go` (line 956-963)

**Before:**
```go
// Add privileged security context only for ObjectStore targets
if target.IsObjectStoreTarget() {
    privileged := true
    scanContainer.SecurityContext.Privileged = &privileged
    // ...
}
```

**After:**
```go
// CRITICAL: Always add privileged security context for scan jobs
// Privileged mode is required for:
// 1. s3fuse mounting (ObjectStore targets)
// 2. qemu-nbd for QCOW2 disk images (ALL targets)
// 3. losetup for RAW disk images (ALL targets)
// 4. modprobe for loading nbd/loop kernel modules (ALL targets)
privileged := true
scanContainer.SecurityContext.Privileged = &privileged
scanContainer.SecurityContext.Capabilities = &corev1.Capabilities{
    Add: []corev1.Capability{"SYS_ADMIN"},
}
```

---

## Why This Happens

### The Disk Mounting Flow

1. **Target Mounting** (NFS/S3)
   - NFS: PVC mount (no privilege needed)
   - S3: s3fuse mount (privilege needed)

2. **Disk Image Mounting** ⚠️ **THIS IS WHERE IT FAILS**
   - QCOW2 files: Need `qemu-nbd` + `/dev/nbd*` devices
   - RAW files: Need `losetup` + `/dev/loop*` devices
   - **Both require privileged mode**

### Why NFS Targets Also Need Privileged Mode

Even though NFS mounting via PVC works fine, the **disk images stored on the NFS share** are still QCOW2 or RAW files that need to be mounted:

```
/triliodata (NFS PVC) ✅ No privilege needed
└── backup-uuid/
    └── snapshot/
        └── disk.qcow2  ❌ Needs qemu-nbd + /dev/nbd* = PRIVILEGED MODE
```

---

## Technical Details

### What Needs Privileged Access

| Operation | Command | Requires | Why |
|-----------|---------|----------|-----|
| Load NBD module | `modprobe nbd` | Privileged | Load kernel module |
| Load loop module | `modprobe loop` | Privileged | Load kernel module |
| Attach QCOW2 | `qemu-nbd -c /dev/nbd0 disk.qcow2` | Privileged | Create block device |
| Attach RAW | `losetup -f disk.raw` | Privileged | Create loop device |
| Mount partition | `mount /dev/nbd0p1 /mnt` | Privileged | Mount filesystem |

### Scan Engine Code References

**QCOW2 Mounting** (`forensics/disk_analyzer.py`):
```python
# Load nbd module - NEEDS PRIVILEGED
cmd = ['sudo', 'modprobe', 'nbd', 'max_part=8']

# Connect QCOW2 to NBD - NEEDS PRIVILEGED
cmd = ['sudo', 'qemu-nbd', '--fork', '-c', device, image_path]
```

**RAW Mounting** (`forensics/disk_analyzer.py`):
```python
# Setup loop device - NEEDS PRIVILEGED
cmd = ['sudo', 'losetup', '-f', '--show', image_path]
```

---

## Deployment Steps

### 1. Update Controller

```bash
# Build new controller image with the fix
cd threat-scanning-architecture
make docker-build docker-push IMG=your-registry/threat-scanning-controller:v1.x.x

# Update deployment
kubectl set image deployment/threat-scanning-controller \
  manager=your-registry/threat-scanning-controller:v1.x.x

# Restart controller
kubectl rollout restart deployment/threat-scanning-controller
```

### 2. Verify Fix

```bash
# Create a test ScanInstance
kubectl apply -f config/samples/scaninstance.yaml

# Wait for scan job creation
kubectl get jobs -l app.kubernetes.io/component=scan

# Verify scan job pod is privileged
kubectl get pod -l job-name=scan-job-xxx -o jsonpath='{.spec.containers[0].securityContext.privileged}'
# Should output: true

# Check pod has SYS_ADMIN capability
kubectl get pod -l job-name=scan-job-xxx -o jsonpath='{.spec.containers[0].securityContext.capabilities.add}'
# Should output: ["SYS_ADMIN"]
```

### 3. Test Disk Mounting

```bash
# Exec into scan job pod
kubectl exec -it scan-job-xxx-yyy -- /bin/bash

# Inside the pod:
# Check loop devices are available
ls -la /dev/loop*
# Should show: /dev/loop0, /dev/loop1, ...

# Load NBD module
modprobe nbd max_part=8

# Check NBD devices are available
ls -la /dev/nbd*
# Should show: /dev/nbd0, /dev/nbd1, ...

# Test losetup works
losetup -f
# Should show: /dev/loop0 (or next available)

# Test qemu-nbd works
qemu-nbd --version
# Should show: qemu-nbd version X.X.X
```

---

## Security Considerations

### Privileged Mode Risks

Running in privileged mode grants the container significant access to the host. Mitigation strategies:

1. **Namespace Isolation**: Scan jobs run in dedicated namespace
2. **RBAC**: Minimal service account permissions
3. **Resource Limits**: CPU/memory quotas enforced
4. **Network Policies**: Restrict egress/ingress
5. **Node Isolation**: Use dedicated nodes with taints

### Example Network Policy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: scan-job-netpol
  namespace: threat-scanning-system
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: scan
  policyTypes:
  - Egress
  egress:
  # Allow Redis access
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/component: redis
    ports:
    - protocol: TCP
      port: 6379
  # Allow DNS
  - to:
    - namespaceSelector:
        matchLabels:
          name: kube-system
    ports:
    - protocol: UDP
      port: 53
```

---

## Alternative Solutions Considered

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Privileged Mode** (chosen) | ✅ Works reliably<br>✅ Supports all formats<br>✅ Mature tooling | ⚠️ Security implications<br>⚠️ Needs controls | ✅ **Best option** |
| HostPath /dev | Simple | ❌ Can't load modules<br>❌ Partial solution | ❌ Doesn't work |
| Pre-load modules | Cleaner | ❌ Still needs device access<br>❌ Doesn't scale | ❌ Doesn't work |
| libguestfs | Feature-rich | ❌ Also needs privileged<br>❌ More complex | ❌ Same requirement |

---

## Testing Checklist

### Pre-Deployment

- [x] Code change made in `job_helper.go`
- [x] Documentation created
- [ ] Controller image built and pushed
- [ ] Controller deployment updated

### Post-Deployment

- [ ] Controller restarted successfully
- [ ] New scan jobs are privileged
- [ ] Loop devices accessible in pods
- [ ] NBD devices accessible in pods
- [ ] Disk mounting works (QCOW2)
- [ ] Disk mounting works (RAW)
- [ ] No loop device errors in logs

### Security Review

- [ ] Network policies applied
- [ ] RBAC reviewed
- [ ] Node isolation configured (if needed)
- [ ] Audit logging enabled
- [ ] Security team approval (if required)

---

## Rollback Plan

If issues occur:

```bash
# 1. Revert controller deployment
kubectl rollout undo deployment/threat-scanning-controller

# 2. Or roll back to specific revision
kubectl rollout history deployment/threat-scanning-controller
kubectl rollout undo deployment/threat-scanning-controller --to-revision=N

# 3. Delete failing scan jobs
kubectl delete jobs -l app.kubernetes.io/component=scan

# 4. Monitor controller logs
kubectl logs -f deployment/threat-scanning-controller
```

---

## Documentation

- **Detailed Analysis**: `SCAN_JOB_PRIVILEGED_MODE.md`
- **Controller Code**: `pkg/helpers/job_helper.go` (line 956-967)
- **Scan Engine Code**: `forensics/disk_analyzer.py` (line 561-627)

---

## Summary

✅ **Root cause identified**: Scan jobs need privileged mode for disk mounting  
✅ **Fix implemented**: Always set privileged=true for scan jobs  
✅ **Documentation created**: Security implications and mitigation strategies  
✅ **Testing guide provided**: Verification steps included  

**Next Steps:**
1. Build and deploy updated controller
2. Test with real ScanInstance
3. Verify no more loop device errors
4. Apply security controls as needed

---

**Status:** ✅ Fixed in code, pending deployment  
**Priority:** High (blocks all disk mounting operations)  
**Impact:** All scan jobs (both NFS and ObjectStore targets)
