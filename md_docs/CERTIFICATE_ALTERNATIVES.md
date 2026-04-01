# Certificate Management Alternatives for Webhooks

## What Trilio Uses

**Trilio k8s-triliovault uses runtime certificate generation** - certificates are generated programmatically by the controller at startup using Go's crypto libraries. This approach:

✅ No external dependencies (no cert-manager needed)
✅ Self-contained solution
✅ Certificates generated on-demand
✅ Automatic CA bundle injection into webhook configurations

### Trilio's Approach

The k8s-triliovault project generates TLS certificates at runtime in the `webhook-init` container:

```go
// From k8s-triliovault/internal/commons.go
func GenerateTLSCerts(commonName string, dnsNames []string) (caPEM, serverCertPEM, serverPrivKeyPEM *bytes.Buffer)
```

Process:
1. **Init container** runs before the main webhook server
2. Generates self-signed CA certificate
3. Generates server certificate signed by the CA
4. Stores certificates in a Kubernetes Secret
5. Patches the webhook configurations with the CA bundle
6. Main container mounts the secret and uses the certificates

## Alternative Approaches for Certificate Management

### Option 1: Runtime Certificate Generation (Trilio's Approach) ⭐ **RECOMMENDED**

**Pros:**
- ✅ No external dependencies
- ✅ Self-contained and portable
- ✅ Works in air-gapped environments
- ✅ Automatic CA bundle management
- ✅ No additional installation required

**Cons:**
- ⚠️ Requires init container or startup logic
- ⚠️ Needs RBAC to patch webhook configurations
- ⚠️ Certificates expire after 1 year (need rotation logic)

**Implementation:**
```yaml
# Init container in deployment
initContainers:
- name: webhook-cert-init
  image: threat-scanning-controller:latest
  command: ["/manager"]
  args: ["--init-certs-only"]
  # Generates certs and updates webhook configurations
```

### Option 2: cert-manager (What I Provided)

**Pros:**
- ✅ Industry standard solution
- ✅ Automatic certificate renewal
- ✅ Support for multiple CA providers
- ✅ Well-documented and widely used

**Cons:**
- ❌ External dependency (requires cert-manager installed)
- ❌ Additional complexity
- ❌ Not suitable for air-gapped environments without pre-installing cert-manager

### Option 3: Manual Certificate Generation (Simplest)

**Pros:**
- ✅ Very simple
- ✅ No dependencies
- ✅ Full control over certificates

**Cons:**
- ❌ Manual process
- ❌ No automatic renewal
- ❌ Need to manually update CA bundle
- ❌ Certificates expire (need manual renewal)

**Implementation:**
```bash
# Generate using our script
./hack/generate-webhook-certs.sh

# Create secret
kubectl create secret tls threat-scanning-webhook-certs \
  --cert=config/webhook/certs/tls.crt \
  --key=config/webhook/certs/tls.key \
  -n threat-scanning-system

# Manually inject CA bundle
kubectl patch validatingwebhookconfiguration ...
```

### Option 4: Kubernetes CSR API

**Pros:**
- ✅ Native Kubernetes feature
- ✅ No external dependencies
- ✅ Certificates signed by cluster CA

**Cons:**
- ⚠️ Requires manual approval of CSR
- ⚠️ More complex setup
- ⚠️ Not all clusters have this enabled

### Option 5: External Secret Management (Vault, AWS Secrets Manager, etc.)

**Pros:**
- ✅ Enterprise-grade secret management
- ✅ Audit logging
- ✅ Automatic rotation

**Cons:**
- ❌ Requires external infrastructure
- ❌ Additional cost
- ❌ Complex setup

## Recommended Approach for Threat Scanning

### **Use Runtime Certificate Generation (Like Trilio)**

This is the best approach because:

1. **No external dependencies** - Works out of the box
2. **Self-contained** - Everything in one image
3. **Production-ready** - Trilio uses this successfully
4. **Simple deployment** - No cert-manager installation needed
5. **Air-gap friendly** - Works in isolated environments

### Implementation Plan

I'll create:
1. Certificate generation logic in Go (similar to Trilio)
2. Init container that generates certificates on startup
3. Automatic CA bundle injection
4. Secret creation/update
5. Updated deployment with init container

## Comparison Table

| Feature | Runtime Gen | cert-manager | Manual | CSR API |
|---------|-------------|--------------|--------|---------|
| No dependencies | ✅ | ❌ | ✅ | ✅ |
| Auto renewal | ⚠️ Manual | ✅ | ❌ | ⚠️ | 
| Air-gap friendly | ✅ | ❌ | ✅ | ✅ |
| Setup complexity | Low | Medium | Low | High |
| Maintenance | Low | Low | High | Medium |
| Used by Trilio | ✅ | ❌ | ❌ | ❌ |

## Conclusion

For the threat-scanning-architecture project, I recommend **switching to runtime certificate generation** (Option 1) to match Trilio's approach. This provides:

- Consistency with Trilio's k8s-triliovault
- No external dependencies
- Simple deployment
- Production-ready solution

Would you like me to implement the runtime certificate generation approach (like Trilio) instead of cert-manager?
