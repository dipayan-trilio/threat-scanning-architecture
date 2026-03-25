#!/bin/bash
#
# Run envtest-style integration tests for targetPoller
#
# Prerequisites:
#   - kubectl installed
#   - envtest binaries (kube-apiserver, etcd)
#   - Python kubernetes client installed
#
# Setup envtest binaries:
#   go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest
#   setup-envtest use
#
# This script:
#   1. Checks prerequisites (binaries, kubectl)
#   2. Runs integration tests (tests start binaries themselves)
#   3. Tests cleanup processes automatically

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  TargetPoller EnvTest Integration${NC}"
echo -e "${GREEN}  (API Server + etcd binaries)${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Function to check prerequisites
check_prerequisites() {
    echo -e "${BLUE}Checking prerequisites...${NC}"
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}Error: kubectl not found${NC}"
        echo "Please install kubectl"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} kubectl found: $(kubectl version --client --short 2>/dev/null || kubectl version --client 2>&1 | head -1)"
    
    # Check for envtest binaries
    BINARIES_FOUND=false
    
    # Check KUBEBUILDER_ASSETS
    if [ -n "$KUBEBUILDER_ASSETS" ] && [ -f "$KUBEBUILDER_ASSETS/kube-apiserver" ]; then
        echo -e "  ${GREEN}✓${NC} envtest binaries found at \$KUBEBUILDER_ASSETS"
        BINARIES_FOUND=true
    fi
    
    # Check ~/.local/share/kubebuilder-envtest/
    if [ "$BINARIES_FOUND" = "false" ]; then
        ENVTEST_DIR="$HOME/.local/share/kubebuilder-envtest/k8s"
        if [ -d "$ENVTEST_DIR" ]; then
            # Find latest version
            LATEST=$(find "$ENVTEST_DIR" -type f -name "kube-apiserver" | head -1)
            if [ -n "$LATEST" ]; then
                BINARY_DIR=$(dirname "$LATEST")
                export KUBEBUILDER_ASSETS="$BINARY_DIR"
                echo -e "  ${GREEN}✓${NC} envtest binaries found at $BINARY_DIR"
                BINARIES_FOUND=true
            fi
        fi
    fi
    
    # Check /usr/local/kubebuilder/bin/
    if [ "$BINARIES_FOUND" = "false" ] && [ -f "/usr/local/kubebuilder/bin/kube-apiserver" ]; then
        export KUBEBUILDER_ASSETS="/usr/local/kubebuilder/bin"
        echo -e "  ${GREEN}✓${NC} envtest binaries found at /usr/local/kubebuilder/bin"
        BINARIES_FOUND=true
    fi
    
    if [ "$BINARIES_FOUND" = "false" ]; then
        echo -e "${RED}Error: envtest binaries not found${NC}"
        echo ""
        echo "Please install envtest binaries:"
        echo "  1. Install setup-envtest:"
        echo "     go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest"
        echo "  2. Download binaries:"
        echo "     setup-envtest use"
        echo ""
        echo "OR set KUBEBUILDER_ASSETS to path containing kube-apiserver and etcd binaries"
        exit 1
    fi
    
    # Check Python and kubernetes module
    if ! python3 -c "import kubernetes" 2>/dev/null; then
        echo -e "${YELLOW}Warning: kubernetes Python module not found${NC}"
        echo "Installing kubernetes module..."
        pip3 install kubernetes boto3
    fi
    echo -e "  ${GREEN}✓${NC} Python kubernetes module available"
    
    echo ""
}

# Function to run tests  
run_tests() {
    echo -e "${BLUE}Running integration tests...${NC}"
    echo -e "${BLUE}(Tests will start API server + etcd binaries)${NC}"
    echo ""
    
    # Run tests (they handle starting/stopping processes)
    # Don't filter by marker - test file is specifically for envtest
    python3 -m pytest targetPoller/tests/test_cleanup_envtest.py \
        -v \
        --tb=short \
        --color=yes \
        "$@"
    
    TEST_EXIT_CODE=$?
    echo ""
    
    return $TEST_EXIT_CODE
}

# Main execution
main() {
    check_prerequisites
    
    # Run tests
    if run_tests "$@"; then
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  All integration tests passed! ✓${NC}"
        echo -e "${GREEN}========================================${NC}"
        TEST_EXIT=0
    else
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}  Some integration tests failed ✗${NC}"
        echo -e "${RED}========================================${NC}"
        TEST_EXIT=1
    fi
    
    echo ""
    
    exit $TEST_EXIT
}

main "$@"
