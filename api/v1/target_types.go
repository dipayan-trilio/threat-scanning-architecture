package v1

import (
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// TargetType is the type of target.
// +kubebuilder:validation:Enum=ObjectStore;NFS
type TargetType string

// ValidationState is validation state of the target credentials
// It can have only two values VALID and INVALID.
type ValidationState string

const (
	ObjectStore TargetType = "ObjectStore"
	NFS         TargetType = "NFS"
)

// BackupProductType is the backup product type (TVK or TVO).
// +kubebuilder:validation:Enum=TVK;TVO
type BackupProductType string

const (
	TVK BackupProductType = "TVK"
	TVO BackupProductType = "TVO"
)

// Vendor is the third party storage vendor hosting the target
// +kubebuilder:validation:Enum=AWS;RedhatCeph;Ceph;IBMCleversafe;Cloudian;Scality;NetApp;Cohesity;SwiftStack;Wasabi;MinIO;DellEMC;Azure;DigitalOcean;OVH;Other
type Vendor string

const (
	AWS                     Vendor          = "AWS"
	RedhatCeph              Vendor          = "RedHatCeph"
	Ceph                    Vendor          = "Ceph"
	IBMCleversafe           Vendor          = "IBMCleversafe"
	Cloudian                Vendor          = "Cloudian"
	Scality                 Vendor          = "Scality"
	NetApp                  Vendor          = "NetApp"
	Cohesity                Vendor          = "Cohesity"
	SwiftStack              Vendor          = "SwiftStack"
	Wasabi                  Vendor          = "Wasabi"
	MinIO                   Vendor          = "MinIO"
	Azure                   Vendor          = "Azure"
	DellEMC                 Vendor          = "DellEMC"
	DigitalOcean            Vendor          = "DigitalOcean"
	OVH                     Vendor          = "OVH"
	Other                   Vendor          = "Other"
	ValidTargetCredential   ValidationState = "VALID"
	InvalidTargetCredential ValidationState = "INVALID"
)

const (
	ReportingTargetAnnotationKey = "trilio.io/reporting-target"
)

// Status represents the current status of a resource
// +kubebuilder:validation:Enum=InProgress;Available;Unavailable;Completed;Failed;Ready
type Status string

const (
	InProgress  Status = "InProgress"
	Available   Status = "Available"
	Unavailable Status = "Unavailable"
	Completed   Status = "Completed"
	Failed      Status = "Failed"
	Ready       Status = "Ready"
)

// OperationType defines the type of operation being performed
// +kubebuilder:validation:Enum=Validation
type OperationType string

const (
	ValidationOperation OperationType = "Validation"
)

// ObjectStoreCredentials defines the credentials to use Object Store as a target type.
type ObjectStoreCredentials struct {
	// URL to connect the Object Store.
	// +kubebuilder:validation:Optional
	URL string `json:"url,omitempty"`

	// CredentialSecret is object ref of a secret which contains target credentials like accessKey, secretKey, etc.
	// +kubebuilder:validation:Optional
	CredentialSecret *corev1.ObjectReference `json:"credentialSecret,omitempty"`

	// SSLCertConfig is the configuration for SSL certificate.
	// +kubebuilder:validation:Optional
	SSLCertConfig *SSLCert `json:"sslCertConfig,omitempty"`

	// BucketName is the name of a bucket within Object Store.
	BucketName string `json:"bucketName"`

	// Region where the Object Store resides.
	// +kubebuilder:validation:Optional
	Region string `json:"region,omitempty"`

	// +kubebuilder:validation:Optional
	// +nullable:true
	// SkipCertVerification specify if target needs to be accessed without certificate verification and usage.
	SkipCertVerification bool `json:"skipCertVerification,omitempty"`
}

// SSLCert defines the configuration for SSL certificate.
type SSLCert struct {
	// certConfigMap is the object reference to the ConfigMap containing the SSL certificate.
	// +kubebuilder:validation:Optional
	CertConfigMap *corev1.ObjectReference `json:"certConfigMap,omitempty"`

	// certKey is the key in the ConfigMap containing the SSL certificate.
	// +kubebuilder:validation:Optional
	CertKey string `json:"certKey,omitempty"`
}

// NFSCredentials defines the credentials to use NFS as a target type.
type NFSCredentials struct {
	// A NFS location in format trilio.net:/data/location/abcde or 192.156.13.1:/user/keeth/data.
	NfsExport string `json:"nfsExport"`

	// An additional options passed to mount NFS directory e.g. rw, suid, hard, intr, timeo, retry.
	// +kubebuilder:validation:Optional
	NfsOptions string `json:"nfsOptions,omitempty"`
}

// TargetCondition specifies the current condition of a target resource.
type TargetCondition struct {
	// Status is the status of the condition.
	// +nullable:true
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Enum=InProgress;Error;Completed;Failed
	Status Status `json:"status,omitempty"`

	// Timestamp is the time a condition occurred.
	// +nullable:true
	// +kubebuilder:validation:Optional
	Timestamp *metav1.Time `json:"timestamp,omitempty"`

	// A brief message indicating details about why the component is in this condition.
	// +nullable:true
	// +kubebuilder:validation:Optional
	Reason string `json:"reason,omitempty"`

	// Phase defines the current phase of the controller.
	// +nullable:true
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Enum=Validation
	Phase OperationType `json:"phase,omitempty"`
}

// TargetSpec defines the specification of a Target.
type TargetSpec struct {
	// Type is the type of target for backup storage.
	Type TargetType `json:"type"`

	// TargetType is the backup product type (TVK or TVO).
	// Required for backup targets, not applicable for reporting targets.
	// +kubebuilder:validation:Optional
	TargetType BackupProductType `json:"targetType,omitempty"`

	// Vendor is the third party storage vendor hosting the target
	Vendor Vendor `json:"vendor"`

	// NfsCredentials specifies the credentials for TargetType NFS
	// +kubebuilder:validation:Optional
	NFSCredentials NFSCredentials `json:"nfsCredentials,omitempty"`

	// ObjectStoreCredentials specifies the credentials for TargetType ObjectStore
	// +kubebuilder:validation:Optional
	ObjectStoreCredentials ObjectStoreCredentials `json:"objectStoreCredentials,omitempty"`

	// ThresholdCapacity is the maximum threshold capacity to store backup data.
	// +kubebuilder:validation:Optional
	ThresholdCapacity *resource.Quantity `json:"thresholdCapacity,omitempty"`
}

// TargetStatus defines the observed state of Target
type TargetStatus struct {
	// Condition is the current condition of a target.
	// +nullable:true
	// +kubebuilder:validation:Optional
	Condition []TargetCondition `json:"condition,omitempty"`

	// Status is the final Status of target Available/Unavailable
	// +nullable:true
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Enum=InProgress;Available;Unavailable
	Status Status `json:"status,omitempty"`

	// NFSPersistentVolume is the object reference to the PersistentVolume of NFS volume type with target NFS credentials
	// +kubebuilder:validation:Optional
	NFSPersistentVolume *corev1.ObjectReference `json:"nfsPersistentVolume,omitempty"`

	// NFSPersistentVolumeClaim is the object reference to the PersistentVolumeClaim bound to NFS volume attached to the Container
	// +kubebuilder:validation:Optional
	NFSPersistentVolumeClaim *corev1.ObjectReference `json:"nfsPersistentVolumeClaim,omitempty"`
}

// Target is a location where backup artifacts are stored.
//
// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:scope=Cluster
// +kubebuilder:printcolumn:name="Type",type=string,JSONPath=`.spec.type`
// +kubebuilder:printcolumn:name="TargetType",type=string,JSONPath=`.spec.targetType`
// +kubebuilder:printcolumn:name="Vendor",type=string,JSONPath=`.spec.vendor`
// +kubebuilder:printcolumn:name="Status",type=string,JSONPath=`.status.status`
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"
type Target struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   TargetSpec   `json:"spec,omitempty"`
	Status TargetStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// TargetList contains a list of Target.
type TargetList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []Target `json:"items"`
}

func init() {
	SchemeBuilder.Register(&Target{}, &TargetList{})
}

// IsNFSTarget returns true if the target is of type NFS
func (in *Target) IsNFSTarget() bool {
	return in.Spec.Type == NFS
}

// IsObjectStoreTarget returns true if the target is of type ObjectStore
func (in *Target) IsObjectStoreTarget() bool {
	return in.Spec.Type == ObjectStore
}

// IsVendorAzure returns true if the vendor is Azure
func (in *Target) IsVendorAzure() bool {
	return in.Spec.Vendor == Azure
}

// HasObjectStoreCredentialSecret returns true if the target has credential secret
func (in *Target) HasObjectStoreCredentialSecret() bool {
	return in.Spec.ObjectStoreCredentials.CredentialSecret != nil
}

// HasSSLCertConfig returns true if the target has SSL certificate configuration
func (in *Target) HasSSLCertConfig() bool {
	return in.Spec.ObjectStoreCredentials.SSLCertConfig != nil
}

// HasSkipCertVerification returns true if the target has skip cert verification enabled
func (in *Target) HasSkipCertVerification() bool {
	return in.Spec.ObjectStoreCredentials.SkipCertVerification
}

// IsReportingTarget returns true if the target is a reporting target
func (in *Target) IsReportingTarget() bool {
	if in.Annotations == nil {
		return false
	}
	value, exists := in.Annotations[ReportingTargetAnnotationKey]
	return exists && value == "true"
}

// IsTVKBackupType returns true if the backup type is TVK
func (in *Target) IsTVKBackupType() bool {
	return in.Spec.TargetType == TVK
}

// IsTVOBackupType returns true if the backup type is TVO
func (in *Target) IsTVOBackupType() bool {
	return in.Spec.TargetType == TVO
}

// LastMatchingTargetCondition returns the last matching target condition
func (in *Target) LastMatchingTargetCondition(condition TargetCondition) *TargetCondition {
	for i := len(in.Status.Condition) - 1; i >= 0; i-- {
		cond := in.Status.Condition[i]
		if cond.Phase == condition.Phase && cond.Status == condition.Status {
			return &cond
		}
	}
	return nil
}

// HasValidationCondition checks if validation condition with given status already exists
func (in *Target) HasValidationCondition(status Status) bool {
	for i := len(in.Status.Condition) - 1; i >= 0; i-- {
		cond := in.Status.Condition[i]
		if cond.Phase == ValidationOperation && cond.Status == status {
			return true
		}
	}
	return false
}

// IsValidationCompleted checks if validation has completed (either Completed or Failed)
func (in *Target) IsValidationCompleted() bool {
	for i := len(in.Status.Condition) - 1; i >= 0; i-- {
		cond := in.Status.Condition[i]
		if cond.Phase == ValidationOperation && (cond.Status == Completed || cond.Status == Failed) {
			return true
		}
	}
	return false
}
