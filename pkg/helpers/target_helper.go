package helpers

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	"github.com/trilioData/threat-scanning-architecture/internal"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// GetTargetResourceName generates a resource name for a target
func GetTargetResourceName(prefix, credentialHash string) string {
	return fmt.Sprintf("%s-%s", prefix, credentialHash)
}

// GetTargetCredentialsHash calculates the hash of target credentials
func GetTargetCredentialsHash(ctx context.Context, cl client.Client, target *v1.Target) (string, error) {
	credentialData := make(map[string]interface{})

	if target.IsNFSTarget() {
		credentialData["type"] = "NFS"
		credentialData["nfsExport"] = target.Spec.NFSCredentials.NfsExport
		credentialData["nfsOptions"] = target.Spec.NFSCredentials.NfsOptions
	} else if target.IsObjectStoreTarget() {
		credentialData["type"] = "ObjectStore"
		credentialData["url"] = target.Spec.ObjectStoreCredentials.URL
		credentialData["bucketName"] = target.Spec.ObjectStoreCredentials.BucketName
		credentialData["region"] = target.Spec.ObjectStoreCredentials.Region
		credentialData["vendor"] = string(target.Spec.Vendor)
		credentialData["skipCertVerification"] = target.Spec.ObjectStoreCredentials.SkipCertVerification

		// Include secret data in hash if credential secret is specified
		if target.HasObjectStoreCredentialSecret() {
			secret := &corev1.Secret{}
			secretKey := types.NamespacedName{
				Name:      target.Spec.ObjectStoreCredentials.CredentialSecret.Name,
				Namespace: target.Spec.ObjectStoreCredentials.CredentialSecret.Namespace,
			}
			if err := cl.Get(ctx, secretKey, secret); err != nil {
				return "", fmt.Errorf("failed to get credential secret: %w", err)
			}
			credentialData["accessKey"] = string(secret.Data[internal.AccessKeyName])
			credentialData["secretKey"] = string(secret.Data[internal.SecretKeyName])
		}

		// Include SSL cert config in hash if specified
		if target.HasSSLCertConfig() {
			configMap := &corev1.ConfigMap{}
			configMapKey := types.NamespacedName{
				Name:      target.Spec.ObjectStoreCredentials.SSLCertConfig.CertConfigMap.Name,
				Namespace: target.Spec.ObjectStoreCredentials.SSLCertConfig.CertConfigMap.Namespace,
			}
			if err := cl.Get(ctx, configMapKey, configMap); err != nil {
				return "", fmt.Errorf("failed to get SSL cert configmap: %w", err)
			}
			certKey := target.Spec.ObjectStoreCredentials.SSLCertConfig.CertKey
			credentialData["sslCert"] = configMap.Data[certKey]
		}
	}

	// Convert to JSON and calculate hash
	jsonData, err := json.Marshal(credentialData)
	if err != nil {
		return "", fmt.Errorf("failed to marshal credential data: %w", err)
	}

	hash := sha256.Sum256(jsonData)
	return fmt.Sprintf("%x", hash)[:16], nil
}

// GetNFSPersistentVolume creates a PersistentVolume for NFS target
func GetNFSPersistentVolume(target *v1.Target, credentialHash string) *corev1.PersistentVolume {
	volumeName := GetTargetResourceName(internal.TargetNFSVolumePrefix, credentialHash)

	// Set default capacity if ThresholdCapacity is not specified
	// Default to 1Ti to match k8s-triliovault behavior
	capacity := resource.MustParse("1Ti")
	if target.Spec.ThresholdCapacity != nil {
		capacity = target.Spec.ThresholdCapacity.DeepCopy()
	}

	// Parse NFS mount options from nfsOptions field (e.g., "nfsvers=4,rw,hard")
	var mountOptions []string
	if target.Spec.NFSCredentials.NfsOptions != "" {
		// Split by comma to get individual options
		options := target.Spec.NFSCredentials.NfsOptions
		// Simple split - could be enhanced to handle more complex parsing if needed
		for _, opt := range splitNFSOptions(options) {
			if opt != "" {
				mountOptions = append(mountOptions, opt)
			}
		}
	}

	pv := &corev1.PersistentVolume{
		ObjectMeta: metav1.ObjectMeta{
			Name:   volumeName,
			Labels: internal.GetRecommendedLabels("nfs-volume", internal.ManagedBy),
			Annotations: map[string]string{
				internal.TargetCredentialsHashAnnotationKey: credentialHash,
			},
		},
		Spec: corev1.PersistentVolumeSpec{
			Capacity: corev1.ResourceList{
				corev1.ResourceStorage: capacity,
			},
			AccessModes: []corev1.PersistentVolumeAccessMode{
				corev1.ReadWriteMany,
			},
			PersistentVolumeReclaimPolicy: corev1.PersistentVolumeReclaimRetain,
			MountOptions:                  mountOptions,
			PersistentVolumeSource: corev1.PersistentVolumeSource{
				NFS: &corev1.NFSVolumeSource{
					Server: getNFSServer(target.Spec.NFSCredentials.NfsExport),
					Path:   getNFSPath(target.Spec.NFSCredentials.NfsExport),
				},
			},
		},
	}

	return pv
}

// GetNFSPersistentVolumeClaim creates a PersistentVolumeClaim for NFS target
func GetNFSPersistentVolumeClaim(credentialHash string, pv *corev1.PersistentVolume) *corev1.PersistentVolumeClaim {
	pvcName := GetTargetResourceName(internal.TargetNFSVolumePrefix, credentialHash)

	// Set empty string for StorageClassName to match the PV (which has no storage class)
	// This prevents Kubernetes from assigning the default storage class
	emptyStorageClass := ""

	pvc := &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      pvcName,
			Namespace: internal.GetInstallNamespace(),
			Labels:    internal.GetRecommendedLabels("nfs-volume-claim", internal.ManagedBy),
			Annotations: map[string]string{
				internal.TargetCredentialsHashAnnotationKey: credentialHash,
			},
		},
		Spec: corev1.PersistentVolumeClaimSpec{
			AccessModes: []corev1.PersistentVolumeAccessMode{
				corev1.ReadWriteMany,
			},
			Resources: corev1.VolumeResourceRequirements{
				Requests: pv.Spec.Capacity,
			},
			StorageClassName: &emptyStorageClass, // Match PV's empty storage class
			VolumeName:       pv.Name,
		},
	}

	return pvc
}

// getNFSServer extracts the server from NFS export string
func getNFSServer(nfsExport string) string {
	// Format: server:/path
	for i, c := range nfsExport {
		if c == ':' {
			return nfsExport[:i]
		}
	}
	return nfsExport
}

// getNFSPath extracts the path from NFS export string
func getNFSPath(nfsExport string) string {
	// Format: server:/path
	for i, c := range nfsExport {
		if c == ':' {
			return nfsExport[i+1:]
		}
	}
	return "/"
}

// splitNFSOptions splits NFS options string by comma
// Example: "nfsvers=4,rw,hard" -> ["nfsvers=4", "rw", "hard"]
func splitNFSOptions(options string) []string {
	var result []string
	current := ""

	for _, ch := range options {
		if ch == ',' {
			if current != "" {
				result = append(result, current)
				current = ""
			}
		} else if ch != ' ' { // Skip spaces
			current += string(ch)
		}
	}

	// Add last option if exists
	if current != "" {
		result = append(result, current)
	}

	return result
}
