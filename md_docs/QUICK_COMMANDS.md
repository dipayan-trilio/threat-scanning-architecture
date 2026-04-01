# Quick Command Reference

## PostgreSQL Secret Integration

### Setup
```bash
# Set environment variables in controller deployment
kubectl set env deployment/threat-scanning-controller \
  -n threat-scanning-system \
  POSTGRES_HOST=postgres.db.svc.cluster.local \
  POSTGRES_PORT=5432 \
  POSTGRES_USER=scanuser \
  POSTGRES_PASSWORD=<password> \
  POSTGRES_DASHBOARD_DATABASE=dashboard_db \
  POSTGRES_CACHE_DATABASE=cache_db
```

### Verify Secret Created
```bash
kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system
```

### Check Secret Data
```bash
kubectl get secret scan-secret-<scaninstance-name> -n threat-scanning-system -o jsonpath='{.data.DATABASE_URL}' | base64 -d
```

---

## Report Upload Integration

### Create Reporting Target
```bash
cat <<EOF | kubectl apply -f -
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    url: "https://s3.amazonaws.com"
    bucketName: "threat-scan-reports"
    region: "us-east-1"
    credentialSecret:
      name: reporting-credentials
EOF
```

### Verify Reporting Target
```bash
# Check annotation
kubectl get target reporting-target -o jsonpath='{.metadata.annotations.trilio\.io/reporting-target}'

# Check status
kubectl get target reporting-target -o jsonpath='{.status.status}'
```

### Verify Scan Job Command
```bash
JOB=$(kubectl get job -n threat-scanning-system -l trilio.io/scaninstance-name=<name> -o jsonpath='{.items[0].metadata.name}')
kubectl get job $JOB -n threat-scanning-system -o jsonpath='{.spec.template.spec.containers[0].args[0]}' | grep -E "soc_database_setup|report_uploader"
```

### Check Execution in Logs
```bash
POD=$(kubectl get pod -l job-name=$JOB -n threat-scanning-system -o jsonpath='{.items[0].metadata.name}')

# Check for all three stages
kubectl logs $POD -n threat-scanning-system | grep -E "(Scan completed|database setup|Upload complete)"

# Check database setup specifically
kubectl logs $POD -n threat-scanning-system | grep -A 10 "soc_database_setup"
```

### Verify Reports in S3
```bash
aws s3 ls s3://threat-scan-reports/reports/ --recursive | grep "$(date +%Y-%m-%d)"
```

---

## Complete Test Flow

```bash
# 1. Deploy controller with PostgreSQL config
kubectl apply -f controller-deployment.yaml
kubectl rollout status deployment/threat-scanning-controller -n threat-scanning-system

# 2. Create reporting target
kubectl apply -f reporting-target.yaml

# 3. Verify setup
kubectl get target reporting-target
kubectl get target reporting-target -o jsonpath='{.metadata.annotations}'

# 4. Create test ScanInstance
kubectl apply -f scaninstance-sample.yaml

# 5. Monitor scan instance
kubectl get scaninstance <name> -w

# 6. Check scan job
kubectl get job -n threat-scanning-system -l trilio.io/scaninstance-name=<name>

# 7. View logs
kubectl logs -f <scan-job-pod> -n threat-scanning-system

# 8. Verify secret
kubectl get secret scan-secret-<name> -n threat-scanning-system -o yaml

# 9. Verify reports in S3
aws s3 ls s3://threat-scan-reports/reports/<instance-id>/ --recursive

# 10. Check for errors
kubectl get events -n threat-scanning-system --sort-by='.lastTimestamp' | grep -i error
```

---

## Debugging Commands

### PostgreSQL Secret Issues
```bash
# Check if secret exists
kubectl get secret -n threat-scanning-system | grep scan-secret

# Decode secret data
kubectl get secret scan-secret-<name> -n threat-scanning-system -o json | jq -r '.data | map_values(@base64d)'

# Check pod environment variables
kubectl exec -it <scan-job-pod> -n threat-scanning-system -- env | grep -E "DATABASE_URL|PG_"
```

### Report Upload Issues
```bash
# Check reporting target count
kubectl get targets -o json | jq '[.items[] | select(.metadata.annotations."trilio.io/reporting-target" == "true")] | length'

# List all reporting targets
kubectl get targets -o json | jq '.items[] | select(.metadata.annotations."trilio.io/reporting-target" == "true") | .metadata.name'

# View full scan job command
kubectl get job <name> -n threat-scanning-system -o jsonpath='{.spec.template.spec.containers[0].args[0]}' | tr '&&' '\n'

# Check upload failure reason
kubectl logs <scan-job-pod> -n threat-scanning-system | tail -100 | grep -A 10 -B 10 "report_uploader"
```

### Common Errors
```bash
# No reporting target
kubectl get targets -o json | jq '.items[] | select(.metadata.annotations."trilio.io/reporting-target" == "true")'
# If empty, add annotation to a target

# Multiple reporting targets
kubectl get targets -o json | jq '.items[] | select(.metadata.annotations."trilio.io/reporting-target" == "true") | .metadata.name'
# Remove annotation from extras

# Secret not created
kubectl describe scaninstance <name> | grep -A 10 "Events:"
# Check for secret creation events

# Upload permission denied
kubectl get secret reporting-credentials -n threat-scanning-system -o yaml
# Verify credentials, test with AWS CLI
```

---

## Cleanup

```bash
# Delete ScanInstance (automatically deletes secret)
kubectl delete scaninstance <name>

# Verify secret deleted
kubectl get secret scan-secret-<name> -n threat-scanning-system
# Should return NotFound

# Delete reporting target
kubectl delete target reporting-target

# Clean up old reports (optional)
aws s3 rm s3://threat-scan-reports/reports/ --recursive
```

---

## One-Liners

```bash
# Check all scan secrets
kubectl get secrets -n threat-scanning-system | grep scan-secret

# Count reporting targets
kubectl get targets -o json | jq '[.items[] | select(.metadata.annotations."trilio.io/reporting-target" == "true")] | length'

# Latest scan job
kubectl get job -n threat-scanning-system --sort-by='.metadata.creationTimestamp' | tail -1

# Recent uploads to S3
aws s3 ls s3://threat-scan-reports/reports/ --recursive | tail -20

# Failed scan jobs
kubectl get jobs -n threat-scanning-system -o json | jq '.items[] | select(.status.failed > 0) | .metadata.name'

# Scan job success rate (last 10)
kubectl get jobs -n threat-scanning-system --sort-by='.metadata.creationTimestamp' | tail -10 | awk '{if($3=="1/1")s++;t++}END{print "Success:",s,"Total:",t,"Rate:",s/t*100"%"}'
```

---

_Quick Reference for PostgreSQL Secret + Report Upload Integration_
