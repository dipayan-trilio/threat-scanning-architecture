#!/bin/bash
#
# Setup script for running targetPoller tests
#
# This script installs minimal dependencies needed for unit tests.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  Installing Test Dependencies"
echo "========================================="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION"
echo ""

# Install dependencies
echo "Installing test dependencies..."
pip3 install -r requirements-test.txt

echo ""
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo ""
echo "You can now run tests:"
echo "  ./run_tests.sh              # All tests (pytest)"
echo "  python3 run_unittest.py     # All tests (unittest)"
echo "  python3 run_unittest.py test_storage_state  # Specific module"
echo ""
