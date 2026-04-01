# Report Uploader - Annotation-Based Target Validation

## Overview

The `report-uploader` CLI has been updated to identify reporting targets using **annotations** instead of spec fields.

## Reporting Target Identification

### Annotation Required

Reporting targets are identified by the annotation:

```yaml
metadata:
  annotations:
    trilio.io/reporting-target: "true"
```

### Complete Target Example

```yaml
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-prod
  annotations:
    trilio.io/reporting-target: "true"  # ← Required for reporting target
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    credentialSecret:
      name: s3-credentials
      namespace: default
    bucketName: my-reports-bucket
    region: us-west-2
    url: https://s3.amazonaws.com
```

## Validation Process

The CLI validates targets in this order:

1. ✅ Check if target has annotations
2. ✅ Check if `trilio.io/reporting-target` annotation exists
3. ✅ Check if annotation value is `"true"`
4. ✅ Check if storage type is `ObjectStore` (not NFS)

## Error Messages

### Missing Annotations

```
RuntimeError: Target reporting-target does not have any annotations.
Cannot determine if this is a reporting target.
Reporting targets should have annotation 'trilio.io/reporting-target=true'
```

**Solution**: Add annotations section to target metadata.

### Missing Reporting Annotation

```
ValueError: Target reporting-target is not a reporting target.
Expected annotation 'trilio.io/reporting-target=true',
found 'trilio.io/reporting-target=(not set)'
```

**Solution**: Add the `trilio.io/reporting-target: "true"` annotation.

### Wrong Annotation Value

```
ValueError: Target my-target is not a reporting target.
Expected annotation 'trilio.io/reporting-target=true',
found 'trilio.io/reporting-target=false'
```

**Solution**: Set annotation value to `"true"`.

## Why Annotations?

Annotations are used instead of spec fields because:

1. **Flexibility**: Annotations don't require CRD schema changes
2. **Compatibility**: Works with existing Target CRD definitions
3. **Consistency**: Matches how targetPoller identifies reporting targets
4. **Standards**: Follows Kubernetes conventions for metadata

## Checking Target Annotation

### Using kubectl

```bash
# Check if target has reporting annotation
kubectl get target reporting-target -o yaml | grep -A 5 annotations

# Should show:
#   annotations:
#     trilio.io/reporting-target: "true"
```

### Using kubectl get with jsonpath

```bash
# Get annotation value directly
kubectl get target reporting-target \
  -o jsonpath='{.metadata.annotations.trilio\.io/reporting-target}'

# Should output: true
```

## Adding Annotation to Existing Target

### Using kubectl annotate

```bash
kubectl annotate target reporting-target \
  trilio.io/reporting-target=true
```

### Using kubectl patch

```bash
kubectl patch target reporting-target --type=merge -p '
{
  "metadata": {
    "annotations": {
      "trilio.io/reporting-target": "true"
    }
  }
}'
```

### Using YAML manifest

```bash
cat <<EOF | kubectl apply -f -
apiVersion: threatscanning.trilio.io/v1
kind: Target
metadata:
  name: reporting-target
  annotations:
    trilio.io/reporting-target: "true"
spec:
  type: ObjectStore
  vendor: AWS
  objectStoreCredentials:
    credentialSecret:
      name: s3-creds
      namespace: default
    bucketName: my-bucket
EOF
```

## Testing

### Verify Annotation Works

```bash
# 1. Add annotation to target
kubectl annotate target reporting-target trilio.io/reporting-target=true

# 2. Run report-uploader
report-uploader --target-name reporting-target \
                --upload-directory /tmp/test \
                --object-prefix test/

# Should see:
# ✓ Verified target reporting-target is a reporting target
```

### Test Without Annotation

```bash
# 1. Remove annotation
kubectl annotate target backup-target trilio.io/reporting-target-

# 2. Try to use as reporting target
report-uploader --target-name backup-target \
                --upload-directory /tmp/test \
                --object-prefix test/

# Should fail with:
# ValueError: Target backup-target is not a reporting target.
# Expected annotation 'trilio.io/reporting-target=true', found '(not set)'
```

## Implementation Details

### Code Location

```python
# File: report_uploader/cli.py
# Function: validate_reporting_target()

def validate_reporting_target(target_cr: dict, target_name: str) -> None:
    """Validate that target is a reporting target using annotation."""
    
    # Check for reporting target annotation
    annotations = target_cr.get('metadata', {}).get('annotations', {})
    
    if not annotations:
        raise RuntimeError(
            f"Target {target_name} does not have any annotations. "
            f"Cannot determine if this is a reporting target. "
            f"Reporting targets should have annotation 'trilio.io/reporting-target=true'"
        )
    
    is_reporting = annotations.get('trilio.io/reporting-target', '').lower()
    
    if is_reporting != 'true':
        found_value = is_reporting if is_reporting else '(not set)'
        raise ValueError(
            f"Target {target_name} is not a reporting target. "
            f"Expected annotation 'trilio.io/reporting-target=true', "
            f"found 'trilio.io/reporting-target={found_value}'"
        )
    
    logging.info(f"✓ Verified target {target_name} is a reporting target")
```

### Consistent with targetPoller

This approach matches how the targetPoller identifies reporting targets:

```python
# File: targetPoller/main.py

# Find reporting target (annotation: trilio.io/reporting-target=true)
for target in targets:
    annotations = target.get('metadata', {}).get('annotations', {})
    if annotations.get('trilio.io/reporting-target') == 'true':
        # This is the reporting target
        return target
```

## Migration Notes

If you have existing documentation or scripts that reference `spec.targetType`, update them to use annotations instead:

### Before (spec field - NOT SUPPORTED)

```yaml
spec:
  targetType: reporting  # ❌ NOT USED
```

### After (annotation - CORRECT)

```yaml
metadata:
  annotations:
    trilio.io/reporting-target: "true"  # ✅ CORRECT
```

## FAQ

**Q: Can a target be both backup and reporting?**

A: Yes, if it has the annotation `trilio.io/reporting-target: "true"`, it can be used for reporting. The spec can still define backup-related configuration.

**Q: Is the annotation case-sensitive?**

A: The annotation key is case-sensitive (`trilio.io/reporting-target`), but the value is compared case-insensitively (`"true"` or `"True"` both work).

**Q: What if I have multiple targets with the annotation?**

A: You must specify which one to use via `--target-name`. The CLI validates the specific target you provide.

**Q: Can I use labels instead of annotations?**

A: No, the CLI specifically checks annotations. Labels and annotations serve different purposes in Kubernetes.

## Summary

✅ **Use annotation** `trilio.io/reporting-target: "true"` to mark reporting targets

✅ **Compatible** with existing Target CRD schema

✅ **Consistent** with targetPoller behavior

✅ **Flexible** - no CRD changes needed

✅ **Standard** Kubernetes approach for metadata

---

**Updated**: 2026-03-26
**Status**: Production Ready
