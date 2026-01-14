# NFS vs S3 File Formats - Important Clarification

## Overview

This document clarifies the differences between NFS and S3 file formats in TVK backups.

---

## File Format Differences

### NFS (Plain Files)

**Metadata files**:
```
/triliodata/
└── backupplan-uid/
    └── backup-uid/
        ├── tvk-meta.json
        ├── backup.json
        ├── cluster-backup.json
        ├── snapshot.json
        └── cluster-snapshot.json
```

**Characteristics**:
- ✅ Plain JSON files (no manifest format)
- ✅ Standard directory structure
- ❌ No `.manifest.<hex>` files
- ❌ No `-segments` directories
- ❌ No `80bc80ff-...` data segments directory

**Why?**
- NFS writes are direct file operations
- No special mounting mechanism involved
- Standard filesystem semantics

---

### S3 with s3fuse (Manifest Files)

**Metadata files**:
```
s3://bucket/
├── 80bc80ff-0c51-4534-86a2-ec5e719643c2/  ← Data segments (global)
│   └── ... (binary data segments)
│
└── backupplan-uid/
    ├── backup-uid/
    │   ├── tvk-meta.json.manifest.12345678
    │   ├── backup.json.manifest.abcdef12
    │   ├── cluster-backup.json.manifest.fedcba98
    │   └── ...
    │
    └── backup-uid-segments/  ← Backup-specific segments
        └── ... (metadata segments)
```

**Characteristics**:
- ✅ Manifest files (`.json.manifest.<8-hex-digits>`)
- ✅ Segment directories (`-segments` suffix)
- ✅ Global data segments directory (`80bc80ff-...`)
- ❌ Not plain JSON files

**Why?**
- s3fuse uses a special write mechanism
- Files are written in segments for efficiency
- Manifest files point to segments
- This is how s3fuse handles large files and concurrent writes

---

## Implementation Impact

### Detection Logic

**NFS**:
```python
# Look for tvk-meta.json (plain file)
if os.path.exists(os.path.join(backup_dir, 'tvk-meta.json')):
    return 'TVK'
```

**S3**:
```python
# Look for tvk-meta.json.manifest.<hex> pattern
tvk_meta_pattern = re.compile(r'^.+/tvk-meta\.json\.manifest\.[0-9a-f]{8}$')
if tvk_meta_pattern.match(obj_key):
    return 'TVK'
```

---

### Storage State Population

**NFS**:
```python
# Find plain JSON files
find /triliodata \
  -name 'backup.json' \
  -o -name 'cluster-backup.json' \
  -o -name 'snapshot.json' \
  -o -name 'cluster-snapshot.json'

# NO segment filtering
# NO manifest handling
```

**S3**:
```python
# Find manifest files with regex
pattern = r'^(.*?)/(backup|cluster-backup|snapshot|cluster-snapshot)\.json\.manifest\.([0-9a-f]{8})$'

# Filter out segments
if obj_key.startswith('80bc80ff-0c51-4534-86a2-ec5e719643c2/'):
    continue
if '-segments' in backupplan_uid or '-segments' in backup_uid:
    continue
```

---

### Metadata Reading

**NFS**:
```python
# Read directly
with open(f'/triliodata/{backupplan_uid}/{backup_uid}/backup.json', 'r') as f:
    metadata = json.load(f)
```

**S3** (when mounted via s3fuse):
```python
# Try exact match first (won't exist for S3)
exact_path = f'/triliodata/{backupplan_uid}/{backup_uid}/backup.json'
if os.path.exists(exact_path):
    # This won't happen for S3
    pass
else:
    # Find manifest file
    for filename in os.listdir(backup_dir):
        if filename.startswith('backup.json.manifest.'):
            with open(os.path.join(backup_dir, filename), 'r') as f:
                metadata = json.load(f)
```

---

## Code Locations

### Files Updated
- `targetPoller/handlers/tvk_handler.py`
  - `_detect_tvk_s3()` - S3 detection with manifest pattern
  - `_detect_tvk_nfs()` - NFS detection with plain files
  - `_populate_from_s3()` - Filters segments and manifests
  - `_populate_from_nfs()` - No segment filtering (FIXED)

### What Was Fixed
❌ **Before**: NFS code incorrectly filtered out `-segments` directories
```python
# Skip segment directories
if '-segments' in backupplan_uid or '-segments' in backup_uid:
    continue
```

✅ **After**: NFS code removed segment filtering
```python
# (segment filtering removed - S3-specific only)
```

---

## Key Takeaways

1. **Manifest files** (`.manifest.<hex>`) are **S3/s3fuse specific**
   - Not used in NFS
   
2. **Segment directories** (`-segments`) are **S3/s3fuse specific**
   - Not used in NFS
   
3. **Data segments directory** (`80bc80ff-...`) is **S3-specific**
   - Global storage for binary data
   - Not used in NFS

4. **NFS uses plain JSON files**
   - No special formatting
   - Standard file operations
   - Direct reads/writes

5. **Filtering logic should be target-type specific**
   - S3: Filter segments and manifests
   - NFS: No segment filtering needed

---

## Testing Implications

### NFS Testing
```bash
# Should find these files:
/triliodata/backupplan-abc/backup-xyz/backup.json
/triliodata/backupplan-abc/backup-xyz/tvk-meta.json

# Should NOT filter anything for segments
# (all directories are valid backup directories)
```

### S3 Testing
```bash
# Should find these files:
backupplan-abc/backup-xyz/backup.json.manifest.12345678
backupplan-abc/backup-xyz/tvk-meta.json.manifest.abcdef12

# Should filter out:
80bc80ff-0c51-4534-86a2-ec5e719643c2/...  (data segments)
backupplan-abc-segments/...               (metadata segments)
```

---

## References

- **s3fuse documentation**: Explains manifest and segment format
- **datastore-attacher**: Uses s3fuse for S3 mounting
- **TVK backup format**: Defines directory structure
- **Old poller S3FUSE_FORMAT.md**: Original documentation of manifest format

---

## Summary

✅ **NFS = Plain JSON files** (no manifests, no segments)  
✅ **S3 = Manifest files + Segments** (due to s3fuse)  
✅ **Code updated** to not filter segments in NFS path  
✅ **Documentation updated** to clarify the difference  

This is a critical distinction for correct backup discovery! 🎯

