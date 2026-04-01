#!/bin/bash
# Verification script for scan job timeout configuration

set -e

echo "=========================================="
echo "Scan Job Timeout Configuration Verification"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

NAMESPACE="${INSTALL_NAMESPACE:-threat-scanning-system}"

echo "Using namespace: $NAMESPACE"
echo ""

# Check if deployment exists
echo "1. Checking if controller deployment exists..."
if kubectl get deployment threat-scanning-controller-manager -n "$NAMESPACE" &>/dev/null; then
    echo -e "${GREEN}✓${NC} Controller deployment found"
else
    echo -e "${RED}✗${NC} Controller deployment not found in namespace $NAMESPACE"
    exit 1
fi
echo ""

# Check environment variable
echo "2. Checking SCAN_JOB_TIMEOUT_SECONDS environment variable..."
TIMEOUT=$(kubectl get deployment threat-scanning-controller-manager -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SCAN_JOB_TIMEOUT_SECONDS")].value}' 2>/dev/null || echo "")

if [ -z "$TIMEOUT" ]; then
    echo -e "${YELLOW}⚠${NC} SCAN_JOB_TIMEOUT_SECONDS not set (will use default: 1500 seconds)"
else
    echo -e "${GREEN}✓${NC} SCAN_JOB_TIMEOUT_SECONDS is set to: $TIMEOUT seconds ($((TIMEOUT / 60)) minutes)"
fi
echo ""

# Check controller pod status
echo "3. Checking controller pod status..."
POD_STATUS=$(kubectl get pods -n "$NAMESPACE" -l control-plane=controller-manager \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")

if [ "$POD_STATUS" = "Running" ]; then
    echo -e "${GREEN}✓${NC} Controller pod is running"
    POD_NAME=$(kubectl get pods -n "$NAMESPACE" -l control-plane=controller-manager \
        -o jsonpath='{.items[0].metadata.name}')
    echo "   Pod name: $POD_NAME"
else
    echo -e "${YELLOW}⚠${NC} Controller pod status: $POD_STATUS"
fi
echo ""

# Check for recent ScanTimeout events
echo "4. Checking for recent ScanTimeout events (last 1 hour)..."
TIMEOUT_EVENTS=$(kubectl get events -n "$NAMESPACE" --field-selector reason=ScanTimeout \
    -o json 2>/dev/null | jq -r '.items | length' 2>/dev/null || echo "0")

if [ "$TIMEOUT_EVENTS" = "0" ]; then
    echo -e "${GREEN}✓${NC} No recent scan timeout events"
else
    echo -e "${YELLOW}⚠${NC} Found $TIMEOUT_EVENTS scan timeout event(s) in the last hour"
    echo "   Run: kubectl get events -n $NAMESPACE --field-selector reason=ScanTimeout"
fi
echo ""

# Check for active scan jobs
echo "5. Checking for active scan jobs..."
SCAN_JOBS=$(kubectl get jobs -n "$NAMESPACE" -l app.kubernetes.io/component=scan \
    -o json 2>/dev/null | jq -r '.items | length' 2>/dev/null || echo "0")

if [ "$SCAN_JOBS" = "0" ]; then
    echo -e "${GREEN}✓${NC} No active scan jobs found"
else
    echo -e "${GREEN}✓${NC} Found $SCAN_JOBS scan job(s)"
    echo ""
    echo "   Job details:"
    kubectl get jobs -n "$NAMESPACE" -l app.kubernetes.io/component=scan \
        -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[0].type,DURATION:.status.startTime
fi
echo ""

# Show all environment variables related to timeouts
echo "6. Showing all timeout-related configurations..."
echo "   Environment variables in controller:"
kubectl get deployment threat-scanning-controller-manager -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[0].env[*]}' 2>/dev/null | \
    jq -r '. | select(.name | contains("TIMEOUT") or contains("DEADLINE"))' 2>/dev/null || \
    echo "   SCAN_JOB_TIMEOUT_SECONDS: ${TIMEOUT:-not set}"
echo ""

# Summary
echo "=========================================="
echo "Verification Summary"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  • Namespace: $NAMESPACE"
echo "  • Scan Job Timeout: ${TIMEOUT:-1500 (default)} seconds ($((${TIMEOUT:-1500} / 60)) minutes)"
echo "  • Controller Status: $POD_STATUS"
echo "  • Active Scan Jobs: $SCAN_JOBS"
echo "  • Recent Timeout Events: $TIMEOUT_EVENTS"
echo ""

# Recommendations
if [ -z "$TIMEOUT" ]; then
    echo -e "${YELLOW}Recommendation:${NC} Set SCAN_JOB_TIMEOUT_SECONDS explicitly in deployment"
    echo "  kubectl edit deployment threat-scanning-controller-manager -n $NAMESPACE"
    echo ""
fi

if [ "$TIMEOUT_EVENTS" != "0" ]; then
    echo -e "${YELLOW}Recommendation:${NC} Review timeout events and consider increasing SCAN_JOB_TIMEOUT_SECONDS"
    echo "  Current: ${TIMEOUT:-1500}s, Suggested: $((${TIMEOUT:-1500} * 2))s"
    echo ""
fi

echo "For more information, see:"
echo "  • SCAN_JOB_TIMEOUT_CONFIG.md - Comprehensive documentation"
echo "  • SCAN_JOB_TIMEOUT_QUICK_REF.md - Quick reference"
echo "  • SCAN_JOB_TIMEOUT_IMPLEMENTATION_SUMMARY.md - Implementation details"
echo ""

echo -e "${GREEN}Verification complete!${NC}"
