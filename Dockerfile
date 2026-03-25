# Build the manager and janitor binaries
FROM golang:1.21 as builder
ARG TARGETOS
ARG TARGETARCH

WORKDIR /workspace
# Copy the Go Modules manifests
COPY go.mod go.mod
COPY go.sum go.sum
# cache deps before building and copying source so that we don't need to re-download as much
# and so that source changes don't invalidate our downloaded layer
RUN go mod download

# Copy the go source
COPY cmd/ cmd/
COPY api/ api/
COPY controllers/ controllers/
COPY internal/ internal/
COPY pkg/ pkg/
COPY hack/boilerplate.go.txt hack/boilerplate.go.txt

# Build manager
RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -a -o manager cmd/manager/main.go

# Build janitor
# RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -a -o janitor cmd/janitor/main.go

# Use alpine as minimal base image to package the binaries
FROM alpine:3.19
WORKDIR /
COPY --from=builder /workspace/manager .
# COPY --from=builder /workspace/janitor .

# Add ca-certificates for HTTPS connections
RUN apk --no-cache add ca-certificates

# Create non-root user
RUN addgroup -g 65532 -S nonroot && adduser -u 65532 -S nonroot -G nonroot
USER nonroot:nonroot

# The manager binary supports the following flags:
# --enable-webhook: Enable the validating webhook server (default: false)
# --webhook-port: Webhook server port (default: 9443)
# --webhook-cert-dir: Directory containing TLS certificates (default: /tmp/k8s-webhook-server/serving-certs)
# --enable-leader-election: Enable leader election for controller manager (default: false)
ENTRYPOINT ["/manager"]
