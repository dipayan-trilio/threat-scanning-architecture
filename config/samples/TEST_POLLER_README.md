# Target Poller Test Jobs

This directory contains manual test jobs for the target poller functionality.

## Available Test Jobs

| File | Description | Use Case |
|------|-------------|----------|
| `test-poller-job-simple.yaml` | ⭐ **Recommended** - Minimal config | Quick testing with ObjectStore targets |
| `test-poller-job-objectstore.yaml` | Full config for ObjectStore | Detailed testing with S3/MinIO/Azure |
| `test-poller-job-nfs.yaml` | Full config for NFS | Testing with NFS targets |

## Quick Start (Recommended)

### 1. Use the Simple Test Job

```bash
# Edit the file and change TARGET_NAME (line 37)
vi config/samples/test-poller-job-simple.yaml

# Apply the job
kubectl apply -f config/samples/test-poller-job-simple.yaml

# Watch the logs
kubectl logs -n threat-scanning-system test-poller-simple -f

# Cleanup
kubectl delete job -n threat-scanning-system test-poller-simple
```

### 2. What to Change

In `test-poller-job-simple.yaml`, update line 37:

```yaml
TARGET_NAME="minio-target"  # Change to your target name
```

And line 30 (image):

```yaml
image: your-registry/datastore-attacher:latest  # Change to your image
```

## Detailed Testing

### ObjectStore Target (S3/MinIO/Azure)

```bash
# 1. Edit the file
vi config/samples/test-poller-job-objectstore.yaml

# 2. Update these values:
#    - Line 69: TARGET_NAME
#    - Line 76: RELATED_IMAGE_VALIDATOR (image)

# 3. Apply
kubectl apply -f config/samples/test-poller-job-objectstore.yaml

# 4. Check logs
kubectl logs -n threat-scanning-system test-poller-objectstore -f

# 5. Cleanup
kubectl delete job -n threat-scanning-system test-poller-objectstore
```

### NFS Target

```bash
# 1. Edit the file
vi config/samples/test-poller-job-nfs.yaml

# 2. Update these values:
#    - Line 55: TARGET_NAME
#    - Line 62: RELATED_IMAGE_VALIDATOR (image)
#    - Line 93-94: NFS server and path

# 3. Apply
kubectl apply -f config/samples/test-poller-job-nfs.yaml

# 4. Check logs
kubectl logs -n threat-scanning-system test-poller-nfs -f

# 5. Cleanup
kubectl delete job -n threat-scanning-system test-poller-nfs
```

## Prerequisites

### 1. Target CR Must Exist

Create a Target CR first:

```bash
# For ObjectStore (MinIO example)
kubectl apply -f config/samples/minio-target-secret.yaml
kubectl apply -f config/samples/minio-target.yaml

# Verify
kubectl get targets
```

### 2. ServiceAccount Must Exist

The jobs use `trilio-threat-scanning` service account:

```bash
# Check if it exists
kubectl get sa -n threat-scanning-system trilio-threat-scanning

# If not, create it with appropriate RBAC
# (Usually created by the controller deployment)
```

### 3. Image Must Be Available

Update the image in the test job:

```yaml
image: your-registry/datastore-attacher:latest
```

Or use environment variable:

```yaml
env:
- name: RELATED_IMAGE_VALIDATOR
  value: "your-registry/datastore-attacher:latest"
```

## Expected Output

### Successful Run

```
==========================================
Target Poller Test Job
==========================================
Target Name: minio-target
Namespace: threat-scanning-system
==========================================

Step 1: Mounting datastore...
INFO: Fetching target cr to get the datastore
INFO: Fetched the list of datastores to be mounted
INFO: Mounting datastore: s3://shiwam-test
INFO: Successfully mounted datastore to /triliodata

✓ Datastore mounted successfully to /triliodata

Step 2: Running target poller...
INFO: Starting target poller for target: minio-target
INFO: Polling for new backups...
INFO: Found 5 backups in target
INFO: Target status updated successfully

==========================================
✓ Poller completed successfully
==========================================
```

### Failed Run (Target Not Found)

```
==========================================
Target Poller Test Job
==========================================
Target Name: non-existent-target
==========================================

Step 1: Mounting datastore...
ERROR: Target 'non-existent-target' not found
ERROR: Failed to fetch target CR
```

## Troubleshooting

### Issue: "Target not found"

**Solution:**
```bash
# Check if target exists
kubectl get targets

# Check target name matches
kubectl get target <target-name> -o yaml
```

### Issue: "Permission denied" or "Forbidden"

**Solution:**
```bash
# Check service account exists
kubectl get sa -n threat-scanning-system trilio-threat-scanning

# Check RBAC permissions
kubectl get clusterrole threat-scanning-controller-role -o yaml
kubectl get clusterrolebinding threat-scanning-controller-rolebinding -o yaml
```

### Issue: "Failed to mount datastore"

**For ObjectStore:**
```bash
# Check secret exists
kubectl get secret <secret-name> -n <namespace>

# Check credentials are correct
kubectl get secret <secret-name> -n <namespace> -o yaml

# Check URL is accessible
curl -k <s3-url>
```

**For NFS:**
```bash
# Check NFS server is accessible
ping <nfs-server>

# Check NFS export exists
showmount -e <nfs-server>

# Verify NFS path in job YAML matches export
```

### Issue: "Image pull error"

**Solution:**
```bash
# Update image in job YAML
image: your-registry/datastore-attacher:latest

# Or use image pull secret
kubectl create secret docker-registry regcred \
  --docker-server=<your-registry> \
  --docker-username=<username> \
  --docker-password=<password>

# Add to job spec:
imagePullSecrets:
- name: regcred
```

## Testing Different Scenarios

### Test 1: Basic Connectivity

```bash
# Use simple job to verify target is accessible
kubectl apply -f config/samples/test-poller-job-simple.yaml
kubectl logs -n threat-scanning-system test-poller-simple -f
```

### Test 2: Multiple Targets

```bash
# Test target 1
sed 's/TARGET_NAME=".*"/TARGET_NAME="target-1"/' test-poller-job-simple.yaml | kubectl apply -f -

# Test target 2
sed 's/TARGET_NAME=".*"/TARGET_NAME="target-2"/' test-poller-job-simple.yaml | kubectl apply -f -
```

### Test 3: Verify Mount Path

```bash
# Add debug commands to see mounted content
# Edit test-poller-job-simple.yaml and add after mount:
echo "Listing /triliodata contents:"
ls -la /triliodata
```

### Test 4: Long-Running Test

```bash
# Modify the job to run multiple times
# Add loop in the script:
for i in {1..5}; do
  echo "Run $i of 5"
  target-poller --target-name=${TARGET_NAME} ...
  sleep 60
done
```

## Comparison with CronJob

| Aspect | Test Job (Manual) | CronJob (Production) |
|--------|-------------------|----------------------|
| **Trigger** | Manual `kubectl apply` | Scheduled (e.g., every 5 min) |
| **Runs** | Once | Repeated on schedule |
| **Cleanup** | TTL or manual delete | Automatic (keeps last N) |
| **Use Case** | Testing, debugging | Production polling |
| **Logs** | Easy to follow | Need to find specific run |

## Converting to CronJob

If you want to convert a test job to a scheduled CronJob:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: target-poller-cronjob
  namespace: threat-scanning-system
spec:
  schedule: "*/5 * * * *"  # Every 5 minutes
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      # Copy everything from Job spec here
      template:
        spec:
          # ... container spec ...
```

## Cleanup

### Remove Single Job

```bash
kubectl delete job -n threat-scanning-system test-poller-simple
```

### Remove All Test Jobs

```bash
kubectl delete job -n threat-scanning-system -l app.kubernetes.io/managed-by=manual-test
```

### Check Job Status

```bash
# List all jobs
kubectl get jobs -n threat-scanning-system

# Get job details
kubectl describe job -n threat-scanning-system test-poller-simple

# Get pod logs (if job completed)
kubectl logs -n threat-scanning-system job/test-poller-simple
```

## Next Steps

After successful poller testing:

1. ✅ Test with different target types (S3, MinIO, Azure, NFS)
2. ✅ Verify target status updates in Target CR
3. ✅ Test error scenarios (invalid credentials, unreachable server)
4. ✅ Deploy production CronJob with proper schedule
5. ✅ Set up monitoring and alerts for poller failures

---

**Happy Testing!** 🎉

For issues or questions, check the main documentation or controller logs.


