#!/bin/bash
# Script to verify that scan jobs retry 3 times before marking ScanInstance as failed

set -e

echo "=== Job Retry Fix Verification ==="
echo
echo "This script verifies that scan jobs with BackoffLimit=3 retry properly"
echo "before the ScanInstance is marked as failed."
echo

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl not found. Please install kubectl."
    exit 1
fi

# Function to cleanup resources
cleanup() {
    echo "Cleaning up test resources..."
    kubectl delete scaninstance test-retry-si --ignore-not-found=true
    echo "Cleanup complete."
}

# Register cleanup on exit
trap cleanup EXIT

echo "Step 1: Create a test ScanInstance with a failing scan job"
echo "-----------------------------------------------------------"

# Create a ScanInstance that will trigger a scan job
# The scan job should fail initially but retry up to 3 times
cat <<EOF | kubectl apply -f -
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-retry-si
spec:
  backupTarget:
    name: minio-target
  backupRef:
    uid: "test-backup-uid"
    path: "test-path"
EOF

echo "Waiting for scan job to be created..."
sleep 10

# Get the scan job name
SCAN_JOB=$(kubectl get jobs -l app.kubernetes.io/component=scan,threatscanning.trilio.io/scaninstance-name=test-retry-si -o name | head -1)

if [ -z "$SCAN_JOB" ]; then
    echo "Error: Scan job not found. ScanInstance may have failed before reaching scan phase."
    kubectl get scaninstance test-retry-si -o yaml
    exit 1
fi

echo "Found scan job: $SCAN_JOB"
echo

echo "Step 2: Monitor job status and pod failures"
echo "-------------------------------------------"

# Monitor the job for up to 5 minutes
TIMEOUT=300
ELAPSED=0
LAST_FAILED_COUNT=0

while [ $ELAPSED -lt $TIMEOUT ]; do
    # Get job status
    JOB_STATUS=$(kubectl get $SCAN_JOB -o jsonpath='{.status}')
    FAILED_COUNT=$(echo "$JOB_STATUS" | jq -r '.failed // 0')
    ACTIVE_COUNT=$(echo "$JOB_STATUS" | jq -r '.active // 0')
    SUCCEEDED_COUNT=$(echo "$JOB_STATUS" | jq -r '.succeeded // 0')
    
    # Check for JobFailed condition
    JOB_FAILED_CONDITION=$(kubectl get $SCAN_JOB -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}')
    
    echo "Time: ${ELAPSED}s | Failed: $FAILED_COUNT | Active: $ACTIVE_COUNT | Succeeded: $SUCCEEDED_COUNT | JobFailed: ${JOB_FAILED_CONDITION:-None}"
    
    # Check if failed count increased
    if [ "$FAILED_COUNT" -gt "$LAST_FAILED_COUNT" ] && [ "$FAILED_COUNT" -lt 4 ]; then
        echo "  → Pod failure #$FAILED_COUNT detected. Job should retry..."
        
        # Get ScanInstance status
        SI_STATUS=$(kubectl get scaninstance test-retry-si -o jsonpath='{.status.status}')
        echo "  → ScanInstance status: $SI_STATUS"
        
        if [ "$SI_STATUS" = "Failed" ]; then
            echo "  ✗ ERROR: ScanInstance marked as Failed after only $FAILED_COUNT pod failure(s)!"
            echo "  Expected: ScanInstance should remain InProgress until 4 failures (BackoffLimit=3)"
            kubectl get scaninstance test-retry-si -o yaml
            exit 1
        else
            echo "  ✓ GOOD: ScanInstance is still $SI_STATUS (not Failed)"
        fi
        
        LAST_FAILED_COUNT=$FAILED_COUNT
    fi
    
    # Check if job reached backoff limit
    if [ "$FAILED_COUNT" -ge 4 ] || [ "$JOB_FAILED_CONDITION" = "True" ]; then
        echo
        echo "Job has exhausted retries (Failed count: $FAILED_COUNT)"
        
        # Wait a bit for controller to process
        sleep 5
        
        SI_STATUS=$(kubectl get scaninstance test-retry-si -o jsonpath='{.status.status}')
        echo "Final ScanInstance status: $SI_STATUS"
        
        if [ "$SI_STATUS" = "Failed" ]; then
            echo "✓ SUCCESS: ScanInstance correctly marked as Failed after all retries exhausted"
        else
            echo "✗ WARNING: ScanInstance status is $SI_STATUS (expected Failed)"
        fi
        break
    fi
    
    # Check if job succeeded
    if [ "$SUCCEEDED_COUNT" -gt 0 ]; then
        echo "✓ Job succeeded!"
        break
    fi
    
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "Timeout reached. Job did not complete within ${TIMEOUT}s."
    echo "This may be expected if the scan takes longer than ${TIMEOUT}s."
fi

echo
echo "=== Verification Complete ==="
