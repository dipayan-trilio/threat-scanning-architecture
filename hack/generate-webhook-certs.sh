#!/bin/bash

# Script to generate self-signed certificates for webhook server
# This is for development/testing purposes only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="${SCRIPT_DIR}/../config/webhook/certs"

# Create certs directory if it doesn't exist
mkdir -p "${CERT_DIR}"

echo "Generating self-signed certificates for webhook server..."

# Generate CA key and certificate
openssl genrsa -out "${CERT_DIR}/ca.key" 2048
openssl req -x509 -new -nodes -key "${CERT_DIR}/ca.key" -subj "/CN=threat-scanning-ca" -days 365 -out "${CERT_DIR}/ca.crt"

# Generate server key
openssl genrsa -out "${CERT_DIR}/tls.key" 2048

# Create certificate signing request
cat > "${CERT_DIR}/csr.conf" <<EOF
[req]
req_extensions = v3_req
distinguished_name = req_distinguished_name
[req_distinguished_name]
[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = threat-scanning-webhook-service
DNS.2 = threat-scanning-webhook-service.threat-scanning-system
DNS.3 = threat-scanning-webhook-service.threat-scanning-system.svc
DNS.4 = threat-scanning-webhook-service.threat-scanning-system.svc.cluster.local
EOF

# Generate certificate signing request
openssl req -new -key "${CERT_DIR}/tls.key" -subj "/CN=threat-scanning-webhook-service.threat-scanning-system.svc" -out "${CERT_DIR}/server.csr" -config "${CERT_DIR}/csr.conf"

# Sign the certificate with CA
openssl x509 -req -in "${CERT_DIR}/server.csr" -CA "${CERT_DIR}/ca.crt" -CAkey "${CERT_DIR}/ca.key" -CAcreateserial -out "${CERT_DIR}/tls.crt" -days 365 -extensions v3_req -extfile "${CERT_DIR}/csr.conf"

# Clean up intermediate files
rm "${CERT_DIR}/server.csr" "${CERT_DIR}/csr.conf" "${CERT_DIR}/ca.srl"

echo "Certificates generated successfully in ${CERT_DIR}"
echo ""
echo "To create Kubernetes secret, run:"
echo "kubectl create secret tls threat-scanning-webhook-certs \\"
echo "  --cert=${CERT_DIR}/tls.crt \\"
echo "  --key=${CERT_DIR}/tls.key \\"
echo "  -n threat-scanning-system"
echo ""
echo "To inject CA bundle into webhook configurations, run:"
echo "export CA_BUNDLE=\$(cat ${CERT_DIR}/ca.crt | base64 | tr -d '\n')"
echo "Then update the webhook configurations with the CA bundle"
