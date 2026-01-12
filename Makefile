# Image URL to use all building/pushing image targets
IMG ?= threat-scanning-controller:latest
WEBHOOK_IMG ?= eu.gcr.io/amazing-chalice-243510/threat-scanning-webhook:latest

# Get the currently used golang install path (in GOPATH/bin, unless GOBIN is set)
ifeq (,$(shell go env GOBIN))
GOBIN=$(shell go env GOPATH)/bin
else
GOBIN=$(shell go env GOBIN)
endif

# Setting SHELL to bash allows bash commands to be executed by recipes.
SHELL = /usr/bin/env bash -o pipefail
.SHELLFLAGS = -ec

.PHONY: all
all: build

##@ General

.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

.PHONY: manifests
manifests: controller-gen ## Generate WebhookConfiguration, ClusterRole and CustomResourceDefinition objects.
	$(CONTROLLER_GEN) rbac:roleName=manager-role crd paths="./..." output:crd:artifacts:config=config/crd/bases

.PHONY: generate
generate: controller-gen ## Generate code containing DeepCopy, DeepCopyInto, and DeepCopyObject method implementations.
	$(CONTROLLER_GEN) object:headerFile="hack/boilerplate.go.txt" paths="./..."

.PHONY: fmt
fmt: ## Run go fmt against code.
	go fmt ./...

.PHONY: vet
vet: ## Run go vet against code.
	go vet ./...

.PHONY: test
test: manifests generate fmt vet ## Run tests.
	go test ./... -coverprofile cover.out

##@ Build

.PHONY: build
build: generate fmt vet ## Build manager binary.
	go build -o bin/manager cmd/manager/main.go

.PHONY: run
run: manifests generate fmt vet ## Run a controller from your host.
	go run ./cmd/manager/main.go

.PHONY: docker-build
docker-build: test ## Build docker image with the manager.
	docker build -t ${IMG} .

.PHONY: docker-buildx
docker-buildx: test ## Build and push docker image for the manager for cross-platform support
	# copy existing Dockerfile and insert --platform=${BUILDPLATFORM} into Dockerfile.cross, and preserve the original Dockerfile
	sed -e '1 s/\(^FROM\)/FROM --platform=\$$\{BUILDPLATFORM\}/; t' -e ' 1,// s//FROM --platform=\$$\{BUILDPLATFORM\}/' Dockerfile > Dockerfile.cross
	- docker buildx create --name project-v3-builder
	docker buildx use project-v3-builder
	- docker buildx build --push --platform=$(PLATFORMS) --tag ${IMG} -f Dockerfile.cross .
	- docker buildx rm project-v3-builder
	rm Dockerfile.cross

.PHONY: docker-push
docker-push: ## Push docker image with the manager.
	docker push ${IMG}

##@ Webhook

.PHONY: webhook-docker-build
webhook-docker-build: test ## Build webhook docker image.
	docker build -t ${WEBHOOK_IMG} .

.PHONY: webhook-docker-push
webhook-docker-push: webhook-docker-build ## Build and push webhook docker image.
	docker push ${WEBHOOK_IMG}

.PHONY: webhook-deploy
webhook-deploy: manifests ## Deploy webhook with service and validating webhook configuration.
	@echo "Deploying webhook to Kubernetes cluster..."
	kubectl apply -f config/webhook/deployment.yaml
	kubectl apply -f config/webhook/certificate.yaml
	kubectl apply -f config/webhook/manifests.yaml
	kubectl apply -f config/rbac/service_account.yaml
	kubectl apply -f config/rbac/role.yaml
	kubectl apply -f config/rbac/role_binding.yaml
	@echo "Waiting for certificate to be ready..."
	kubectl wait --for=condition=Ready certificate/webhook-server-cert -n threat-scanning-system --timeout=60s || true
	@echo "Webhook deployment complete!"

.PHONY: webhook-undeploy
webhook-undeploy: ## Undeploy webhook from the cluster.
	@echo "Removing webhook from Kubernetes cluster..."
	kubectl delete -f config/webhook/manifests.yaml --ignore-not-found=true
	kubectl delete -f config/webhook/certificate.yaml --ignore-not-found=true
	kubectl delete -f config/webhook/deployment.yaml --ignore-not-found=true
	@echo "Webhook undeployed!"

.PHONY: webhook-build-deploy
webhook-build-deploy: webhook-docker-push webhook-deploy ## Build, push and deploy webhook (full workflow).
	@echo "Webhook build and deployment complete!"

.PHONY: webhook-logs
webhook-logs: ## Show webhook pod logs.
	kubectl logs -n threat-scanning-system -l app.kubernetes.io/name=threat-scanning -f

##@ Deployment

.PHONY: install
install: manifests ## Install CRDs into the K8s cluster specified in ~/.kube/config.
	kubectl apply -f config/crd/bases

.PHONY: uninstall
uninstall: manifests ## Uninstall CRDs from the K8s cluster specified in ~/.kube/config.
	kubectl delete -f config/crd/bases

.PHONY: deploy
deploy: manifests ## Deploy controller to the K8s cluster specified in ~/.kube/config.
	kubectl apply -f config/default

.PHONY: undeploy
undeploy: ## Undeploy controller from the K8s cluster specified in ~/.kube/config.
	kubectl delete -f config/default

##@ Build Dependencies

## Location to install dependencies to
LOCALBIN ?= $(shell pwd)/bin
$(LOCALBIN):
	mkdir -p $(LOCALBIN)

## Tool Binaries
CONTROLLER_GEN ?= $(LOCALBIN)/controller-gen

## Tool Versions
CONTROLLER_TOOLS_VERSION ?= v0.16.5

.PHONY: controller-gen
controller-gen: $(CONTROLLER_GEN) ## Download controller-gen locally if necessary.
$(CONTROLLER_GEN): $(LOCALBIN)
	GOBIN=$(LOCALBIN) go install sigs.k8s.io/controller-tools/cmd/controller-gen@$(CONTROLLER_TOOLS_VERSION)

