# S3fuse File Format

## Overview

When backups are created using s3fuse mount, files are stored in a special **manifest and segment format** rather than as single objects. This is different from NFS where files are stored directly.

## File Naming Convention

### S3 (with s3fuse)
Files are stored as:
```
<filename>.manifest.<hex_number_in_decimal_format>
```

**Example**:
- Original file: `tvk-meta.json`
- S3 object: `tvk-meta.json.manifest.0000000e`

The number after `.manifest.` is a hexadecimal number represented in decimal format.

### NFS (direct mount)
Files are stored directly:
```
<filename>
```

**Example**:
- Original file: `tvk-meta.json`
- NFS file: `tvk-meta.json`

## Detection Logic

### For S3 Targets

The detector checks for manifest files:

```python
# Check for tvk-meta.json.manifest.* (s3fuse format)
manifest_prefix = f'{backup_path}/tvk-meta.json.manifest.'
response = s3_client.list_objects_v2(
    Bucket=bucket_name,
    Prefix=manifest_prefix,
    MaxKeys=1
)

if response.get('Contents'):
    manifest_file = response['Contents'][0]['Key']
    # Example: backupplan-uid/backup-uid/tvk-meta.json.manifest.0000000e
    return 'TVK'
```

**Why `list_objects_v2` instead of `head_object`?**
- We don't know the exact hex number suffix
- We use prefix matching to find any file starting with `tvk-meta.json.manifest.`
- This works for any hex number: `0000000e`, `00000010`, `0000000c`, etc.

### For NFS Targets

The detector checks for the file directly:

```python
# Check for tvk-meta.json (direct file, not manifest format)
tvk_meta_path = os.path.join(backup_path, 'tvk-meta.json')

if os.path.exists(tvk_meta_path):
    return 'TVK'
```

## Example Directory Structures

### S3 Bucket (s3fuse format)
```
shiwam-test/
├── backupplan-abc-123/
│   ├── backup-def-456/
│   │   ├── tvk-meta.json.manifest.0000000e  ← Manifest file
│   │   ├── backup.json.manifest.00000012
│   │   └── metadata/
│   │       └── ...
│   └── backup-ghi-789/
│       ├── tvk-meta.json.manifest.00000010  ← Manifest file
│       └── ...
└── 80bc80ff-0c51-4534-86a2-ec5e719643c2/  ← Data segments (skip)
    └── data.qcow2-segments/
        └── ...
```

### NFS Mount (direct format)
```
/triliodata/
├── backupplan-abc-123/
│   ├── backup-def-456/
│   │   ├── tvk-meta.json  ← Direct file
│   │   ├── backup.json
│   │   └── metadata/
│   │       └── ...
│   └── backup-ghi-789/
│       ├── tvk-meta.json  ← Direct file
│       └── ...
└── ...
```

## Why This Matters

### Detection Phase
- **S3**: Must check for `tvk-meta.json.manifest.*` pattern
- **NFS**: Can check for `tvk-meta.json` directly

### Cleanup Phase
- Both S3 and NFS use the same directory structure
- Only the file naming differs

### Discovery Phase
- S3 API returns manifest files in listings
- Must handle both formats when parsing backup metadata

## Common Pitfalls

### ❌ Wrong: Checking for exact filename on S3
```python
# This will FAIL for S3 targets
s3_client.head_object(Bucket=bucket, Key=f'{path}/tvk-meta.json')
```

### ✅ Correct: Using prefix matching on S3
```python
# This works for S3 targets
response = s3_client.list_objects_v2(
    Bucket=bucket,
    Prefix=f'{path}/tvk-meta.json.manifest.'
)
```

### ❌ Wrong: Using prefix matching on NFS
```python
# Unnecessary for NFS, just use direct file check
os.path.exists(f'{path}/tvk-meta.json')
```

## Hex Number Format

The manifest suffix is a hexadecimal number in decimal format:

| Hex | Decimal | Manifest Suffix |
|-----|---------|-----------------|
| 0xE | 14 | 0000000e |
| 0x10 | 16 | 00000010 |
| 0xC | 12 | 0000000c |
| 0x12 | 18 | 00000012 |

**Format**: 8-digit zero-padded lowercase hexadecimal

## Implementation Details

### Detector (`cleanup/detector.py`)

```python
def _detect_s3(self) -> str:
    """Detect TVK backup type from S3 target using manifest format."""
    # Check for tvk-meta.json.manifest.* pattern
    manifest_prefix = f'{backup_path}/tvk-meta.json.manifest.'
    response = s3_client.list_objects_v2(
        Bucket=bucket_name,
        Prefix=manifest_prefix,
        MaxKeys=1
    )
    
    if response.get('Contents'):
        return 'TVK'
    return 'UNKNOWN'

def _detect_nfs(self, mount_path: str) -> str:
    """Detect TVK backup type from NFS target using direct file."""
    # Check for tvk-meta.json directly
    tvk_meta_path = os.path.join(backup_path, 'tvk-meta.json')
    
    if os.path.exists(tvk_meta_path):
        return 'TVK'
    return 'UNKNOWN'
```

## Testing

### Test S3 Detection
```bash
# Should find: tvk-meta.json.manifest.0000000e
aws s3 ls s3://shiwam-test/backupplan-uid/backup-uid/ | grep manifest
```

### Test NFS Detection
```bash
# Should find: tvk-meta.json
ls /triliodata/backupplan-uid/backup-uid/tvk-meta.json
```

## References

- **s3fuse**: FUSE-based file system backed by Amazon S3
- **Manifest format**: Used to handle large files and enable efficient updates
- **Segment format**: Large files are split into segments for better performance

## Summary

| Aspect | S3 (s3fuse) | NFS (direct) |
|--------|-------------|--------------|
| **Format** | Manifest + Segments | Direct files |
| **tvk-meta.json** | `tvk-meta.json.manifest.<hex>` | `tvk-meta.json` |
| **Detection** | Prefix match with `list_objects_v2` | Direct file check with `os.path.exists` |
| **Example** | `tvk-meta.json.manifest.0000000e` | `tvk-meta.json` |

🎯 **Key Takeaway**: Always use prefix matching for S3 detection, direct file checks for NFS detection.

