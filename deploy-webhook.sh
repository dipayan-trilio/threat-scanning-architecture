#!/bin/bash

# Threat Scanning Controller - Webhook Deployment Script
# This script automates the deployment of the threat-scanning controller with webhooks

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="threat-scanning-system"
IMG="${IMG:-eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest}"
USE_CERT_MANAGER="${USE_CERT_MANAGER:-false}"  # Changed default to false (Trilio's approach)

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prereqs() {
    log_info "Checking prerequisites..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl first."
        exit 1
    fi
    
    # Check docker (only if building)
    if [ "$BUILD_IMAGE" = "true" ]; then
        if ! command -v docker &> /dev/null; then
            log_error "docker not found. Please install docker first."
            exit 1
        fi
    fi
    
    # Check cluster access
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster. Please check your kubeconfig."
        exit 1
    fi
    
    log_info "Prerequisites check passed ✓"
}

install_cert_manager() {
    if [ "$USE_CERT_MANAGER" = "true" ]; then
        log_info "Checking if cert-manager is installed..."
        
        if kubectl get namespace cert-manager &> /dev/null; then
            log_info "cert-manager already installed ✓"
        else
            log_warn "cert-manager not found. Installing..."
            kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
            
            log_info "Waiting for cert-manager to be ready..."
            kubectl wait --for=condition=Ready pods --all -n cert-manager --timeout=300s || {
                log_error "cert-manager installation timed out"
                exit 1
            }
            log_info "cert-manager installed successfully ✓"
        fi
    fi
}

build_and_push_image() {
    if [ "$BUILD_IMAGE" = "true" ]; then
        log_info "Building Docker image: ${IMG}..."
        make docker-build IMG=${IMG}
        
        log_info "Pushing Docker image to registry..."
        docker push ${IMG}
        
        log_info "Image built and pushed successfully ✓"
    else
        log_info "Skipping image build (using existing image: ${IMG})"
    fi
}

install_crds() {
    log_info "Installing CRDs..."
    kubectl apply -f config/crd/bases
    log_info "CRDs installed ✓"
}

install_rbac() {
    log_info "Installing RBAC resources..."
    kubectl apply -f config/rbac/service_account.yaml
    kubectl apply -f config/rbac/role.yaml
    kubectl apply -f config/rbac/role_binding.yaml
    kubectl apply -f config/rbac/leader_election_role.yaml
    kubectl apply -f config/rbac/leader_election_role_binding.yaml
    log_info "RBAC resources installed ✓"
}

deploy_webhook() {
    log_info "Deploying webhook resources..."
    
    if [ "$USE_CERT_MANAGER" = "true" ]; then
        # Deploy with cert-manager
        kubectl apply -f config/webhook/manifests.yaml
        
        log_info "Waiting for certificate to be ready..."
        kubectl wait --for=condition=Ready certificate/threat-scanning-webhook-cert \
            -n ${NAMESPACE} --timeout=120s || {
            log_warn "Certificate not ready yet, continuing anyway..."
        }
    else:
        # Deploy without cert-manager (Trilio's approach - runtime certificate generation)
        log_info "Deploying with runtime certificate generation (Trilio's approach)..."
        kubectl apply -f config/webhook/manifests-no-cert-manager.yaml
        
        log_info "Init container will generate certificates automatically on startup"
    fi
    
    log_info "Webhook resources deployed ✓"
}

wait_for_deployment() {
    log_info "Waiting for deployment to be ready..."
    kubectl wait --for=condition=Available deployment/threat-scanning-controller \
        -n ${NAMESPACE} --timeout=300s || {
        log_error "Deployment not ready"
        kubectl get pods -n ${NAMESPACE}
        kubectl logs -n ${NAMESPACE} -l app.kubernetes.io/name=threat-scanning --tail=50
        exit 1
    }
    log_info "Deployment ready ✓"
}

verify_deployment() {
    log_info "Verifying deployment..."
    
    # Check pod status
    POD_STATUS=$(kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=threat-scanning -o jsonpath='{.items[0].status.phase}')
    if [ "$POD_STATUS" != "Running" ]; then
        log_error "Pod is not running. Status: ${POD_STATUS}"
        kubectl describe pods -n ${NAMESPACE} -l app.kubernetes.io/name=threat-scanning
        exit 1
    fi
    
    # Check webhook configurations
    if ! kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration &> /dev/null; then
        log_error "ValidatingWebhookConfiguration not found"
        exit 1
    fi
    
    if ! kubectl get mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration &> /dev/null; then
        log_error "MutatingWebhookConfiguration not found"
        exit 1
    fi
    
    log_info "Deployment verification passed ✓"
}

show_status() {
    log_info "Deployment Status:"
    echo ""
    echo "Pods:"
    kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=threat-scanning
    echo ""
    echo "Service:"
    kubectl get svc -n ${NAMESPACE} threat-scanning-webhook-service
    echo ""
    if [ "$USE_CERT_MANAGER" = "true" ]; then
        echo "Certificate:"
        kubectl get certificate -n ${NAMESPACE}
        echo ""
    fi
    echo "Webhook Configurations:"
    kubectl get validatingwebhookconfiguration threat-scanning-validating-webhook-configuration
    kubectl get mutatingwebhookconfiguration threat-scanning-mutating-webhook-configuration
}

print_next_steps() {
    log_info "Deployment completed successfully! 🎉"
    echo ""
    echo "Next steps:"
    echo "  1. View logs: kubectl logs -n ${NAMESPACE} -l app.kubernetes.io/name=threat-scanning -f"
    echo "  2. Test webhooks: See WEBHOOK_QUICK_TEST_GUIDE.md"
    echo "  3. Create a Target: kubectl apply -f config/samples/minio-target.yaml"
    echo ""
    echo "Useful commands:"
    echo "  - Check webhook status: kubectl get pods -n ${NAMESPACE}"
    echo "  - View webhook logs: make webhook-logs"
    echo "  - Update deployment: kubectl apply -f config/webhook/deployment.yaml"
}

# Main execution
main() {
    echo "========================================"
    echo "Threat Scanning Webhook Deployment"
    echo "========================================"
    echo ""
    
    check_prereqs
    install_cert_manager
    build_and_push_image
    install_crds
    install_rbac
    deploy_webhook
    wait_for_deployment
    verify_deployment
    
    echo ""
    show_status
    echo ""
    print_next_steps
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD_IMAGE="true"
            shift
            ;;
        --no-cert-manager)
            USE_CERT_MANAGER="false"
            shift
            ;;
        --image)
            IMG="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build              Build and push Docker image"
            echo "  --no-cert-manager    Don't use cert-manager (use manual certificates)"
            echo "  --image IMAGE        Specify custom image (default: ${IMG})"
            echo "  --help               Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Deploy with existing image"
            echo "  $0 --build                            # Build, push, and deploy"
            echo "  $0 --no-cert-manager                  # Deploy without cert-manager"
            echo "  $0 --build --image myregistry/img:v1  # Use custom image"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Run main
main
