package v1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// BackupType is the type of backup (TVK or TVO)
// +kubebuilder:validation:Enum=TVK;TVO
type BackupType string

const (
	TVK BackupType = "TVK"
	TVO BackupType = "TVO"
)

// ScanPhase represents the current phase of scanning
// +kubebuilder:validation:Enum=Queued;PreScan;Scanning
type ScanPhase string

const (
	Queued   ScanPhase = "Queued"
	PreScan  ScanPhase = "PreScan"
	Scanning ScanPhase = "Scanning"
)

// ScanInstanceStatus represents the overall status of a scan instance
// +kubebuilder:validation:Enum=Queued;InProgress;Completed;Failed
type ScanInstanceStatus string

const (
	ScanQueued     ScanInstanceStatus = "Queued"
	ScanInProgress ScanInstanceStatus = "InProgress"
	ScanCompleted  ScanInstanceStatus = "Completed"
	ScanFailed     ScanInstanceStatus = "Failed"
)

// ScanInstanceCondition specifies the current condition of a scan instance.
type ScanInstanceCondition struct {
	// Phase defines the current phase of the scan.
	// +nullable:true
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Enum=Queued;PreScan;Scanning
	Phase ScanPhase `json:"phase,omitempty"`

	// Status is the status of the condition.
	// +nullable:true
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Enum=InProgress;Completed;Failed
	Status Status `json:"status,omitempty"`

	// Timestamp is the time a condition occurred.
	// +nullable:true
	// +kubebuilder:validation:Optional
	Timestamp *metav1.Time `json:"timestamp,omitempty"`

	// A brief message indicating details about why the component is in this condition.
	// +nullable:true
	// +kubebuilder:validation:Optional
	Reason string `json:"reason,omitempty"`
}

// BackupTargetReference contains the reference to the backup target
type BackupTargetReference struct {
	// APIVersion is the API version of the target
	// +kubebuilder:validation:Optional
	APIVersion string `json:"apiVersion,omitempty"`

	// Kind is the kind of the target
	// +kubebuilder:validation:Optional
	Kind string `json:"kind,omitempty"`

	// Name is the name of the target
	Name string `json:"name"`

	// ResourceVersion is the resource version of the target
	// +kubebuilder:validation:Optional
	ResourceVersion string `json:"resourceVersion,omitempty"`

	// UID is the UID of the target
	// +kubebuilder:validation:Optional
	UID string `json:"uid,omitempty"`
}

// BackupReference contains the reference to the backup
type BackupReference struct {
	// UID is the UID of the backup
	// +kubebuilder:validation:Optional
	UID string `json:"uid,omitempty"`

	// Path is the path to the backup
	Path string `json:"path"`
}

// ScanInstanceSpec defines the specification of a ScanInstance.
type ScanInstanceSpec struct {
	// BackupTarget is the reference to the backup target
	BackupTarget BackupTargetReference `json:"backupTarget"`

	// BackupRef is the reference to the backup
	BackupRef BackupReference `json:"backupRef"`
}

// VMInfo contains information about a VM and its PVCs that need scanning
type VMInfo struct {
	// VMName is the name of the VirtualMachine
	VMName string `json:"vmName"`

	// PVCPaths contains the list of PVC paths for this VM
	// For now, includes all VM PVCs (boot disk + data disks)
	// Future: Will be filtered to include only the boot disk
	PVCPaths []string `json:"pvcPaths"`
}

// ScanLocation represents a backup location with VMs to scan
type ScanLocation struct {
	// Namespace is the namespace of the backup
	// Empty for single namespace backups (non-cluster)
	// +kubebuilder:validation:Optional
	Namespace string `json:"namespace,omitempty"`

	// BackupUID is the UID of the backup
	BackupUID string `json:"backupUID"`

	// BackupPath is the relative path to the backup directory
	BackupPath string `json:"backupPath"`

	// VMs contains the list of VMs with their PVC paths that need scanning
	// Each VM entry groups all PVCs belonging to that VM
	// For now, includes all VM PVCs (boot + data disks)
	// Future: Will be filtered to include only boot disks
	VMs []VMInfo `json:"vms"`
}

// ScanInstanceStatusSpec defines the observed state of ScanInstance
type ScanInstanceStatusSpec struct {
	// Type is the type of backup (TVK or TVO)
	// +nullable:true
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Enum=TVK;TVO
	Type BackupType `json:"type,omitempty"`

	// Status is the overall status of the scan instance
	// +nullable:true
	// +kubebuilder:validation:Optional
	// +kubebuilder:validation:Enum=Queued;InProgress;Completed;Failed
	Status ScanInstanceStatus `json:"status,omitempty"`

	// Condition is the current condition of a scan instance.
	// +nullable:true
	// +kubebuilder:validation:Optional
	Condition []ScanInstanceCondition `json:"condition,omitempty"`

	// Report is the path to the scan report
	// +nullable:true
	// +kubebuilder:validation:Optional
	Report string `json:"report,omitempty"`

	// ScanLocations contains the list of backup locations to scan with their VM PVC paths
	// For single namespace backup: One entry with empty Namespace field
	// For cluster-backup: Multiple entries (one per child backup that has VMs)
	// If this list is empty, no VM workloads need scanning
	// +nullable:true
	// +kubebuilder:validation:Optional
	ScanLocations []ScanLocation `json:"scanLocations,omitempty"`
}

// ScanInstance represents a single scan operation for a backup.
//
// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:scope=Cluster,shortName=si
// +kubebuilder:printcolumn:name="BackupTarget",type=string,JSONPath=`.spec.backupTarget.name`
// +kubebuilder:printcolumn:name="BackupPath",type=string,JSONPath=`.spec.backupRef.path`
// +kubebuilder:printcolumn:name="Type",type=string,JSONPath=`.status.type`
// +kubebuilder:printcolumn:name="Status",type=string,JSONPath=`.status.status`
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"
type ScanInstance struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ScanInstanceSpec       `json:"spec,omitempty"`
	Status ScanInstanceStatusSpec `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// ScanInstanceList contains a list of ScanInstance.
type ScanInstanceList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ScanInstance `json:"items"`
}

func init() {
	SchemeBuilder.Register(&ScanInstance{}, &ScanInstanceList{})
}

// LastMatchingScanInstanceCondition returns the last matching scan instance condition
func (in *ScanInstance) LastMatchingScanInstanceCondition(condition ScanInstanceCondition) *ScanInstanceCondition {
	for i := len(in.Status.Condition) - 1; i >= 0; i-- {
		cond := in.Status.Condition[i]
		if cond.Phase == condition.Phase && cond.Status == condition.Status {
			return &cond
		}
	}
	return nil
}

// HasCondition checks if a specific phase/status condition exists
// This is used for idempotency - to avoid reprocessing completed phases
func (in *ScanInstance) HasCondition(phase ScanPhase, status Status) bool {
	for _, cond := range in.Status.Condition {
		if cond.Phase == phase && cond.Status == status {
			return true
		}
	}
	return false
}

// GetLastConditionForPhase returns the last condition for a specific phase
// Useful for checking if a phase is in progress, completed, or failed
func (in *ScanInstance) GetLastConditionForPhase(phase ScanPhase) *ScanInstanceCondition {
	for i := len(in.Status.Condition) - 1; i >= 0; i-- {
		if in.Status.Condition[i].Phase == phase {
			return &in.Status.Condition[i]
		}
	}
	return nil
}

// HasVMWorkload returns true if the scan instance has VM workload
func (in *ScanInstance) HasVMWorkload() bool {
	if in.Annotations == nil {
		return false
	}
	value, exists := in.Annotations["trilio.io/vm-workload"]
	return exists && value == "true"
}

// GetInstanceID returns the instance ID from labels
func (in *ScanInstance) GetInstanceID() string {
	if in.Labels == nil {
		return ""
	}
	return in.Labels["trilio.io/instance-id"]
}

// GetBackupTargetUID returns the backup target UID from labels
func (in *ScanInstance) GetBackupTargetUID() string {
	if in.Labels == nil {
		return ""
	}
	return in.Labels["trilio.io/backup-target"]
}

// GetBackupPlanUID returns the backup plan UID from labels
func (in *ScanInstance) GetBackupPlanUID() string {
	if in.Labels == nil {
		return ""
	}
	return in.Labels["trilio.io/backupplan"]
}

// GetBackupUID returns the backup UID from labels
func (in *ScanInstance) GetBackupUID() string {
	if in.Labels == nil {
		return ""
	}
	return in.Labels["trilio.io/backup"]
}
