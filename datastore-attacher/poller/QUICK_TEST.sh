#!/bin/bash

# Quick Test Script for Threat Scanning Poller
# Usage: ./QUICK_TEST.sh <target-name> [lookback-hours]

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check arguments
if [ -z "$1" ]; then
    echo -e "${RED}Error: Target name required${NC}"
    echo "Usage: $0 <target-name> [lookback-hours]"
    echo ""
    echo "Examples:"
    echo "  $0 my-backup-target           # Use default 6 hours lookback"
    echo "  $0 my-backup-target 24        # Use 24 hours lookback for testing"
    echo "  $0 my-backup-target 168       # Use 7 days lookback for testing"
    exit 1
fi

TARGET_NAME="$1"
LOOKBACK_HOURS="${2:-6}"  # Default to 6 if not provided

echo -e "${GREEN}=========================================="
echo "Threat Scanning Poller - Quick Test"
echo -e "==========================================${NC}"
echo ""

# Configuration
export BACKUP_TARGET_NAME="$TARGET_NAME"
export CRONJOB_NAME="poller-$TARGET_NAME"
export CRONJOB_NAMESPACE="default"
export DISCOVERY_LOOKBACK_HOURS="$LOOKBACK_HOURS"
export LOG_LEVEL="DEBUG"
export VM_MOUNT="true"

echo "Configuration:"
echo "  Target: $BACKUP_TARGET_NAME"
echo "  CronJob: $CRONJOB_NAME"
echo "  Namespace: $CRONJOB_NAMESPACE"
echo -e "  Lookback: ${YELLOW}$DISCOVERY_LOOKBACK_HOURS hours${NC}"
echo "  Log Level: $LOG_LEVEL"
echo ""

# Verify kubectl access
echo -e "${YELLOW}Verifying kubectl access...${NC}"
if kubectl get targets "$BACKUP_TARGET_NAME" &> /dev/null; then
    echo -e "${GREEN}✓ Target '$BACKUP_TARGET_NAME' found${NC}"
else
    echo -e "${RED}✗ Target '$BACKUP_TARGET_NAME' not found${NC}"
    echo ""
    echo "Available targets:"
    kubectl get targets
    exit 1
fi
echo ""

# Check if running as root (needed for NFS mount)
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Warning: Not running as root. NFS mounting may fail.${NC}"
    echo -e "${YELLOW}Consider running: sudo -E $0 $@${NC}"
    echo ""
fi

# Run the poller
echo -e "${GREEN}Running poller...${NC}"
echo "=========================================="
cd "$(dirname "$0")/.."
python3 poller/main.py

EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Test completed successfully${NC}"
else
    echo -e "${RED}✗ Test failed with exit code $EXIT_CODE${NC}"
fi
echo "=========================================="

exit $EXIT_CODE

