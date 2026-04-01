# Cluster-Scoped Target Clarification

## 🎯 Important: Targets are Cluster-Scoped

In threat-scanning-architecture, **all Target resources are cluster-scoped**, not namespaced. This is different from k8s-triliovault which supports both namespaced and cluster-scoped targets.

---

## ✅ What This Means

### 1. No `--namespace` Parameter
The validation and mount scripts do NOT use the `--namespace` parameter:

#### ✅ Correct Commands (No Namespace)
```bash
# Validation command
python3 target_validations.py \
    --target-name=my-target \
    --type=backup \
    --group=threatscanning.trilio.io \
    --version=v1

# Mount command
python3 mount_datastores.py \
    --target-name=my-target \
    --group=threatscanning.trilio.io \
    --version=v1
```

#### ❌ Incorrect Commands (With Namespace - NOT USED)
```bash
# DON'T DO THIS - namespace parameter is ignored
python3 target_validations.py \
    --target-name=my-target \
    --namespace=threat-scanning-system \  # ❌ Not needed!
    --type=backup
```

---

## 📋 Target CRD Definition

Targets are defined as cluster-scoped in the CRD:

```go
// api/v1/target_types.go

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:storageversion
// +kubebuilder:resource:scope=Cluster,shortName=tgt  // ← Cluster-scoped
type Target struct {
    metav1.TypeMeta   `json:",inline"`
    metav1.ObjectMeta `json:"metadata,omitempty"`
    Spec   TargetSpec   `json:"spec,omitempty"`
    Status TargetStatus `json:"status,omitempty"`
}
```

---

## 🔍 How Python Scripts Handle Cluster-Scoped Targets

### target_validations.py
```python
# The --namespace argument is optional and DEPRECATED for threat-scanning
parser.add_argument('--namespace', required=False,
                    help="(DEPRECATED for threat-scanning) Namespace is not used as targets are cluster-scoped. "
                         "This parameter is kept for compatibility with k8s-commons but will be ignored.")

# When namespace is None (not provided), CRD parser fetches from cluster scope
target_json = triliodata_crd_parser.get_ds_from_target_crds(
    self.target_cr_name, 
    None,  # ← namespace = None = cluster scope
    "",
    self.group, 
    self.version
)
```

### mount_datastores.py
```python
# The --target-namespace argument is optional and DEPRECATED for threat-scanning
parser.add_argument('--target-namespace', dest="target_namespace", required=False,
                    help="(DEPRECATED for threat-scanning) Namespace is not used as targets are cluster-scoped. "
                         "This parameter is kept for compatibility with k8s-commons but will be ignored.")

# When target_namespace is None, CRD parser fetches from cluster scope
target_json = triliodata_crd_parser.get_ds_from_target_crds(
    name, 
    None,  # ← namespace = None = cluster scope
    cred_hash, 
    cr_group, 
    cr_version
)
```

### triliodata_crd_parser.py
```python
def get_ds_from_target_crds(target_crd_name, target_crd_namespace, ...):
    if target_crd_name:
        if not target_crd_namespace:
            # ← Fetch from cluster scope
            api_response = api_instance.get_cluster_custom_object(
                group=group,
                version=version,
                plural=constants.TARGET_CRD_PLURAL,
                name=target_crd_name
            )
        else:
            # This branch is NOT used in threat-scanning
            api_response = api_instance.get_namespaced_custom_object(...)
```

---

## 🚀 Controller Implementation

The controller correctly omits the namespace parameter:

```go
// pkg/helpers/job_helper.go

// For NFS targets
if target.IsNFSTarget() {
    validationCmd = fmt.Sprintf("%s %s --target-name=%s --type=%s --group=threatscanning.trilio.io --version=v1",
        internal.Py3Path,
        fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreValidatorUtil),
        target.Name,
        targetType)
        // ↑ No --namespace parameter!
}

// For ObjectStore targets
mountCmd := fmt.Sprintf("%s %s --target-name=%s --group=threatscanning.trilio.io --version=v1",
    internal.Py3Path,
    fmt.Sprintf("%s/%s", internal.BasePath, internal.DatastoreMountUtil),
    target.Name)
    // ↑ No --target-namespace parameter!
```

---

## 📝 Creating Targets

### ✅ Correct (Cluster-Scoped)
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: my-backup-target
  # No namespace field - cluster-scoped!
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    bucketName: "my-bucket"
    credentialSecret:
      name: s3-creds
      namespace: threat-scanning-system  # Secret is namespaced, but Target is not
```

### ❌ Incorrect (With Namespace)
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: my-backup-target
  namespace: threat-scanning-system  # ❌ This will fail - targets are cluster-scoped!
spec:
  type: ObjectStore
```

---

## 🔐 Note About Secrets and ConfigMaps

While **Targets are cluster-scoped**, the **secrets and configmaps they reference are namespaced**:

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: cluster-scoped-target  # ← Cluster-scoped (no namespace)
spec:
  objectStoreCredentials:
    credentialSecret:
      name: s3-credentials
      namespace: threat-scanning-system  # ← Secret IS namespaced
    sslCertConfig:
      certConfigMap:
        name: ssl-certs
        namespace: threat-scanning-system  # ← ConfigMap IS namespaced
```

---

## 📊 Comparison with k8s-triliovault

| Aspect | k8s-triliovault | threat-scanning-architecture |
|--------|-----------------|------------------------------|
| **Target Scope** | Namespaced OR Cluster-scoped | **Cluster-scoped ONLY** |
| **Namespace Parameter** | Used (optional) | **NOT used (ignored)** |
| **API Call** | `get_namespaced_custom_object()` or `get_cluster_custom_object()` | **`get_cluster_custom_object()` ONLY** |
| **Target Listing** | Per namespace or cluster-wide | **Cluster-wide ONLY** |
| **Secret References** | Same namespace as target OR explicit | **Explicit namespace REQUIRED** |

---

## ✅ Summary

1. ✅ **Targets are cluster-scoped** - no namespace in metadata
2. ✅ **No `--namespace` parameter** in validation/mount commands
3. ✅ **Controller omits namespace** from all Python script calls
4. ✅ **Python scripts handle this correctly** - when namespace is None, they fetch from cluster scope
5. ✅ **Secrets/ConfigMaps ARE namespaced** - must specify namespace in target spec
6. ✅ **Compatible with k8s-commons** - scripts support both modes, default to cluster scope when namespace not provided

---

## 🔧 For Developers

If you're debugging and see namespace-related errors:

1. **Check CRD definition**: Ensure `scope=Cluster` in `target_types.go`
2. **Check controller commands**: Ensure no `--namespace` or `--target-namespace` parameters
3. **Check Python scripts**: Ensure `target_cr_namespace = None` when not provided
4. **Check target YAML**: Ensure no `namespace` field in target metadata
5. **Check secret references**: Ensure secrets have explicit namespace in target spec

---

**Last Updated**: December 10, 2025  
**Status**: ✅ All scripts and documentation updated to clarify cluster-scoped behavior
