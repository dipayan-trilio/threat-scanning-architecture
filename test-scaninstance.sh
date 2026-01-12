#!/bin/bash

# Test script for ScanInstance controller
# This script helps test the ScanInstance controller with placeholder implementation

set -e

NAMESPACE="${INSTALL_NAMESPACE:-threat-scanning-system}"
SCAN_INSTANCE_NAME="${1:-sample-scan-instance}"
TARGET_NAME="${2:-sample-target}"

echo "=========================================="
echo "ScanInstance Controller Test Script"
echo "=========================================="
echo "Namespace: $NAMESPACE"
echo "ScanInstance: $SCAN_INSTANCE_NAME"
echo "Target: $TARGET_NAME"
echo ""

# Function to wait for condition
wait_for_condition() {
    local resource=$1
    local name=$2
    local condition=$3
    local timeout=${4:-300}
    
    echo "Waiting for $resource/$name to meet condition: $condition (timeout: ${timeout}s)"
    kubectl wait --for=condition="$condition" "$resource/$name" --timeout="${timeout}s" 2>/dev/null || true
}

# Function to get status
get_status() {
    local resource=$1
    local name=$2
    local jsonpath=$3
    
    kubectl get "$resource" "$name" -o jsonpath="$jsonpath" 2>/dev/null || echo "N/A"
}

# Step 1: Check if CRD is installed
echo "Step 1: Checking if ScanInstance CRD is installed..."
if kubectl get crd scaninstances.threatscanning.trilio.io &>/dev/null; then
    echo "✓ ScanInstance CRD is installed"
else
    echo "✗ ScanInstance CRD not found. Installing..."
    kubectl apply -f config/crd/bases/threatscanning.trilio.io_scaninstances.yaml
    echo "✓ ScanInstance CRD installed"
fi
echo ""

# Step 2: Check if target exists and is available
echo "Step 2: Checking if target exists and is available..."
if kubectl get target "$TARGET_NAME" &>/dev/null; then
    TARGET_STATUS=$(get_status "target" "$TARGET_NAME" "{.status.status}")
    echo "✓ Target '$TARGET_NAME' exists (Status: $TARGET_STATUS)"
    
    if [ "$TARGET_STATUS" != "Available" ]; then
        echo "⚠ Warning: Target is not Available. ScanInstance will wait for target to become available."
        echo "  You can check target status with: kubectl get target $TARGET_NAME -o yaml"
    fi
else
    echo "✗ Target '$TARGET_NAME' not found!"
    echo "  Please create a target first. Example:"
    echo "  kubectl apply -f config/samples/threatscanning_v1_target_s3.yaml"
    exit 1
fi
echo ""

# Step 3: Create or check ScanInstance
echo "Step 3: Creating/checking ScanInstance..."
if kubectl get scaninstance "$SCAN_INSTANCE_NAME" &>/dev/null; then
    echo "✓ ScanInstance '$SCAN_INSTANCE_NAME' already exists"
    SCAN_STATUS=$(get_status "scaninstance" "$SCAN_INSTANCE_NAME" "{.status.status}")
    echo "  Current Status: $SCAN_STATUS"
else
    echo "Creating ScanInstance '$SCAN_INSTANCE_NAME'..."
    
    # Create a temporary ScanInstance YAML
    cat > /tmp/test-scaninstance.yaml <<EOF
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: $SCAN_INSTANCE_NAME
spec:
  backupTarget:
    apiVersion: threatscanning.trilio.io/v1
    kind: Target
    name: $TARGET_NAME
    resourceVersion: "12345"
    uid: "test-target-uid"
  backupRef:
    uid: "test-backup-uid"
    path: "/backups/test-backup"
EOF
    
    kubectl apply -f /tmp/test-scaninstance.yaml
    echo "✓ ScanInstance created"
    rm -f /tmp/test-scaninstance.yaml
fi
echo ""

# Step 4: Monitor ScanInstance progress
echo "Step 4: Monitoring ScanInstance progress..."
echo "Press Ctrl+C to stop monitoring"
echo ""

for i in {1..60}; do
    SCAN_STATUS=$(get_status "scaninstance" "$SCAN_INSTANCE_NAME" "{.status.status}")
    SCAN_TYPE=$(get_status "scaninstance" "$SCAN_INSTANCE_NAME" "{.status.type}")
    
    echo "[$i/60] Status: $SCAN_STATUS | Type: $SCAN_TYPE"
    
    # Check for pre-scan job
    PRESCAN_JOB="threat-scan-prescan-$SCAN_INSTANCE_NAME"
    if kubectl get job "$PRESCAN_JOB" -n "$NAMESPACE" &>/dev/null; then
        JOB_STATUS=$(kubectl get job "$PRESCAN_JOB" -n "$NAMESPACE" -o jsonpath='{.status.conditions[0].type}' 2>/dev/null || echo "Running")
        echo "       PreScan Job: $JOB_STATUS"
        
        # Show job logs if available
        if [ "$JOB_STATUS" = "Complete" ] || [ "$JOB_STATUS" = "Failed" ]; then
            echo "       Job Logs:"
            kubectl logs -n "$NAMESPACE" "job/$PRESCAN_JOB" --tail=5 2>/dev/null | sed 's/^/         /' || echo "         (logs not available)"
        fi
    fi
    
    # Check conditions
    CONDITIONS=$(kubectl get scaninstance "$SCAN_INSTANCE_NAME" -o jsonpath='{.status.condition[-1:].phase}:{.status.condition[-1:].status}' 2>/dev/null || echo "N/A")
    if [ "$CONDITIONS" != "N/A" ]; then
        echo "       Last Condition: $CONDITIONS"
    fi
    
    # Exit if completed or failed
    if [ "$SCAN_STATUS" = "Completed" ] || [ "$SCAN_STATUS" = "Failed" ]; then
        echo ""
        echo "=========================================="
        echo "ScanInstance reached terminal state: $SCAN_STATUS"
        echo "=========================================="
        break
    fi
    
    sleep 5
done

echo ""
echo "Step 5: Final Status"
echo "=========================================="
kubectl get scaninstance "$SCAN_INSTANCE_NAME" -o yaml | grep -A 20 "^status:"
echo ""

echo "Step 6: PreScan Job Details"
echo "=========================================="
PRESCAN_JOB="threat-scan-prescan-$SCAN_INSTANCE_NAME"
if kubectl get job "$PRESCAN_JOB" -n "$NAMESPACE" &>/dev/null; then
    kubectl get job "$PRESCAN_JOB" -n "$NAMESPACE"
    echo ""
    echo "Job Logs:"
    kubectl logs -n "$NAMESPACE" "job/$PRESCAN_JOB" 2>/dev/null || echo "(logs not available)"
else
    echo "PreScan job not found (may have been cleaned up)"
fi

echo ""
echo "=========================================="
echo "Test Complete!"
echo "=========================================="
echo ""
echo "Useful commands:"
echo "  Watch ScanInstance: kubectl get scaninstance $SCAN_INSTANCE_NAME -w"
echo "  View details: kubectl get scaninstance $SCAN_INSTANCE_NAME -o yaml"
echo "  View events: kubectl get events --field-selector involvedObject.name=$SCAN_INSTANCE_NAME"
echo "  Delete ScanInstance: kubectl delete scaninstance $SCAN_INSTANCE_NAME"

