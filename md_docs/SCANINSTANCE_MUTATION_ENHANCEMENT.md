# ScanInstance Mutation Enhancement

## Overview
Enhanced the ScanInstance mutating webhook to automatically populate the Target's `resourceVersion` and `uid` fields in the `backupTarget` reference during ScanInstance creation.

## Changes Made

### 1. Updated `scaninstance_mutator.go`
- Modified `MutateScanInstance` to accept `context.Context` and `client.Client` parameters
- Added logic to fetch the referenced Target resource
- Automatically populates `spec.backupTarget.resourceVersion` and `spec.backupTarget.uid` if not already set
- Returns error if the Target cannot be fetched

### 2. Updated `scaninstance_webhook.go`
- Modified the `ScanInstanceMutator.Handle` method to pass `ctx` and `m.Client` to `MutateScanInstance`

## Behavior

When a ScanInstance is created:

1. **Target Lookup**: The webhook fetches the referenced Target by name
2. **Resource Version**: If `spec.backupTarget.resourceVersion` is empty, it's populated from the Target's `metadata.resourceVersion`
3. **UID**: If `spec.backupTarget.uid` is empty, it's populated from the Target's `metadata.uid`
4. **Error Handling**: If the Target cannot be fetched, the mutation fails with an error

## Benefits

1. **Immutable References**: Captures the exact version of the Target at the time of ScanInstance creation
2. **Audit Trail**: Provides a complete audit trail linking ScanInstances to specific Target versions
3. **Consistency**: Ensures ScanInstances always have complete Target metadata
4. **Automation**: Reduces manual effort - users don't need to specify these fields

## Example

### Before (User Input)
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-scan
spec:
  backupTarget:
    name: minio-target
  backupRef:
    path: /backups/test
```

### After (Mutated by Webhook)
```yaml
apiVersion: threatscanning.trilio.io/v1
kind: ScanInstance
metadata:
  name: test-scan
spec:
  backupTarget:
    apiVersion: threatscanning.trilio.io/v1
    kind: Target
    name: minio-target
    resourceVersion: "12345"
    uid: "abc-123-def-456"
  backupRef:
    path: /backups/test
```

## Testing

Deploy the updated controller and create a ScanInstance:

```bash
# Rebuild and redeploy
make docker-build IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest
make docker-push IMG=eu.gcr.io/amazing-chalice-243510/threat-scanning-controller:latest
kubectl rollout restart deployment threat-scanning-controller -n default

# Create a ScanInstance
kubectl apply -f config/samples/scaninstance.yaml

# Verify the mutation
kubectl get scaninstance test-scan -o yaml | grep -A 5 backupTarget
```

Expected output should show `resourceVersion` and `uid` populated.

## Deployment

The changes are included in the controller binary. No additional configuration or RBAC changes are needed beyond what's already in place for reading Target resources.
