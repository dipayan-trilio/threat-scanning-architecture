# Controller RBAC and Deployment Updates

**Date:** March 26, 2026  
**Status:** ✅ Complete

---

## Changes Made

### 1. ClusterRole: Added Secret Permissions ✅

**File:** `config/rbac/role.yaml`

Added full CRUD permissions for Secrets to allow the controller to create and manage PostgreSQL secrets for scan jobs.

#### Updated Permissions:

```yaml
- apiGroups:
  - ""
  resources:
  - secrets
  verbs:
  - create    # ← NEW
  - delete    # ← NEW
  - get
  - list
  - patch     # ← NEW
  - update    # ← NEW
  - watch
```

#### Before:
- Only had: `get`, `list`, `watch` (read-only)

#### After:
- Full permissions: `create`, `delete`, `get`, `list`, `patch`, `update`, `watch`

**Reason:** Controller needs to create `scan-secret-<name>` for each ScanInstance with PostgreSQL credentials.

---

### 2. Deployment: Added PostgreSQL Environment Variables ✅

**File:** `config/manager/manager.yaml`

Added PostgreSQL configuration environment variables to the controller deployment with dummy/example values.

#### Added Environment Variables:

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

**Note:** These are dummy values for development/testing. In production, these should be:
- Loaded from a Kubernetes Secret (using `envFrom`)
- Or configured via ConfigMap
- Or passed through deployment parameters

---

## Complete RBAC Rules

The controller now has permissions for:

| Resource | Permissions |
|----------|-------------|
| ConfigMaps | Full CRUD |
| PersistentVolumeClaims | Full CRUD |
| PersistentVolumes | Full CRUD |
| Services | Full CRUD |
| Events | Create, Patch |
| **Secrets** | **Full CRUD** ✅ |
| Deployments | Full CRUD |
| Jobs | Full CRUD |
| ScanInstances | Full CRUD + Status |
| Targets | Full CRUD + Status |

---

## Complete Deployment Spec

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: controller-manager
  namespace: system
spec:
  replicas: 1
  selector:
    matchLabels:
      control-plane: controller-manager
  template:
    metadata:
      labels:
        control-plane: controller-manager
    spec:
      serviceAccountName: controller-manager
      containers:
      - name: manager
        image: controller:latest
        command:
        - /manager
        args:
        - --leader-elect
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
        resources:
          limits:
            cpu: 500m
            memory: 512Mi
          requests:
            cpu: 100m
            memory: 128Mi
```

---

## Deployment Instructions

### 1. Apply Updated RBAC:
```bash
kubectl apply -f config/rbac/role.yaml
kubectl apply -f config/rbac/role_binding.yaml
```

### 2. Deploy Controller with Environment Variables:
```bash
kubectl apply -f config/manager/manager.yaml
```

### 3. Verify Permissions:
```bash
# Check ClusterRole
kubectl get clusterrole manager-role -o yaml | grep -A 10 "secrets"

# Should show all verbs: create, delete, get, list, patch, update, watch
```

### 4. Verify Environment Variables:
```bash
# Check deployment
kubectl get deployment controller-manager -n threat-scanning-system -o yaml | grep -A 20 "env:"

# Should see all POSTGRES_* environment variables
```

### 5. Verify Controller Functionality:
```bash
# Check controller logs for PostgreSQL connection
kubectl logs -l control-plane=controller-manager -n threat-scanning-system | grep -i postgres

# Create a test ScanInstance
kubectl apply -f config/samples/threatscanning_v1_scaninstance.yaml

# Verify Secret was created
kubectl get secrets -n threat-scanning-system | grep scan-secret
```

---

## Production Configuration

For production deployment, replace hardcoded values with secrets:

### Option 1: Using envFrom (Recommended)
```yaml
env: []
envFrom:
- secretRef:
    name: postgres-credentials
```

### Option 2: Using valueFrom
```yaml
env:
- name: POSTGRES_HOST
  valueFrom:
    secretKeyRef:
      name: postgres-credentials
      key: host
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: postgres-credentials
      key: password
# ... etc
```

### Create Production Secret:
```bash
kubectl create secret generic postgres-credentials \
  -n threat-scanning-system \
  --from-literal=POSTGRES_HOST=postgres.prod.svc.cluster.local \
  --from-literal=POSTGRES_PORT=5432 \
  --from-literal=POSTGRES_USER=scanuser \
  --from-literal=POSTGRES_PASSWORD='<strong-password>' \
  --from-literal=POSTGRES_DASHBOARD_DATABASE=soc_dashboard \
  --from-literal=POSTGRES_CACHE_DATABASE=soc_cache
```

---

## Security Notes

⚠️ **IMPORTANT:**
- Current deployment uses **plaintext dummy password** for development only
- **DO NOT** use in production
- Use Kubernetes Secrets for production deployments
- Consider using secret management tools (e.g., Vault, Sealed Secrets)
- Rotate credentials regularly
- Use strong passwords for PostgreSQL

---

## Testing Checklist

- [ ] ClusterRole updated with secret permissions
- [ ] Deployment includes all POSTGRES_* environment variables
- [ ] Controller can create secrets (check RBAC)
- [ ] Controller reads environment variables correctly
- [ ] Scan jobs receive PostgreSQL credentials via secrets
- [ ] Scan jobs can connect to PostgreSQL
- [ ] Database setup script runs successfully
- [ ] Reports are uploaded successfully

---

## Troubleshooting

### Controller Can't Create Secrets:
```bash
# Check RBAC
kubectl auth can-i create secrets --as=system:serviceaccount:threat-scanning-system:controller-manager

# Should return: yes
```

### Environment Variables Not Set:
```bash
# Check pod environment
kubectl get pod -l control-plane=controller-manager -n threat-scanning-system -o yaml | grep -A 20 "env:"
```

### Secret Not Created for Scan Job:
```bash
# Check controller logs
kubectl logs -l control-plane=controller-manager -n threat-scanning-system | grep -i "secret"

# Check for secret
kubectl get secrets -n threat-scanning-system | grep scan-secret
```

---

**Files Modified:**
- ✅ `config/rbac/role.yaml` - Added secret CRUD permissions
- ✅ `config/manager/manager.yaml` - Added PostgreSQL environment variables

**Status:** Complete and Ready ✅
