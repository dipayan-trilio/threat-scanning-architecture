package webhookinit

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/pem"
	"fmt"
	"math/big"
	"time"

	"github.com/sirupsen/logrus"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

const (
	webhookSecretName                  = "threat-scanning-webhook-certs"
	validatingWebhookConfigurationName = "threat-scanning-validating-webhook-configuration"
	mutatingWebhookConfigurationName   = "threat-scanning-mutating-webhook-configuration"
	webhookServiceName                 = "threat-scanning-webhook-service"
	defaultNamespace                   = "threat-scanning-system"
)

// GenerateTLSCerts generates self-signed CA and server certificates
// This implementation matches k8s-triliovault's approach
func GenerateTLSCerts(commonName string, dnsNames []string) (caPEM, serverCertPEM, serverPrivKeyPEM *bytes.Buffer, err error) {
	// CA config
	ca := &x509.Certificate{
		SerialNumber: big.NewInt(2020),
		Subject: pkix.Name{
			Organization: []string{"Trilio.io"},
		},
		NotBefore:             time.Now(),
		NotAfter:              time.Now().AddDate(1, 0, 0), // 1 year validity
		IsCA:                  true,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		BasicConstraintsValid: true,
	}

	// CA private key
	caPrivKey, err := rsa.GenerateKey(rand.Reader, 4096)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("failed to generate CA private key: %w", err)
	}

	// Self signed CA certificate
	caBytes, err := x509.CreateCertificate(rand.Reader, ca, ca, &caPrivKey.PublicKey, caPrivKey)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("failed to create CA certificate: %w", err)
	}

	// PEM encode CA cert
	caPEM = new(bytes.Buffer)
	if err := pem.Encode(caPEM, &pem.Block{
		Type:  "CERTIFICATE",
		Bytes: caBytes,
	}); err != nil {
		return nil, nil, nil, fmt.Errorf("failed to encode CA certificate: %w", err)
	}

	// Server cert config
	cert := &x509.Certificate{
		DNSNames:     dnsNames,
		SerialNumber: big.NewInt(1658),
		Subject: pkix.Name{
			CommonName:   commonName,
			Organization: []string{"Trilio.io"},
		},
		NotBefore:    time.Now(),
		NotAfter:     time.Now().AddDate(1, 0, 0), // 1 year validity
		SubjectKeyId: []byte{1, 2, 3, 4, 6},
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
		KeyUsage:     x509.KeyUsageDigitalSignature,
	}

	// Server private key
	serverPrivKey, err := rsa.GenerateKey(rand.Reader, 4096)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("failed to generate server private key: %w", err)
	}

	// Sign the server cert
	serverCertBytes, err := x509.CreateCertificate(rand.Reader, cert, ca, &serverPrivKey.PublicKey, caPrivKey)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("failed to create server certificate: %w", err)
	}

	// PEM encode the server cert and key
	serverCertPEM = new(bytes.Buffer)
	if err := pem.Encode(serverCertPEM, &pem.Block{
		Type:  "CERTIFICATE",
		Bytes: serverCertBytes,
	}); err != nil {
		return nil, nil, nil, fmt.Errorf("failed to encode server certificate: %w", err)
	}

	serverPrivKeyPEM = new(bytes.Buffer)
	if err := pem.Encode(serverPrivKeyPEM, &pem.Block{
		Type:  "RSA PRIVATE KEY",
		Bytes: x509.MarshalPKCS1PrivateKey(serverPrivKey),
	}); err != nil {
		return nil, nil, nil, fmt.Errorf("failed to encode server private key: %w", err)
	}

	return caPEM, serverCertPEM, serverPrivKeyPEM, nil
}

// InitializeWebhookCertificates generates certificates and configures webhooks
func InitializeWebhookCertificates(clientset kubernetes.Interface, namespace string, log *logrus.Logger) error {
	ctx := context.Background()

	if namespace == "" {
		namespace = defaultNamespace
	}

	log.Infof("Initializing webhook certificates in namespace: %s", namespace)

	// Generate DNS names for the webhook service
	commonName := fmt.Sprintf("%s.%s.svc", webhookServiceName, namespace)
	dnsNames := []string{
		webhookServiceName,
		fmt.Sprintf("%s.%s", webhookServiceName, namespace),
		fmt.Sprintf("%s.%s.svc", webhookServiceName, namespace),
		fmt.Sprintf("%s.%s.svc.cluster.local", webhookServiceName, namespace),
	}

	log.Infof("Generating TLS certificates for: %s", commonName)
	log.Infof("DNS names: %v", dnsNames)

	// Generate certificates
	caCert, serverCert, serverKey, err := GenerateTLSCerts(commonName, dnsNames)
	if err != nil {
		return fmt.Errorf("failed to generate TLS certificates: %w", err)
	}

	log.Info("TLS certificates generated successfully")

	// Create or update secret with certificates
	if err := createOrUpdateSecret(ctx, clientset, namespace, caCert.Bytes(), serverCert.Bytes(), serverKey.Bytes(), log); err != nil {
		return fmt.Errorf("failed to create/update secret: %w", err)
	}

	log.Info("Webhook secret created/updated successfully")

	// Patch webhook configurations with CA bundle
	caBundle := base64.StdEncoding.EncodeToString(caCert.Bytes())
	if err := patchWebhookConfigurations(ctx, clientset, caBundle, log); err != nil {
		return fmt.Errorf("failed to patch webhook configurations: %w", err)
	}

	log.Info("Webhook configurations patched with CA bundle successfully")
	log.Info("Webhook initialization complete!")

	return nil
}

// createOrUpdateSecret creates or updates the webhook secret with certificates
func createOrUpdateSecret(ctx context.Context, clientset kubernetes.Interface, namespace string, caCert, serverCert, serverKey []byte, log *logrus.Logger) error {
	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      webhookSecretName,
			Namespace: namespace,
			Labels: map[string]string{
				"app.kubernetes.io/name":      "threat-scanning",
				"app.kubernetes.io/component": "webhook",
			},
		},
		Type: corev1.SecretTypeTLS,
		Data: map[string][]byte{
			"ca.crt":  caCert,
			"tls.crt": serverCert,
			"tls.key": serverKey,
		},
	}

	// Try to get existing secret
	existingSecret, err := clientset.CoreV1().Secrets(namespace).Get(ctx, webhookSecretName, metav1.GetOptions{})
	if err != nil {
		if apierrors.IsNotFound(err) {
			// Create new secret
			log.Infof("Creating new secret: %s", webhookSecretName)
			_, err = clientset.CoreV1().Secrets(namespace).Create(ctx, secret, metav1.CreateOptions{})
			return err
		}
		return err
	}

	// Update existing secret
	log.Infof("Updating existing secret: %s", webhookSecretName)
	existingSecret.Data = secret.Data
	_, err = clientset.CoreV1().Secrets(namespace).Update(ctx, existingSecret, metav1.UpdateOptions{})
	return err
}

// patchWebhookConfigurations patches both validating and mutating webhook configurations with CA bundle
func patchWebhookConfigurations(ctx context.Context, clientset kubernetes.Interface, caBundle string, log *logrus.Logger) error {
	// Patch validating webhook configuration
	log.Infof("Patching validating webhook configuration: %s", validatingWebhookConfigurationName)
	if err := patchValidatingWebhookConfiguration(ctx, clientset, caBundle); err != nil {
		return fmt.Errorf("failed to patch validating webhook configuration: %w", err)
	}

	// Patch mutating webhook configuration
	log.Infof("Patching mutating webhook configuration: %s", mutatingWebhookConfigurationName)
	if err := patchMutatingWebhookConfiguration(ctx, clientset, caBundle); err != nil {
		return fmt.Errorf("failed to patch mutating webhook configuration: %w", err)
	}

	return nil
}

// patchValidatingWebhookConfiguration patches the validating webhook configuration with CA bundle
func patchValidatingWebhookConfiguration(ctx context.Context, clientset kubernetes.Interface, caBundle string) error {
	vwc, err := clientset.AdmissionregistrationV1().ValidatingWebhookConfigurations().Get(
		ctx, validatingWebhookConfigurationName, metav1.GetOptions{})
	if err != nil {
		if apierrors.IsNotFound(err) {
			// Webhook configuration doesn't exist yet, skip patching
			return nil
		}
		return err
	}

	// Decode base64 CA bundle
	caBundleBytes, err := base64.StdEncoding.DecodeString(caBundle)
	if err != nil {
		return fmt.Errorf("failed to decode CA bundle: %w", err)
	}

	// Update CA bundle for all webhooks
	for i := range vwc.Webhooks {
		vwc.Webhooks[i].ClientConfig.CABundle = caBundleBytes
	}

	_, err = clientset.AdmissionregistrationV1().ValidatingWebhookConfigurations().Update(ctx, vwc, metav1.UpdateOptions{})
	return err
}

// patchMutatingWebhookConfiguration patches the mutating webhook configuration with CA bundle
func patchMutatingWebhookConfiguration(ctx context.Context, clientset kubernetes.Interface, caBundle string) error {
	mwc, err := clientset.AdmissionregistrationV1().MutatingWebhookConfigurations().Get(
		ctx, mutatingWebhookConfigurationName, metav1.GetOptions{})
	if err != nil {
		if apierrors.IsNotFound(err) {
			// Webhook configuration doesn't exist yet, skip patching
			return nil
		}
		return err
	}

	// Decode base64 CA bundle
	caBundleBytes, err := base64.StdEncoding.DecodeString(caBundle)
	if err != nil {
		return fmt.Errorf("failed to decode CA bundle: %w", err)
	}

	// Update CA bundle for all webhooks
	for i := range mwc.Webhooks {
		mwc.Webhooks[i].ClientConfig.CABundle = caBundleBytes
	}

	_, err = clientset.AdmissionregistrationV1().MutatingWebhookConfigurations().Update(ctx, mwc, metav1.UpdateOptions{})
	return err
}
