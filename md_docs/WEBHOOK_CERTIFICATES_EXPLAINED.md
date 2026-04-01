# Webhook Certificate Authentication - Deep Dive

## How Validating Webhooks Use Certificates

### The Problem: API Server → Webhook Communication

When you create a resource (e.g., a Target), this happens:

```
1. kubectl apply -f target.yaml
   ↓
2. API Server receives request
   ↓
3. API Server needs to call your webhook to validate
   ↓
4. PROBLEM: How does API Server trust your webhook server?
   ↓
5. SOLUTION: TLS certificates with mutual authentication
```

### TLS Mutual Authentication Flow

```
┌─────────────┐                           ┌──────────────────┐
│ API Server  │                           │ Webhook Server   │
│             │                           │ (Port 9443)      │
└─────────────┘                           └──────────────────┘
      │                                            │
      │  1. HTTPS Request (validate target)       │
      │─────────────────────────────────────────>│
      │                                            │
      │  2. Server presents certificate           │
      │<─────────────────────────────────────────│
      │     (signed by CA)                        │
      │                                            │
      │  3. API Server verifies certificate       │
      │     using CA bundle from webhook config   │
      │                                            │
      │  4. If valid: Continue                    │
      │     If invalid: REJECT                    │
      │                                            │
      │  5. Send validation request               │
      │─────────────────────────────────────────>│
      │                                            │
      │  6. Receive validation response           │
      │<─────────────────────────────────────────│
      │     (allow/deny)                          │
```

### The Three Critical Components

#### 1. CA Certificate (Certificate Authority)
- Used by API Server to verify webhook server's certificate
- Stored in the ValidatingWebhookConfiguration
- **This is the CA Bundle field**

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: threat-scanning-validating-webhook-configuration
webhooks:
- name: vtarget.threatscanning.trilio.io
  clientConfig:
    caBundle: LS0tLS1CRUdJTi...  # <-- Base64-encoded CA certificate
    service:
      name: threat-scanning-webhook-service
      namespace: threat-scanning-system
      path: /validate-threatscanning-trilio-io-v1-target
```

**What the API Server does:**
```
1. Read caBundle from ValidatingWebhookConfiguration
2. Decode base64 → get CA certificate
3. When webhook server presents its certificate:
   - Check if it was signed by this CA
   - Verify DNS names match
   - Check expiration
4. If all checks pass → trust the connection
5. If any check fails → reject the request
```

#### 2. Server Certificate (tls.crt)
- Presented by webhook server to API Server
- Must be signed by the CA
- Contains DNS names for the webhook service

```
Subject: CN=threat-scanning-webhook-service.threat-scanning-system.svc
DNS Names:
  - threat-scanning-webhook-service
  - threat-scanning-webhook-service.threat-scanning-system
  - threat-scanning-webhook-service.threat-scanning-system.svc
  - threat-scanning-webhook-service.threat-scanning-system.svc.cluster.local
Issuer: CN=Self-signed CA (our generated CA)
Valid: 1 year
```

#### 3. Server Private Key (tls.key)
- Used by webhook server to prove it owns the certificate
- Never shared, stays on the server
- Used in TLS handshake

These three are stored in a Kubernetes Secret:
```yaml
apiVersion: v1
kind: Secret
type: kubernetes.io/tls
metadata:
  name: threat-scanning-webhook-certs
  namespace: threat-scanning-system
data:
  ca.crt: <base64-encoded CA cert>
  tls.crt: <base64-encoded server cert>
  tls.key: <base64-encoded server private key>
```

## Where cert-manager Fits

### cert-manager's Approach

cert-manager is a Kubernetes add-on that automates certificate management:

```
┌──────────────────────────────────────────────────────────────┐
│                     cert-manager Flow                         │
└──────────────────────────────────────────────────────────────┘

1. You create a Certificate resource:
   ┌─────────────────────────────────────────────┐
   │ apiVersion: cert-manager.io/v1              │
   │ kind: Certificate                           │
   │ metadata:                                   │
   │   name: threat-scanning-webhook-cert        │
   │ spec:                                       │
   │   secretName: threat-scanning-webhook-certs │
   │   issuerRef:                                │
   │     name: selfsigned-issuer                 │
   │   dnsNames:                                 │
   │     - threat-scanning-webhook-service...    │
   └─────────────────────────────────────────────┘
                        ↓
2. cert-manager controller watches Certificate resources
                        ↓
3. Talks to the Issuer (selfsigned, CA, Let's Encrypt, etc.)
                        ↓
4. Generates/requests certificates
                        ↓
5. Creates/updates Secret with ca.crt, tls.crt, tls.key
                        ↓
6. Watches ValidatingWebhookConfiguration with annotation:
   cert-manager.io/inject-ca-from: namespace/certificate-name
                        ↓
7. Automatically injects CA bundle into webhook configuration
                        ↓
8. Automatically renews certificates before expiration
```

### Example with cert-manager

```yaml
---
# 1. Create a self-signed Issuer
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-issuer
  namespace: threat-scanning-system
spec:
  selfSigned: {}

---
# 2. Request a Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: threat-scanning-webhook-cert
  namespace: threat-scanning-system
spec:
  secretName: threat-scanning-webhook-certs  # Where to store certs
  issuerRef:
    name: selfsigned-issuer
  dnsNames:
  - threat-scanning-webhook-service.threat-scanning-system.svc

---
# 3. Tell cert-manager to inject CA bundle
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: threat-scanning-validating-webhook-configuration
  annotations:
    cert-manager.io/inject-ca-from: threat-scanning-system/threat-scanning-webhook-cert
webhooks:
- name: vtarget.threatscanning.trilio.io
  clientConfig:
    caBundle: ""  # cert-manager fills this automatically
    service:
      name: threat-scanning-webhook-service
```

**What cert-manager does:**
1. Watches Certificate resources
2. Generates certificates using Issuer
3. Creates Secret with certificates
4. Watches for annotation `cert-manager.io/inject-ca-from`
5. Extracts CA from the Certificate
6. Base64-encodes it
7. Patches ValidatingWebhookConfiguration with CA bundle
8. Monitors expiration and auto-renews

## How webhook-cert-init Tackles This

Our init container approach replicates cert-manager's functionality **without the external dependency**.

### The Init Container Approach (Trilio's Way)

```
┌──────────────────────────────────────────────────────────────┐
│              Init Container Flow (Our Approach)               │
└──────────────────────────────────────────────────────────────┘

Pod starts
    ↓
┌───────────────────────────────────────────────┐
│ Init Container: webhook-cert-init             │
│                                               │
│ Runs: /manager --init-certs-only             │
└───────────────────────────────────────────────┘
    ↓
1. Generate CA certificate (self-signed)
   ┌─────────────────────────────────────────┐
   │ func GenerateTLSCerts()                 │
   │                                         │
   │ - Create CA with crypto/x509           │
   │ - RSA 4096-bit key                     │
   │ - Valid for 1 year                     │
   │ - Organization: Trilio.io              │
   └─────────────────────────────────────────┘
    ↓
2. Generate server certificate (signed by CA)
   ┌─────────────────────────────────────────┐
   │ - CN: webhook-service.namespace.svc     │
   │ - DNS SANs for all variations           │
   │ - RSA 4096-bit key                     │
   │ - Signed by CA we just created         │
   └─────────────────────────────────────────┘
    ↓
3. Create/update Secret
   ┌─────────────────────────────────────────┐
   │ func createOrUpdateSecret()             │
   │                                         │
   │ kubectl create secret tls \             │
   │   threat-scanning-webhook-certs \       │
   │   --cert=tls.crt \                     │
   │   --key=tls.key \                      │
   │   --namespace=threat-scanning-system    │
   │                                         │
   │ Plus: ca.crt in secret.Data            │
   └─────────────────────────────────────────┘
    ↓
4. Patch ValidatingWebhookConfiguration
   ┌─────────────────────────────────────────┐
   │ func patchValidatingWebhookConfiguration│
   │                                         │
   │ 1. Get webhook configuration            │
   │ 2. Base64-encode CA certificate         │
   │ 3. Update .webhooks[*].clientConfig.    │
   │    caBundle = base64(ca.crt)           │
   │ 4. Update webhook configuration         │
   └─────────────────────────────────────────┘
    ↓
5. Patch MutatingWebhookConfiguration
   ┌─────────────────────────────────────────┐
   │ func patchMutatingWebhookConfiguration  │
   │ (same process)                          │
   └─────────────────────────────────────────┘
    ↓
6. Init container exits (success)
    ↓
┌───────────────────────────────────────────────┐
│ Main Container: manager                       │
│                                               │
│ Runs: /manager --enable-webhook=true         │
└───────────────────────────────────────────────┘
    ↓
1. Mount secret from /tmp/k8s-webhook-server/serving-certs
    ↓
2. Start webhook server on port 9443
    ↓
3. Use tls.crt and tls.key for TLS
    ↓
4. Ready to receive requests from API Server
```

### Code Flow in webhook-cert-init

Let's trace through the actual code:

```go
// 1. Manager main.go detects init-only mode
if initCertsOnly {
    clientset, err := kubernetes.NewForConfig(config)
    namespace := internal.GetInstallNamespace()
    
    // Call initialization
    webhookinit.InitializeWebhookCertificates(clientset, namespace, logger)
    os.Exit(0)  // Exit after cert generation
}

// 2. InitializeWebhookCertificates in webhook_init.go
func InitializeWebhookCertificates(clientset kubernetes.Interface, namespace string, log *logrus.Logger) error {
    // Define DNS names
    commonName := "threat-scanning-webhook-service.threat-scanning-system.svc"
    dnsNames := []string{
        "threat-scanning-webhook-service",
        "threat-scanning-webhook-service.threat-scanning-system",
        "threat-scanning-webhook-service.threat-scanning-system.svc",
        "threat-scanning-webhook-service.threat-scanning-system.svc.cluster.local",
    }
    
    // Generate certificates
    caCert, serverCert, serverKey, err := GenerateTLSCerts(commonName, dnsNames)
    
    // Create/update secret
    createOrUpdateSecret(ctx, clientset, namespace, caCert.Bytes(), serverCert.Bytes(), serverKey.Bytes())
    
    // Patch webhook configurations
    caBundle := base64.StdEncoding.EncodeToString(caCert.Bytes())
    patchWebhookConfigurations(ctx, clientset, caBundle)
}

// 3. GenerateTLSCerts - The actual certificate generation
func GenerateTLSCerts(commonName string, dnsNames []string) (*bytes.Buffer, *bytes.Buffer, *bytes.Buffer, error) {
    // Create CA certificate
    ca := &x509.Certificate{
        SerialNumber: big.NewInt(2020),
        Subject: pkix.Name{Organization: []string{"Trilio.io"}},
        NotBefore: time.Now(),
        NotAfter: time.Now().AddDate(1, 0, 0),  // 1 year
        IsCA: true,
        KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
        // ... more fields
    }
    
    caPrivKey, _ := rsa.GenerateKey(rand.Reader, 4096)
    caBytes, _ := x509.CreateCertificate(rand.Reader, ca, ca, &caPrivKey.PublicKey, caPrivKey)
    caPEM := pem.Encode(&pem.Block{Type: "CERTIFICATE", Bytes: caBytes})
    
    // Create server certificate
    cert := &x509.Certificate{
        DNSNames: dnsNames,
        SerialNumber: big.NewInt(1658),
        Subject: pkix.Name{CommonName: commonName, Organization: []string{"Trilio.io"}},
        NotBefore: time.Now(),
        NotAfter: time.Now().AddDate(1, 0, 0),  // 1 year
        // ... more fields
    }
    
    serverPrivKey, _ := rsa.GenerateKey(rand.Reader, 4096)
    serverCertBytes, _ := x509.CreateCertificate(rand.Reader, cert, ca, &serverPrivKey.PublicKey, caPrivKey)
    serverCertPEM := pem.Encode(&pem.Block{Type: "CERTIFICATE", Bytes: serverCertBytes})
    serverPrivKeyPEM := pem.Encode(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(serverPrivKey)})
    
    return caPEM, serverCertPEM, serverPrivKeyPEM, nil
}

// 4. createOrUpdateSecret
func createOrUpdateSecret(ctx context.Context, clientset kubernetes.Interface, namespace string, caCert, serverCert, serverKey []byte) error {
    secret := &corev1.Secret{
        ObjectMeta: metav1.ObjectMeta{
            Name: "threat-scanning-webhook-certs",
            Namespace: namespace,
        },
        Type: corev1.SecretTypeTLS,
        Data: map[string][]byte{
            "ca.crt":  caCert,      // For reference
            "tls.crt": serverCert,  // Webhook server uses this
            "tls.key": serverKey,   // Webhook server uses this
        },
    }
    
    // Try to get existing secret
    existingSecret, err := clientset.CoreV1().Secrets(namespace).Get(ctx, "threat-scanning-webhook-certs", metav1.GetOptions{})
    if err != nil {
        if apierrors.IsNotFound(err) {
            // Create new
            clientset.CoreV1().Secrets(namespace).Create(ctx, secret, metav1.CreateOptions{})
        }
    } else {
        // Update existing
        existingSecret.Data = secret.Data
        clientset.CoreV1().Secrets(namespace).Update(ctx, existingSecret, metav1.UpdateOptions{})
    }
}

// 5. patchValidatingWebhookConfiguration
func patchValidatingWebhookConfiguration(ctx context.Context, clientset kubernetes.Interface, caBundle string) error {
    vwc, _ := clientset.AdmissionregistrationV1().ValidatingWebhookConfigurations().Get(
        ctx, "threat-scanning-validating-webhook-configuration", metav1.GetOptions{})
    
    // Decode base64 CA bundle
    caBundleBytes, _ := base64.StdEncoding.DecodeString(caBundle)
    
    // Update CA bundle for all webhooks
    for i := range vwc.Webhooks {
        vwc.Webhooks[i].ClientConfig.CABundle = caBundleBytes
    }
    
    // Update the configuration
    clientset.AdmissionregistrationV1().ValidatingWebhookConfigurations().Update(ctx, vwc, metav1.UpdateOptions{})
}
```

## Comparison: cert-manager vs Init Container

### cert-manager Approach

```
┌─────────────────────────────────────────┐
│          cert-manager                   │
│   (separate deployment/controller)      │
└─────────────────────────────────────────┘
           ↓ watches
┌─────────────────────────────────────────┐
│  Certificate Custom Resource            │
│  (you create this)                      │
└─────────────────────────────────────────┘
           ↓ processes
┌─────────────────────────────────────────┐
│  Generates certificates                 │
│  Creates Secret                         │
│  Injects CA bundle via annotation       │
└─────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────┐
│  Your webhook pod starts                │
│  Mounts secret                          │
│  Uses certificates                      │
└─────────────────────────────────────────┘

Pros:
✅ Automatic renewal
✅ Multiple CA options (Let's Encrypt, etc.)
✅ Centralized cert management

Cons:
❌ External dependency
❌ More complex setup
❌ Requires cert-manager installed
```

### Init Container Approach (Our Implementation)

```
┌─────────────────────────────────────────┐
│  Your webhook pod starts                │
└─────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────┐
│  Init container runs FIRST              │
│  (same image, different command)        │
│                                         │
│  - Generates certificates               │
│  - Creates Secret                       │
│  - Patches webhook configs              │
│  - Exits                                │
└─────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────┐
│  Main container starts                  │
│  Mounts secret (created by init)        │
│  Uses certificates                      │
└─────────────────────────────────────────┘

Pros:
✅ No external dependencies
✅ Self-contained
✅ Simple deployment
✅ Same approach as Trilio

Cons:
⚠️ Manual renewal (restart pod)
⚠️ Only self-signed certs
```

## The Complete Flow: API Server Using Certificates

Let's trace a complete validation request:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Step 1: User creates a Target                                          │
└────────────────────────────────────────────────────────────────────────┘

$ kubectl apply -f target.yaml

┌────────────────────────────────────────────────────────────────────────┐
│ Step 2: API Server intercepts the request                              │
└────────────────────────────────────────────────────────────────────────┘

API Server checks: "Are there any ValidatingWebhooks for this resource?"
→ YES! Found threat-scanning-validating-webhook-configuration

┌────────────────────────────────────────────────────────────────────────┐
│ Step 3: API Server reads webhook configuration                         │
└────────────────────────────────────────────────────────────────────────┘

ValidatingWebhookConfiguration:
  webhooks:
  - name: vtarget.threatscanning.trilio.io
    clientConfig:
      caBundle: LS0tLS1CRUdJTi...  # ← API Server reads this
      service:
        name: threat-scanning-webhook-service
        namespace: threat-scanning-system
        path: /validate-threatscanning-trilio-io-v1-target

API Server decodes caBundle → gets CA certificate

┌────────────────────────────────────────────────────────────────────────┐
│ Step 4: API Server establishes TLS connection                          │
└────────────────────────────────────────────────────────────────────────┘

API Server → Webhook Service (threat-scanning-webhook-service:443)

TLS Handshake:
1. API Server: "Hello, I want to connect"
2. Webhook Server: "Here's my certificate" (presents tls.crt)
3. API Server: "Let me verify..."
   - Extract issuer from server cert
   - Check if issuer matches CA from caBundle
   - Verify signature using CA public key
   - Check DNS names match service name
   - Check certificate not expired
4. API Server: "Certificate valid! ✓"

┌────────────────────────────────────────────────────────────────────────┐
│ Step 5: Send validation request over TLS                               │
└────────────────────────────────────────────────────────────────────────┘

POST https://threat-scanning-webhook-service.threat-scanning-system.svc:443/validate-threatscanning-trilio-io-v1-target

{
  "request": {
    "uid": "...",
    "kind": {"kind": "Target"},
    "operation": "CREATE",
    "object": { ...target data... }
  }
}

┌────────────────────────────────────────────────────────────────────────┐
│ Step 6: Webhook validates and responds                                 │
└────────────────────────────────────────────────────────────────────────┘

{
  "response": {
    "uid": "...",
    "allowed": false,
    "status": {
      "message": "[spec.objectStoreCredentials.credentialSecret.namespace] namespace must be specified"
    }
  }
}

┌────────────────────────────────────────────────────────────────────────┐
│ Step 7: API Server returns result to user                              │
└────────────────────────────────────────────────────────────────────────┘

Error from server: admission webhook "vtarget.threatscanning.trilio.io" denied the request: 
[spec.objectStoreCredentials.credentialSecret.namespace] namespace must be specified
```

## Key Takeaways

1. **CA Bundle is Critical**: Without the correct CA bundle in the webhook configuration, API Server cannot trust the webhook server.

2. **cert-manager = Automation**: It automates certificate generation, secret creation, CA bundle injection, and renewal.

3. **Init Container = Manual cert-manager**: We do the same things cert-manager does, but in an init container using Go code.

4. **Both Approaches Work**: 
   - cert-manager: Better for enterprises needing cert lifecycle management
   - Init container: Better for simplicity, no dependencies, Trilio's proven approach

5. **The Secret Connection**: 
   - Init container creates → Secret
   - Main container mounts → Secret
   - Webhook server uses → tls.crt + tls.key from Secret

6. **The Webhook Config Connection**:
   - Init container patches → ValidatingWebhookConfiguration.caBundle
   - API Server reads → caBundle
   - API Server verifies → Webhook server's certificate

Our implementation is **production-ready** because it's the same approach Trilio uses successfully in k8s-triliovault! 🎉
