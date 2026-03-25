#!/bin/bash
# Test script for janitor CLI

set -e

NAMESPACE="threat-scanning-system"
SCAN_INSTANCE_NAME="test-scan-instance"

echo "=== Janitor CLI Test Script ==="
echo ""

# Function to create a test ScanInstance
create_test_scaninstance() {
    echo "Creating test ScanInstance..."
    cat <<EOF | kubectl apply -f -
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: ${SCAN_INSTANCE_NAME}
spec:
  backupTarget:
    name: test-target
  backupRef:
    uid: test-uid
    path: /test/path
status:
  status: Completed
  type: TVK
  condition:
  - phase: Scanning
    status: Completed
    timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
    reason: "Scan completed successfully"
EOF
    echo "ScanInstance created: ${SCAN_INSTANCE_NAME}"
}

# Function to create test resources
create_test_resources() {
    local scan_instance=$1
    echo "Creating test resources for ScanInstance: ${scan_instance}"
    
    # Create prescan job
    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: threat-scan-prescan-${scan_instance}
  namespace: ${NAMESPACE}
  labels:
    trilio.io/scaninstance-name: ${scan_instance}
spec:
  template:
    spec:
      containers:
      - name: prescan
        image: busybox
        command: ["echo", "prescan"]
      restartPolicy: Never
EOF
    
    # Create scan job
    cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: threat-scan-scanjob-${scan_instance}
  namespace: ${NAMESPACE}
  labels:
    trilio.io/scaninstance-name: ${scan_instance}
spec:
  template:
    spec:
      containers:
      - name: scan
        image: busybox
        command: ["echo", "scan"]
      restartPolicy: Never
EOF
    
    # Create Redis deployment
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis-deploy-${scan_instance}
  namespace: ${NAMESPACE}
  labels:
    trilio.io/scaninstance-name: ${scan_instance}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
      scan-instance: ${scan_instance}
  template:
    metadata:
      labels:
        app: redis
        scan-instance: ${scan_instance}
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
EOF
    
    # Create Redis service
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: redis-svc-${scan_instance}
  namespace: ${NAMESPACE}
  labels:
    trilio.io/scaninstance-name: ${scan_instance}
spec:
  selector:
    app: redis
    scan-instance: ${scan_instance}
  ports:
  - port: 6379
    targetPort: 6379
EOF
    
    # Create scan configmap
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: scan-config-${scan_instance}
  namespace: ${NAMESPACE}
  labels:
    trilio.io/scaninstance-name: ${scan_instance}
data:
  config.json: |
    {
      "scan_locations": []
    }
EOF
    
    echo "Test resources created"
}

# Function to list resources
list_resources() {
    local scan_instance=$1
    echo ""
    echo "=== Current resources for ${scan_instance} ==="
    echo ""
    echo "Jobs:"
    kubectl get jobs -n ${NAMESPACE} -l trilio.io/scaninstance-name=${scan_instance} 2>/dev/null || echo "  None found"
    echo ""
    echo "Deployments:"
    kubectl get deployments -n ${NAMESPACE} -l trilio.io/scaninstance-name=${scan_instance} 2>/dev/null || echo "  None found"
    echo ""
    echo "Services:"
    kubectl get services -n ${NAMESPACE} -l trilio.io/scaninstance-name=${scan_instance} 2>/dev/null || echo "  None found"
    echo ""
    echo "ConfigMaps:"
    kubectl get configmaps -n ${NAMESPACE} -l trilio.io/scaninstance-name=${scan_instance} 2>/dev/null || echo "  None found"
    echo ""
}

# Function to test dry-run
test_dry_run() {
    echo "=== Test 1: Dry Run Mode ==="
    echo "Running janitor in dry-run mode..."
    echo ""
    go run ./cmd/janitor/main.go --scan-instance=${SCAN_INSTANCE_NAME} --status=Available --dry-run
    echo ""
    echo "Checking resources still exist..."
    list_resources ${SCAN_INSTANCE_NAME}
}

# Function to test cleanup
test_cleanup() {
    echo "=== Test 2: Actual Cleanup ==="
    echo "Running janitor to cleanup resources..."
    echo ""
    go run ./cmd/janitor/main.go --scan-instance=${SCAN_INSTANCE_NAME} --status=Available
    echo ""
    echo "Waiting for cleanup to complete..."
    sleep 5
    echo ""
    echo "Checking resources after cleanup..."
    list_resources ${SCAN_INSTANCE_NAME}
}

# Function to test failed ScanInstance cleanup
test_failed_cleanup() {
    local failed_scan="test-failed-scan"
    echo "=== Test 3: Failed ScanInstance Cleanup ==="
    echo ""
    
    # Create a failed ScanInstance
    echo "Creating failed ScanInstance..."
    cat <<EOF | kubectl apply -f -
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: ${failed_scan}
spec:
  backupTarget:
    name: test-target
  backupRef:
    uid: test-uid
    path: /test/path
status:
  status: Failed
  type: TVK
  condition:
  - phase: Scanning
    status: Failed
    timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
    reason: "Scan failed"
EOF
    
    # Create test resources
    create_test_resources ${failed_scan}
    
    echo ""
    echo "Resources before cleanup:"
    list_resources ${failed_scan}
    
    echo "Running janitor for failed ScanInstances..."
    echo ""
    go run ./cmd/janitor/main.go --scan-instance=${failed_scan} --status=Failed
    
    echo ""
    echo "Waiting for cleanup to complete..."
    sleep 5
    
    echo ""
    echo "Resources after cleanup (Redis should be deleted, jobs retained for <3 days):"
    list_resources ${failed_scan}
    
    # Cleanup
    kubectl delete scaninstance ${failed_scan} 2>/dev/null || true
}

# Function to cleanup test resources
cleanup() {
    echo ""
    echo "=== Cleaning up test resources ==="
    kubectl delete scaninstance ${SCAN_INSTANCE_NAME} 2>/dev/null || true
    kubectl delete jobs -n ${NAMESPACE} -l trilio.io/scaninstance-name=${SCAN_INSTANCE_NAME} 2>/dev/null || true
    kubectl delete deployments -n ${NAMESPACE} -l trilio.io/scaninstance-name=${SCAN_INSTANCE_NAME} 2>/dev/null || true
    kubectl delete services -n ${NAMESPACE} -l trilio.io/scaninstance-name=${SCAN_INSTANCE_NAME} 2>/dev/null || true
    kubectl delete configmaps -n ${NAMESPACE} -l trilio.io/scaninstance-name=${SCAN_INSTANCE_NAME} 2>/dev/null || true
    echo "Cleanup complete"
}

# Main test flow
main() {
    echo "Starting janitor tests..."
    echo ""
    
    # Setup
    create_test_scaninstance
    create_test_resources ${SCAN_INSTANCE_NAME}
    
    echo ""
    echo "Initial resources:"
    list_resources ${SCAN_INSTANCE_NAME}
    
    # Run tests
    test_dry_run
    test_cleanup
    test_failed_cleanup
    
    # Cleanup
    cleanup
    
    echo ""
    echo "=== All tests completed ==="
}

# Run if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
