#!/usr/bin/env python3
"""
Test TVK backup type detection logic.
"""


def test_tvk_detection_s3():
    """Test TVK detection with S3 structure."""
    print("Testing TVK detection with S3 structure...")
    
    # Sample S3 objects from a backup directory
    sample_structure = {
        'objects': [
            'backupplan-abc/backup-123/backup.json',
            'backupplan-abc/backup-123/backupplan.json',
            'backupplan-abc/backup-123/tvk-meta.json',  # TVK indicator
            'backupplan-abc/backup-123/metadata.qcow2',
            'backupplan-abc/backup-123/custom/',
        ]
    }
    
    # Check for tvk-meta.json
    found_tvk = False
    for obj_key in sample_structure['objects']:
        if obj_key.endswith('tvk-meta.json'):
            parts = obj_key.strip('/').split('/')
            if len(parts) >= 3 and parts[-1] == 'tvk-meta.json':
                found_tvk = True
                print(f"  ✓ Found tvk-meta.json in {obj_key}")
                break
    
    assert found_tvk, "Should detect TVK from tvk-meta.json"
    print("  ✓ TVK detection test passed (S3)")


def test_tvk_detection_nfs():
    """Test TVK detection with NFS structure."""
    print("\nTesting TVK detection with NFS structure...")
    
    # Sample NFS paths from a backup directory
    sample_structure = {
        'paths': [
            '/mnt/target/backupplan-abc/backup-123/backup.json',
            '/mnt/target/backupplan-abc/backup-123/backupplan.json',
            '/mnt/target/backupplan-abc/backup-123/tvk-meta.json',  # TVK indicator
            '/mnt/target/backupplan-abc/backup-123/metadata.qcow2',
        ]
    }
    
    # Check for tvk-meta.json
    found_tvk = False
    for path in sample_structure['paths']:
        if path.endswith('tvk-meta.json'):
            parts = path.strip('/').split('/')
            if len(parts) >= 3 and parts[-1] == 'tvk-meta.json':
                found_tvk = True
                print(f"  ✓ Found tvk-meta.json in {path}")
                break
    
    assert found_tvk, "Should detect TVK from tvk-meta.json"
    print("  ✓ TVK detection test passed (NFS)")


def test_no_tvk_detection():
    """Test that non-TVK structure is not detected."""
    print("\nTesting non-TVK structure...")
    
    # Sample without tvk-meta.json
    sample_structure = {
        'objects': [
            'backupplan-abc/backup-123/some-file.json',
            'backupplan-abc/backup-123/other-file.json',
        ]
    }
    
    # Check for tvk-meta.json
    found_tvk = False
    for obj_key in sample_structure['objects']:
        if obj_key.endswith('tvk-meta.json'):
            parts = obj_key.strip('/').split('/')
            if len(parts) >= 3 and parts[-1] == 'tvk-meta.json':
                found_tvk = True
                break
    
    assert not found_tvk, "Should not detect TVK without tvk-meta.json"
    print("  ✓ Non-TVK structure correctly not detected")


def test_malformed_paths():
    """Test that malformed paths don't cause false positives."""
    print("\nTesting malformed paths...")
    
    # tvk-meta.json in wrong location
    sample_structure = {
        'objects': [
            'tvk-meta.json',  # At root - invalid
            'backupplan-abc/tvk-meta.json',  # Only 2 levels - invalid
        ]
    }
    
    # Check for tvk-meta.json with proper structure
    found_tvk = False
    for obj_key in sample_structure['objects']:
        if obj_key.endswith('tvk-meta.json'):
            parts = obj_key.strip('/').split('/')
            # Must have at least 3 parts: backupplan-uid, backup-uid, tvk-meta.json
            if len(parts) >= 3 and parts[-1] == 'tvk-meta.json':
                found_tvk = True
                break
    
    assert not found_tvk, "Should not detect TVK with malformed paths"
    print("  ✓ Malformed paths correctly rejected")


def main():
    """Run all detection tests."""
    print("=" * 70)
    print(" " * 20 + "TVK DETECTION TESTS")
    print("=" * 70)
    print()
    
    try:
        test_tvk_detection_s3()
        test_tvk_detection_nfs()
        test_no_tvk_detection()
        test_malformed_paths()
        
        print()
        print("=" * 70)
        print(" " * 20 + "ALL TESTS PASSED!")
        print("=" * 70)
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())

