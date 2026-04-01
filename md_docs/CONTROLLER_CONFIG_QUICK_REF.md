# Quick Reference: Controller Configuration Update

**Updated:** March 26, 2026

---

## Files Modified

1. ✅ `config/rbac/role.yaml` - Added secret CRUD permissions
2. ✅ `config/manager/manager.yaml` - Added PostgreSQL environment variables

---

## 1. Secret Permissions (ClusterRole)

### Added Verbs:
```yaml
- create
- delete
- patch
- update
```

### Full Secret Permissions:
```yaml
- apiGroups:
  - ""
  resources:
  - secrets
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch
```

---

## 2. PostgreSQL Environment Variables (Deployment)

### Environment Variables Added:
```yaml
env:
- name: POSTGRES_HOST
  value: "postgres-service.threat-scanning-system.svc.cluster.local"
- name: POSTGRES_PORT
  value: "5432"
- name: POSTGRES_USER
  value: "postgres"
- name: POSTGRES_PASSWORD
  value: "postgres123"
- name: POSTGRES_DASHBOARD_DATABASE
  value: "soc_dashboard"
- name: POSTGRES_CACHE_DATABASE
  value: "soc_cache"
```

⚠️ **Note:** These are dummy values for development. Use Kubernetes Secrets in production.

---

## Deployment Commands

```bash
# Apply RBAC
kubectl apply -f config/rbac/role.yaml
kubectl apply -f config/rbac/role_binding.yaml

# Deploy controller
kubectl apply -f config/manager/manager.yaml

# Verify permissions
kubectl auth can-i create secrets --as=system:serviceaccount:threat-scanning-system:controller-manager
# Expected: yes

# Verify environment variables
kubectl get deployment controller-manager -n threat-scanning-system -o yaml | grep -A 15 "env:"
```

---

## Production Setup

### Using Kubernetes Secret (Recommended):

```bash
# Create secret
kubectl create secret generic postgres-credentials \
  -n threat-scanning-system \
  --from-literal=POSTGRES_HOST=postgres.prod.svc \
  --from-literal=POSTGRES_PORT=5432 \
  --from-literal=POSTGRES_USER=scanuser \
  --from-literal=POSTGRES_PASSWORD='<strong-password>' \
  --from-literal=POSTGRES_DASHBOARD_DATABASE=soc_dashboard \
  --from-literal=POSTGRES_CACHE_DATABASE=soc_cache
```

### Update Deployment to Use Secret:

```yaml
# Replace env: section with:
envFrom:
- secretRef:
    name: postgres-credentials
```

---

## Verification

```bash
# 1. Check secret permissions
kubectl describe clusterrole manager-role | grep -A 10 secrets

# 2. Check controller env vars
kubectl get pod -l control-plane=controller-manager -n threat-scanning-system \
  -o jsonpath='{.items[0].spec.containers[0].env[*].name}'

# 3. Test secret creation
kubectl apply -f config/samples/threatscanning_v1_scaninstance.yaml
kubectl get secrets -n threat-scanning-system | grep scan-secret
```

---

**YAML Validation:** ✅ Valid  
**Ready for Deployment:** ✅ Yes
