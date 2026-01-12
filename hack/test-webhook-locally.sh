#!/bin/bash

set -e

echo "=== Testing Threat Scanning Webhook Locally ==="
echo

# Step 1: Generate certificates
echo "Step 1: Generating self-signed certificates..."
CERT_DIR="/tmp/k8s-webhook-server/serving-certs"
mkdir -p "${CERT_DIR}"

openssl req -x509 -newkey rsa:4096 \
  -keyout "${CERT_DIR}/tls.key" \
  -out "${CERT_DIR}/tls.crt" \
  -days 365 -nodes \
  -subj "/CN=threat-scanning-webhook-service.threat-scanning-system.svc" \
  2>/dev/null

echo "✓ Certificates generated at ${CERT_DIR}"
echo

# Step 2: Get CA bundle
echo "Step 2: Extracting CA bundle..."
CA_BUNDLE=$(cat "${CERT_DIR}/tls.crt" | base64 | tr -d '\n')
echo "✓ CA bundle extracted"
echo

# Step 3: Create webhook configuration
echo "Step 3: Creating ValidatingWebhookConfiguration..."
cat <<EOF | kubectl apply -f -
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: threat-scanning-validating-webhook
  labels:
    app.kubernetes.io/name: threat-scanning
webhooks:
  - name: target-validation.threatscanning.trilio.io
    admissionReviewVersions:
      - v1
    clientConfig:
      # For local testing, you'll need to update this to your actual webhook URL
      # Option 1: Use ngrok or similar to expose localhost
      # Option 2: Run webhook inside cluster
      service:
        name: threat-scanning-webhook-service
        namespace: threat-scanning-system
        path: /validate-threatscanning-trilio-io-v1-target
        port: 443
      caBundle: ${CA_BUNDLE}
    failurePolicy: Fail
    matchPolicy: Equivalent
    rules:
      - apiGroups:
          - threatscanning.trilio.io
        apiVersions:
          - v1
        operations:
          - CREATE
          - UPDATE
        resources:
          - targets
        scope: "Cluster"
    sideEffects: None
    timeoutSeconds: 10
EOF

echo "✓ ValidatingWebhookConfiguration created"
echo

echo "=== Setup Complete ==="
echo
echo "Next steps:"
echo "1. Build the controller:"
echo "   go build -o bin/manager cmd/manager/main.go"
echo
echo "2. Run the webhook locally:"
echo "   ./bin/manager --enable-webhook --webhook-port=9443 --webhook-cert-dir=${CERT_DIR}"
echo
echo "3. For the webhook to work from your cluster, you need to either:"
echo "   a) Deploy the controller as a pod in the cluster with a Service"
echo "   b) Use a tunnel like ngrok to expose your local webhook:"
echo "      ngrok http 9443"
echo "      Then update the webhook configuration with the ngrok URL"
echo
echo "4. Test with sample targets in config/samples/"
echo
echo "To run unit tests instead:"
echo "   go test ./pkg/webhook/target/... -v"


