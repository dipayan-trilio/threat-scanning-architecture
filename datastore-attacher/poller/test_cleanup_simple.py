#!/usr/bin/env python3
"""
Simple unit test for cleanup functionality without external dependencies.
Tests the core parsing logic in isolation.
"""

from collections import defaultdict
from typing import Dict, Set


def parse_s3_structure(s3_data: Dict) -> Dict[str, Set[str]]:
    """
    Parse S3 directory structure (TVK format).
    Format: 'backupplan-uid/backup-uid/...'
    """
    backupplan_map = defaultdict(set)
    
    for obj_key in s3_data['objects']:
        parts = obj_key.strip('/').split('/')
        if len(parts) >= 2:
            backupplan_uid = parts[0]
            backup_uid = parts[1]
            backupplan_map[backupplan_uid].add(backup_uid)
    
    return dict(backupplan_map)


def parse_nfs_structure(nfs_data: Dict) -> Dict[str, Set[str]]:
    """
    Parse NFS directory structure (TVK format).
    Format: '/mount/backupplan-uid/backup-uid'
    """
    backupplan_map = defaultdict(set)
    
    for path in nfs_data['paths']:
        parts = path.strip('/').split('/')
        if len(parts) >= 2:
            backupplan_uid = parts[-2]  # Second last
            backup_uid = parts[-1]      # Last
            backupplan_map[backupplan_uid].add(backup_uid)
    
    return dict(backupplan_map)


def test_s3_parsing():
    """Test S3 structure parsing."""
    print("Testing S3 structure parsing...")
    
    s3_data = {
        'type': 's3',
        'objects': [
            'backupplan-aaa/backup-111/',
            'backupplan-aaa/backup-222/',
            'backupplan-aaa/backup-333/',
            'backupplan-bbb/backup-444/',
            'backupplan-bbb/backup-555/',
            'backupplan-ccc/backup-666/',
        ],
        'bucket': 'test-bucket'
    }
    
    result = parse_s3_structure(s3_data)
    
    print(f"  Parsed {len(result)} backupplans:")
    for bp_uid, backup_uids in sorted(result.items()):
        print(f"    {bp_uid}: {sorted(backup_uids)}")
    
    # Assertions
    assert len(result) == 3, f"Expected 3 backupplans, got {len(result)}"
    assert len(result['backupplan-aaa']) == 3, "backupplan-aaa should have 3 backups"
    assert len(result['backupplan-bbb']) == 2, "backupplan-bbb should have 2 backups"
    assert len(result['backupplan-ccc']) == 1, "backupplan-ccc should have 1 backup"
    assert 'backup-111' in result['backupplan-aaa']
    assert 'backup-444' in result['backupplan-bbb']
    
    print("  ✓ S3 parsing test passed!")


def test_nfs_parsing():
    """Test NFS structure parsing."""
    print("\nTesting NFS structure parsing...")
    
    nfs_data = {
        'type': 'nfs',
        'paths': [
            '/mnt/target/backupplan-xxx/backup-aaa',
            '/mnt/target/backupplan-xxx/backup-bbb',
            '/mnt/target/backupplan-xxx/backup-ccc',
            '/mnt/target/backupplan-yyy/backup-ddd',
            '/mnt/target/backupplan-yyy/backup-eee',
            '/mnt/target/backupplan-zzz/backup-fff',
        ],
        'mount_path': '/mnt/target'
    }
    
    result = parse_nfs_structure(nfs_data)
    
    print(f"  Parsed {len(result)} backupplans:")
    for bp_uid, backup_uids in sorted(result.items()):
        print(f"    {bp_uid}: {sorted(backup_uids)}")
    
    # Assertions
    assert len(result) == 3, f"Expected 3 backupplans, got {len(result)}"
    assert len(result['backupplan-xxx']) == 3, "backupplan-xxx should have 3 backups"
    assert len(result['backupplan-yyy']) == 2, "backupplan-yyy should have 2 backups"
    assert len(result['backupplan-zzz']) == 1, "backupplan-zzz should have 1 backup"
    assert 'backup-aaa' in result['backupplan-xxx']
    assert 'backup-ddd' in result['backupplan-yyy']
    
    print("  ✓ NFS parsing test passed!")


def test_stale_detection_logic():
    """Test stale ScanInstance detection logic."""
    print("\nTesting stale detection logic...")
    
    # Actual backups in target
    actual_backups = {
        'backupplan-aaa': {'backup-111', 'backup-222'},
        'backupplan-bbb': {'backup-333'},
    }
    
    # ScanInstances in K8s
    scan_instances = {
        'backupplan-aaa': [
            {'name': 'si-1', 'backup_uid': 'backup-111'},  # Valid
            {'name': 'si-2', 'backup_uid': 'backup-222'},  # Valid
            {'name': 'si-3', 'backup_uid': 'backup-999'},  # STALE - backup deleted
        ],
        'backupplan-bbb': [
            {'name': 'si-4', 'backup_uid': 'backup-333'},  # Valid
        ],
        'backupplan-ccc': [  # STALE - entire backupplan deleted
            {'name': 'si-5', 'backup_uid': 'backup-444'},
            {'name': 'si-6', 'backup_uid': 'backup-555'},
        ],
    }
    
    # Detect stale ScanInstances
    stale_instances = []
    
    for bp_uid, si_list in scan_instances.items():
        if bp_uid in actual_backups:
            # Backupplan exists - check individual backups
            actual_backup_uids = actual_backups[bp_uid]
            for si in si_list:
                if si['backup_uid'] not in actual_backup_uids:
                    stale_instances.append((si['name'], 'backup-deleted'))
        else:
            # Backupplan deleted - all ScanInstances are stale
            for si in si_list:
                stale_instances.append((si['name'], 'backupplan-deleted'))
    
    print(f"  Found {len(stale_instances)} stale ScanInstances:")
    for si_name, reason in stale_instances:
        print(f"    {si_name}: {reason}")
    
    # Assertions
    assert len(stale_instances) == 3, f"Expected 3 stale instances, got {len(stale_instances)}"
    assert ('si-3', 'backup-deleted') in stale_instances
    assert ('si-5', 'backupplan-deleted') in stale_instances
    assert ('si-6', 'backupplan-deleted') in stale_instances
    
    print("  ✓ Stale detection test passed!")


def test_edge_cases():
    """Test edge cases."""
    print("\nTesting edge cases...")
    
    # Empty target
    empty_result = parse_s3_structure({'type': 's3', 'objects': []})
    assert len(empty_result) == 0, "Empty target should return empty dict"
    print("  ✓ Empty target handled correctly")
    
    # Malformed paths (should be skipped)
    malformed_data = {
        'type': 's3',
        'objects': [
            'backupplan-aaa/backup-111/',  # Valid
            'single-level/',                # Invalid - should be skipped
            'backupplan-bbb/backup-222/',  # Valid
        ]
    }
    result = parse_s3_structure(malformed_data)
    assert len(result) == 2, "Should skip malformed paths"
    print("  ✓ Malformed paths handled correctly")
    
    # Duplicate backups (should be deduplicated by set)
    duplicate_data = {
        'type': 's3',
        'objects': [
            'backupplan-aaa/backup-111/',
            'backupplan-aaa/backup-111/',  # Duplicate
            'backupplan-aaa/backup-222/',
        ]
    }
    result = parse_s3_structure(duplicate_data)
    assert len(result['backupplan-aaa']) == 2, "Duplicates should be deduplicated"
    print("  ✓ Duplicates handled correctly")


def main():
    """Run all tests."""
    print("=" * 70)
    print(" " * 20 + "CLEANUP UNIT TESTS")
    print("=" * 70)
    print()
    
    try:
        test_s3_parsing()
        test_nfs_parsing()
        test_stale_detection_logic()
        test_edge_cases()
        
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

