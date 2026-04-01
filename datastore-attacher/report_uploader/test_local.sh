#!/bin/bash
#
# Quick test script for report-uploader CLI
#
# This script demonstrates how to test the report-uploader locally
# without building the Docker image.
#

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Report Uploader - Local Test Script${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Change to datastore-attacher directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo -e "${YELLOW}Step 1: Verify Python modules${NC}"
python3 -c "import sys; sys.path.insert(0, '.'); from report_uploader.uploader import ReportUploader; print('✓ ReportUploader imported successfully')"
python3 -c "import sys; sys.path.insert(0, '.'); from report_uploader import cli; print('✓ CLI module imported successfully')"

echo ""
echo -e "${YELLOW}Step 2: Run CLI with --help${NC}"
python3 -m report_uploader.cli --help

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Basic import tests passed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo -e "${YELLOW}To test with a real target:${NC}"
echo ""
echo "1. Create a test directory:"
echo "   mkdir -p /tmp/test-reports"
echo "   echo 'test data' > /tmp/test-reports/test.txt"
echo ""
echo "2. Run the uploader:"
echo "   python3 -m report_uploader.cli \\"
echo "     --target-name <your-reporting-target> \\"
echo "     --upload-directory /tmp/test-reports \\"
echo "     --object-prefix test-uploads/\$(date +%Y%m%d)"
echo ""
echo "3. Verify in S3:"
echo "   aws s3 ls s3://<bucket-name>/test-uploads/"
echo ""

echo -e "${YELLOW}To run unit tests:${NC}"
echo "   python3 -m pytest report_uploader/tests/ -v"
echo ""
