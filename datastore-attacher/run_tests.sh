#!/bin/bash
#
# Test runner script for targetPoller unit tests
#
# Usage:
#   ./run_tests.sh                  # Run all tests
#   ./run_tests.sh cleanup          # Run only cleanup tests
#   ./run_tests.sh workers          # Run only worker tests
#   ./run_tests.sh test_cleanup.py  # Run specific test file

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  TargetPoller Unit Tests${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest not found${NC}"
    echo "Please install pytest: pip install pytest pytest-timeout pytest-cov"
    exit 1
fi

# Determine what to test
TEST_TARGET="targetPoller/tests/"
if [ ! -z "$1" ]; then
    case "$1" in
        cleanup)
            TEST_TARGET="targetPoller/tests/test_cleanup.py targetPoller/tests/test_cleanup_workers.py"
            echo -e "${YELLOW}Running cleanup tests only${NC}"
            ;;
        workers)
            TEST_TARGET="targetPoller/tests/test_cleanup_workers.py"
            echo -e "${YELLOW}Running worker tests only${NC}"
            ;;
        storage)
            TEST_TARGET="targetPoller/tests/test_storage_state.py"
            echo -e "${YELLOW}Running storage state tests only${NC}"
            ;;
        *.py)
            TEST_TARGET="targetPoller/tests/$1"
            echo -e "${YELLOW}Running specific test file: $1${NC}"
            ;;
        *)
            echo -e "${RED}Unknown test target: $1${NC}"
            echo "Valid targets: cleanup, workers, storage, or specific .py file"
            exit 1
            ;;
    esac
fi

echo ""

# Run tests
pytest $TEST_TARGET \
    -v \
    --tb=short \
    --color=yes \
    -m "not integration" \
    "$@"

TEST_EXIT_CODE=$?

echo ""
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  All tests passed! ✓${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}  Some tests failed ✗${NC}"
    echo -e "${RED}========================================${NC}"
fi

exit $TEST_EXIT_CODE
