package target

import (
	"context"
	"testing"

	"k8s.io/apimachinery/pkg/api/resource"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	v1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func TestValidateTargetCreate(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = v1.AddToScheme(scheme)

	tests := []struct {
		name    string
		target  *v1.Target
		wantErr bool
		errMsg  string
	}{
		{
			name: "valid NFS target",
			target: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-nfs-target",
				},
				Spec: v1.TargetSpec{
					Type: v1.NFS,
					NFSCredentials: v1.NFSCredentials{
						NfsExport: "/export/path",
					},
				},
			},
			wantErr: false,
		},
		{
			name: "invalid NFS target - missing nfsExport",
			target: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-nfs-target",
				},
				Spec: v1.TargetSpec{
					Type:           v1.NFS,
					NFSCredentials: v1.NFSCredentials{},
				},
			},
			wantErr: true,
			errMsg:  "nfsExport for NFS target missing",
		},
		{
			name: "valid ObjectStore backup target",
			target: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-s3-target",
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "test-bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "invalid ObjectStore target - missing bucketName",
			target: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-s3-target",
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			wantErr: true,
			errMsg:  "bucketName for object store missing",
		},
		{
			name: "valid reporting target",
			target: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-reporting-target",
					Annotations: map[string]string{
						v1.ReportingTargetAnnotationKey: "true",
					},
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "reporting-bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "invalid - second reporting target",
			target: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-reporting-target-2",
					Annotations: map[string]string{
						v1.ReportingTargetAnnotationKey: "true",
					},
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "reporting-bucket-2",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			wantErr: true,
			errMsg:  "only one reporting target is allowed",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create fake client with existing reporting target for the "second reporting" test
			existingObjects := []runtime.Object{}
			if tt.name == "invalid - second reporting target" {
				existingReporting := &v1.Target{
					ObjectMeta: metav1.ObjectMeta{
						Name: "existing-reporting-target",
						Annotations: map[string]string{
							v1.ReportingTargetAnnotationKey: "true",
						},
					},
					Spec: v1.TargetSpec{
						Type: v1.ObjectStore,
					},
				}
				existingObjects = append(existingObjects, existingReporting)
			}

			client := fake.NewClientBuilder().
				WithScheme(scheme).
				WithRuntimeObjects(existingObjects...).
				Build()

			err := ValidateTargetCreate(context.Background(), client, tt.target)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateTargetCreate() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if tt.wantErr && tt.errMsg != "" {
				if err == nil || !contains(err.Error(), tt.errMsg) {
					t.Errorf("ValidateTargetCreate() error = %v, want error containing %q", err, tt.errMsg)
				}
			}
		})
	}
}

func TestValidateTargetUpdate(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = v1.AddToScheme(scheme)

	tests := []struct {
		name      string
		oldTarget *v1.Target
		newTarget *v1.Target
		wantErr   bool
		errMsg    string
	}{
		{
			name: "valid update - backup remains backup",
			oldTarget: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-backup-target",
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "old-bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			newTarget: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-backup-target",
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "new-bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "invalid update - backup to reporting conversion",
			oldTarget: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-target",
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			newTarget: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-target",
					Annotations: map[string]string{
						v1.ReportingTargetAnnotationKey: "true",
					},
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			wantErr: true,
			errMsg:  "conversion from backup target to reporting target is not allowed",
		},
		{
			name: "valid update - reporting to backup conversion allowed",
			oldTarget: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-target",
					Annotations: map[string]string{
						v1.ReportingTargetAnnotationKey: "true",
					},
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			newTarget: &v1.Target{
				ObjectMeta: metav1.ObjectMeta{
					Name: "test-target",
				},
				Spec: v1.TargetSpec{
					Type:   v1.ObjectStore,
					Vendor: v1.AWS,
					ObjectStoreCredentials: v1.ObjectStoreCredentials{
						BucketName: "bucket",
						CredentialSecret: &corev1.ObjectReference{
							Name:      "s3-secret",
							Namespace: "default",
						},
					},
				},
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			client := fake.NewClientBuilder().
				WithScheme(scheme).
				Build()

			err := ValidateTargetUpdate(context.Background(), client, tt.oldTarget, tt.newTarget)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateTargetUpdate() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if tt.wantErr && tt.errMsg != "" {
				if err == nil || !contains(err.Error(), tt.errMsg) {
					t.Errorf("ValidateTargetUpdate() error = %v, want error containing %q", err, tt.errMsg)
				}
			}
		})
	}
}

func TestValidateResourceQuantity(t *testing.T) {
	tests := []struct {
		name     string
		quantity *resource.Quantity
		wantErr  bool
	}{
		{
			name:     "nil quantity is valid",
			quantity: nil,
			wantErr:  false,
		},
		{
			name:     "positive quantity is valid",
			quantity: resource.NewQuantity(1024*1024*1024, resource.BinarySI),
			wantErr:  false,
		},
		{
			name:     "negative quantity is invalid",
			quantity: resource.NewQuantity(-1024, resource.BinarySI),
			wantErr:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateResourceQuantity(tt.quantity)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateResourceQuantity() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

// Helper function to check if a string contains a substring
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > len(substr) &&
		(s[:len(substr)] == substr || s[len(s)-len(substr):] == substr ||
			len(s) > len(substr) && s[1:len(substr)+1] == substr))
}
