#!/usr/bin/env python3
"""
Simple test script for cleanup functionality.
This is a basic test to verify the cleanup logic works correctly.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from cleanup.tvk_handler import TVKBackupTargetHandler
from cleanup.factory import BackupTargetHandlerFactory


def test_parse_directory_structure():
    """Test parsing of S3 and NFS directory structures."""
    print("Testing directory structure parsing...")
    
    # Mock target CR
    mock_target = {
        'metadata': {
            'name': 'test-target',
            'uid': 'test-uid-123',
        },
        'spec': {
            'type': 'ObjectStore',
            'vendor': 'AWS',
            'objectStoreCredentials': {
                'bucketName': 'test-bucket',
                'credentialSecret': {
                    'name': 'test-secret',
                    'namespace': 'default'
                }
            }
        },
        'status': {
            'status': 'Available'
        }
    }
    
    # Mock K8s client
    class MockK8sClient:
        def list_scan_instances(self, label_selector=None):
            return []
        
        def delete_scan_instance(self, name):
            return True
    
    # Mock logger
    class MockLogger:
        def info(self, msg): print(f"INFO: {msg}")
        def debug(self, msg): print(f"DEBUG: {msg}")
        def warning(self, msg): print(f"WARN: {msg}")
        def error(self, msg, exc_info=False): print(f"ERROR: {msg}")
    
    # Create handler
    handler = TVKBackupTargetHandler(mock_target, MockK8sClient(), MockLogger())
    
    # Test S3 structure parsing
    s3_data = {
        'type': 's3',
        'objects': [
            'backupplan-aaa/backup-111/',
            'backupplan-aaa/backup-222/',
            'backupplan-bbb/backup-333/',
        ],
        'bucket': 'test-bucket'
    }
    
    result = handler.parse_directory_structure(s3_data)
    print(f"\nS3 Parsing Result:")
    print(f"  Backupplans: {len(result)}")
    for bp_uid, backup_uids in result.items():
        print(f"  {bp_uid}: {backup_uids}")
    
    assert len(result) == 2, "Should have 2 backupplans"
    assert len(result['backupplan-aaa']) == 2, "backupplan-aaa should have 2 backups"
    assert len(result['backupplan-bbb']) == 1, "backupplan-bbb should have 1 backup"
    
    # Test NFS structure parsing
    nfs_data = {
        'type': 'nfs',
        'paths': [
            '/mnt/target/backupplan-xxx/backup-aaa',
            '/mnt/target/backupplan-xxx/backup-bbb',
            '/mnt/target/backupplan-yyy/backup-ccc',
        ],
        'mount_path': '/mnt/target'
    }
    
    result = handler.parse_directory_structure(nfs_data)
    print(f"\nNFS Parsing Result:")
    print(f"  Backupplans: {len(result)}")
    for bp_uid, backup_uids in result.items():
        print(f"  {bp_uid}: {backup_uids}")
    
    assert len(result) == 2, "Should have 2 backupplans"
    assert len(result['backupplan-xxx']) == 2, "backupplan-xxx should have 2 backups"
    assert len(result['backupplan-yyy']) == 1, "backupplan-yyy should have 1 backup"
    
    print("\n✓ All parsing tests passed!")


def test_factory():
    """Test handler factory."""
    print("\n" + "="*60)
    print("Testing handler factory...")
    
    # Mock target with TVK annotation
    mock_target_tvk = {
        'metadata': {
            'name': 'test-target',
            'uid': 'test-uid-123',
            'annotations': {
                'trilio.io/backup-type': 'TVK'
            }
        },
        'spec': {
            'type': 'ObjectStore',
            'vendor': 'AWS',
            'objectStoreCredentials': {
                'bucketName': 'test-bucket',
                'credentialSecret': {
                    'name': 'test-secret',
                    'namespace': 'default'
                }
            }
        }
    }
    
    # Mock K8s client and logger
    class MockK8sClient:
        pass
    
    class MockLogger:
        def info(self, msg): print(f"INFO: {msg}")
    
    handler = BackupTargetHandlerFactory.create_handler(
        mock_target_tvk, MockK8sClient(), MockLogger()
    )
    
    assert handler.backup_type == 'TVK', "Should create TVK handler"
    print(f"✓ Factory correctly created {handler.backup_type} handler")
    
    # Test default (no annotation)
    mock_target_default = {
        'metadata': {
            'name': 'test-target',
            'uid': 'test-uid-123',
        },
        'spec': {
            'type': 'NFS',
            'vendor': 'Other',
            'nfsCredentials': {
                'nfsExport': '192.168.1.1:/data'
            }
        }
    }
    
    handler = BackupTargetHandlerFactory.create_handler(
        mock_target_default, MockK8sClient(), MockLogger()
    )
    
    assert handler.backup_type == 'TVK', "Should default to TVK handler"
    print(f"✓ Factory correctly defaulted to {handler.backup_type} handler")
    
    print("✓ All factory tests passed!")


def main():
    """Run all tests."""
    print("="*60)
    print(" " * 15 + "CLEANUP TESTS")
    print("="*60)
    
    try:
        test_parse_directory_structure()
        test_factory()
        
        print("\n" + "="*60)
        print(" " * 15 + "ALL TESTS PASSED!")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

