# Quick Test Guide - Target Poller

## 🚀 Fastest Way to Test

### 1️⃣ Edit the Simple Test Job

```bash
cd config/samples
vi test-poller-job-simple.yaml
```

**Change line 37:**
```yaml
TARGET_NAME="minio-target"  # ← Change this to your target name
```

**Change line 30:**
```yaml
image: your-registry/datastore-attacher:latest  # ← Change to your image
```

### 2️⃣ Run the Test

```bash
# Apply
kubectl apply -f test-poller-job-simple.yaml

# Watch logs (follow mode)
kubectl logs -n threat-scanning-system test-poller-simple -f
```

### 3️⃣ Cleanup

```bash
kubectl delete job -n threat-scanning-system test-poller-simple
```

## 📋 One-Liner for Quick Testing

```bash
# Edit, apply, and watch in one go
vi test-poller-job-simple.yaml && \
kubectl apply -f test-poller-job-simple.yaml && \
kubectl logs -n threat-scanning-system test-poller-simple -f
```

## ✅ Expected Success Output

```
==========================================
Testing Target Poller
Target: minio-target
==========================================
Mounting datastore...
✓ Mounted to /triliodata

Running poller...
✓ Poller completed successfully!
```

## ❌ Common Errors

| Error | Fix |
|-------|-----|
| `Target not found` | Check target name: `kubectl get targets` |
| `Image pull error` | Update image in line 30 |
| `Permission denied` | Check service account exists |
| `Mount failed` | Check target credentials/secret |

## 🔍 Debug Commands

```bash
# Check if target exists
kubectl get target <target-name> -o yaml

# Check job status
kubectl get job -n threat-scanning-system test-poller-simple

# Get detailed job info
kubectl describe job -n threat-scanning-system test-poller-simple

# Check pod status
kubectl get pods -n threat-scanning-system -l job-name=test-poller-simple

# Get pod logs (if job failed)
kubectl logs -n threat-scanning-system -l job-name=test-poller-simple
```

## 🎯 Test Different Targets

```bash
# Test target 1
sed -i 's/TARGET_NAME=".*"/TARGET_NAME="target-1"/' test-poller-job-simple.yaml
kubectl apply -f test-poller-job-simple.yaml

# Test target 2
sed -i 's/TARGET_NAME=".*"/TARGET_NAME="target-2"/' test-poller-job-simple.yaml
kubectl apply -f test-poller-job-simple.yaml
```

## 📚 More Options

- **ObjectStore (detailed):** Use `test-poller-job-objectstore.yaml`
- **NFS targets:** Use `test-poller-job-nfs.yaml`
- **Full guide:** See `TEST_POLLER_README.md`

---

**That's it!** Just change the target name and run. 🎉


