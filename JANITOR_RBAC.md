# Janitor RBAC Configuration

The janitor service requires appropriate RBAC permissions to delete resources. Here's how to set it up correctly:

## Option 1: Use Existing Service Account (Recommended)

If you're deploying janitor in the same namespace as the controller (`threat-scanning-system`), update the ClusterRoleBinding:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: manager-rolebinding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: manager-role
subjects:
- kind: ServiceAccount
  name: trilio-threat-scanning
  namespace: threat-scanning-system  # Change from 'default' to your namespace
```

## Option 2: Separate Janitor Service Account

Create a dedicated service account for janitor:

```yaml
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: threat-scan-janitor
  namespace: threat-scanning-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: janitor-role
rules:
- apiGroups:
  - ""
  resources:
  - configmaps
  - services
  verbs:
  - get
  - list
  - delete
- apiGroups:
  - apps
  resources:
  - deployments
  verbs:
  - get
  - list
  - delete
- apiGroups:
  - batch
  resources:
  - jobs
  verbs:
  - get
  - list
  - delete
- apiGroups:
  - threatscanning.trilio.io
  resources:
  - scaninstances
  verbs:
  - get
  - list
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: janitor-rolebinding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: janitor-role
subjects:
- kind: ServiceAccount
  name: threat-scan-janitor
  namespace: threat-scanning-system
```

Then update the janitor job/cronjob to use this service account:

```yaml
serviceAccountName: threat-scan-janitor
```

## Troubleshooting

### Check Current Service Account
```bash
kubectl get sa -n threat-scanning-system
```

### Verify RBAC Permissions
```bash
# Check if service account can get deployments
kubectl auth can-i get deployments \
  --as=system:serviceaccount:threat-scanning-system:trilio-threat-scanning \
  -n default

# Check if service account can delete deployments
kubectl auth can-i delete deployments \
  --as=system:serviceaccount:threat-scanning-system:trilio-threat-scanning \
  -n default
```

### Check ClusterRoleBinding
```bash
kubectl get clusterrolebinding manager-rolebinding -o yaml
```

### Fix Namespace Mismatch

If your janitor is running in namespace A but the ClusterRoleBinding references namespace B:

```bash
# Update the ClusterRoleBinding
kubectl edit clusterrolebinding manager-rolebinding

# Change the subject namespace to match where your pods run
```

## Common Issues

### Issue: "is forbidden: User cannot get resource"

**Cause:** Service account in ClusterRoleBinding doesn't match the namespace where the janitor pod runs.

**Solution:** Update the ClusterRoleBinding subject namespace to match your deployment namespace.

### Issue: Resources in different namespace

**Cause:** `INSTALL_NAMESPACE` environment variable points to wrong namespace.

**Solution:** Set `INSTALL_NAMESPACE` correctly in the janitor job/cronjob spec.
