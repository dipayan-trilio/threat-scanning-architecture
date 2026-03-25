#!/usr/bin/env python3
"""
Quick test of the cleanup test suite.

Runs a subset of tests to verify the implementation works.
This script can run without installing ALL dependencies.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def quick_test():
    """Run quick smoke tests"""
    print("=" * 80)
    print("  Quick Test - Storage State (No Dependencies Required)")
    print("=" * 80)
    print()
    
    try:
        # Test 1: Import storage state
        print("✓ Importing storage state models...")
        from targetPoller.models.storage_state import (
            StorageState, BackupObject, BackupType, CleanupMessage
        )
        print("  SUCCESS: All models imported")
        
        # Test 2: Create storage state
        print("\n✓ Creating storage state...")
        state = StorageState()
        print(f"  SUCCESS: Created {state}")
        
        # Test 3: Add backup
        print("\n✓ Adding backup to storage state...")
        from datetime import datetime
        backup = BackupObject(
            backup_uid='test-backup-123',
            json_path='plan-1/test-backup-123/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        state.add_backup('plan-1', backup)
        print(f"  SUCCESS: Storage state has {state.total_backups} backup(s)")
        
        # Test 4: Query operations
        print("\n✓ Testing query operations...")
        assert state.has_backupplan('plan-1') == True
        assert state.has_backup('plan-1', 'test-backup-123') == True
        assert state.has_backup('plan-1', 'nonexistent') == False
        print("  SUCCESS: All queries work correctly")
        
        # Test 5: Create cleanup message
        print("\n✓ Creating cleanup message...")
        message = CleanupMessage(
            scaninstance_name='test-si',
            backupplan_uid='plan-1',
            backup_uid='backup-1'
        )
        print(f"  SUCCESS: {message}")
        
        print("\n" + "=" * 80)
        print("  ✅ All Quick Tests Passed!")
        print("=" * 80)
        print()
        print("Next steps:")
        print("  1. Install test dependencies: ./setup_tests.sh")
        print("  2. Run full test suite: python3 run_unittest.py")
        print()
        
        return 0
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(quick_test())
