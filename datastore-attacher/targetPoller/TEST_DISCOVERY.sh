#!/bin/bash
#
# Quick test script for targetPoller backup discovery
#
# Usage:
#   ./TEST_DISCOVERY.sh <target-name>
#
# Example:
#   ./TEST_DISCOVERY.sh my-backup-target
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if target name provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: Target name is required${NC}"
    echo ""
    echo "Usage:"
    echo "  $0 <target-name>"
    echo ""
    echo "Example:"
    echo "  $0 my-backup-target"
    exit 1
fi

TARGET_NAME="$1"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Target Poller - Discovery Test${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Target: ${YELLOW}${TARGET_NAME}${NC}"
echo ""

# Set environment variables
export TARGET_NAME="${TARGET_NAME}"
export TARGET_NAMESPACE="${TARGET_NAMESPACE:-trilio-system}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export VM_MOUNT="true"  # For local development

# Change to script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Run test
python3 test_discovery.py

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Test completed successfully${NC}"
else
    echo ""
    echo -e "${RED}✗ Test failed with exit code: ${exit_code}${NC}"
fi

exit $exit_code

