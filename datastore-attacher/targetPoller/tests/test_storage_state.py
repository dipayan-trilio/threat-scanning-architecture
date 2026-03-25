#!/usr/bin/env python3
"""
Unit tests for StorageState model and operations.

Tests the in-memory storage state representation used during cleanup.
"""

import unittest
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from targetPoller.models.storage_state import (
    StorageState, BackupObject, BackupType,
    CleanupMessage, CreationMessage, ScanConfig
)


class TestStorageStateBasics(unittest.TestCase):
    """Test basic StorageState operations"""
    
    def test_empty_storage_state(self):
        """Test empty storage state initialization"""
        # Act
        state = StorageState()
        
        # Assert
        self.assertEqual(state.total_backupplans, 0)
        self.assertEqual(state.total_backups, 0)
        self.assertEqual(len(state.backupplans), 0)
    
    def test_add_single_backup(self):
        """Test adding a single backup"""
        # Arrange
        state = StorageState()
        backup = BackupObject(
            backup_uid='backup-123',
            json_path='plan-1/backup-123/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        
        # Act
        state.add_backup('plan-1', backup)
        
        # Assert
        self.assertEqual(state.total_backupplans, 1)
        self.assertEqual(state.total_backups, 1)
        self.assertTrue(state.has_backupplan('plan-1'))
        self.assertTrue(state.has_backup('plan-1', 'backup-123'))
    
    def test_add_multiple_backups_same_plan(self):
        """Test adding multiple backups to same backupplan"""
        # Arrange
        state = StorageState()
        backups = [
            BackupObject(f'backup-{i}', f'plan-1/backup-{i}/backup.json', datetime.now(), BackupType.BACKUP)
            for i in range(5)
        ]
        
        # Act
        for backup in backups:
            state.add_backup('plan-1', backup)
        
        # Assert
        self.assertEqual(state.total_backupplans, 1)
        self.assertEqual(state.total_backups, 5)
        self.assertEqual(len(state.get_backups('plan-1')), 5)
    
    def test_add_backups_multiple_plans(self):
        """Test adding backups across multiple backupplans"""
        # Arrange
        state = StorageState()
        
        # Act
        for plan_num in range(3):
            for backup_num in range(4):
                backup = BackupObject(
                    backup_uid=f'backup-{backup_num}',
                    json_path=f'plan-{plan_num}/backup-{backup_num}/backup.json',
                    last_updated_timestamp=datetime.now(),
                    type=BackupType.BACKUP
                )
                state.add_backup(f'plan-{plan_num}', backup)
        
        # Assert
        self.assertEqual(state.total_backupplans, 3)
        self.assertEqual(state.total_backups, 12)  # 3 plans * 4 backups
        
        for plan_num in range(3):
            self.assertEqual(len(state.get_backups(f'plan-{plan_num}')), 4)


class TestStorageStateQueries(unittest.TestCase):
    """Test StorageState query operations"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.state = StorageState()
        
        # Add test data
        self.state.add_backup(
            'plan-1',
            BackupObject('backup-1', 'plan-1/backup-1/backup.json', datetime.now(), BackupType.BACKUP)
        )
        self.state.add_backup(
            'plan-1',
            BackupObject('backup-2', 'plan-1/backup-2/backup.json', datetime.now(), BackupType.BACKUP)
        )
        self.state.add_backup(
            'plan-2',
            BackupObject('backup-3', 'plan-2/backup-3/backup.json', datetime.now(), BackupType.CLUSTER_BACKUP)
        )
    
    def test_has_backupplan_exists(self):
        """Test has_backupplan returns True when plan exists"""
        self.assertTrue(self.state.has_backupplan('plan-1'))
        self.assertTrue(self.state.has_backupplan('plan-2'))
    
    def test_has_backupplan_not_exists(self):
        """Test has_backupplan returns False when plan doesn't exist"""
        self.assertFalse(self.state.has_backupplan('plan-999'))
        self.assertFalse(self.state.has_backupplan(''))
    
    def test_has_backup_exists(self):
        """Test has_backup returns True when backup exists"""
        self.assertTrue(self.state.has_backup('plan-1', 'backup-1'))
        self.assertTrue(self.state.has_backup('plan-1', 'backup-2'))
        self.assertTrue(self.state.has_backup('plan-2', 'backup-3'))
    
    def test_has_backup_not_exists(self):
        """Test has_backup returns False when backup doesn't exist"""
        self.assertFalse(self.state.has_backup('plan-1', 'backup-999'))
        self.assertFalse(self.state.has_backup('plan-999', 'backup-1'))
        self.assertFalse(self.state.has_backup('', ''))
    
    def test_get_backup_exists(self):
        """Test get_backup returns correct BackupObject"""
        # Act
        backup = self.state.get_backup('plan-1', 'backup-1')
        
        # Assert
        self.assertIsNotNone(backup)
        self.assertEqual(backup.backup_uid, 'backup-1')
        self.assertEqual(backup.type, BackupType.BACKUP)
    
    def test_get_backup_not_exists(self):
        """Test get_backup returns None when not found"""
        # Act & Assert
        self.assertIsNone(self.state.get_backup('plan-1', 'backup-999'))
        self.assertIsNone(self.state.get_backup('plan-999', 'backup-1'))
    
    def test_get_backups_for_plan(self):
        """Test get_backups returns all backups for plan"""
        # Act
        backups = self.state.get_backups('plan-1')
        
        # Assert
        self.assertEqual(len(backups), 2)
        backup_uids = [b.backup_uid for b in backups]
        self.assertIn('backup-1', backup_uids)
        self.assertIn('backup-2', backup_uids)
    
    def test_get_backups_empty_plan(self):
        """Test get_backups returns empty list for non-existent plan"""
        # Act
        backups = self.state.get_backups('plan-999')
        
        # Assert
        self.assertEqual(len(backups), 0)
        self.assertEqual(backups, [])
    
    def test_get_all_backupplan_uids(self):
        """Test get_all_backupplan_uids returns all UIDs"""
        # Act
        uids = self.state.get_all_backupplan_uids()
        
        # Assert
        self.assertEqual(len(uids), 2)
        self.assertIn('plan-1', uids)
        self.assertIn('plan-2', uids)


class TestBackupObject(unittest.TestCase):
    """Test BackupObject model"""
    
    def test_backup_object_creation(self):
        """Test BackupObject creates correctly"""
        # Arrange
        timestamp = datetime.now()
        
        # Act
        backup = BackupObject(
            backup_uid='backup-123',
            json_path='plan-1/backup-123/backup.json',
            last_updated_timestamp=timestamp,
            type=BackupType.BACKUP
        )
        
        # Assert
        self.assertEqual(backup.backup_uid, 'backup-123')
        self.assertEqual(backup.json_path, 'plan-1/backup-123/backup.json')
        self.assertEqual(backup.last_updated_timestamp, timestamp)
        self.assertEqual(backup.type, BackupType.BACKUP)
        self.assertIsNone(backup.status)
        self.assertIsNone(backup.completion_timestamp)
    
    def test_backup_object_with_optional_fields(self):
        """Test BackupObject with optional status fields"""
        # Arrange & Act
        backup = BackupObject(
            backup_uid='backup-123',
            json_path='plan-1/backup-123/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='Available',
            completion_timestamp=datetime.now()
        )
        
        # Assert
        self.assertEqual(backup.status, 'Available')
        self.assertIsNotNone(backup.completion_timestamp)
    
    def test_backup_object_repr(self):
        """Test BackupObject string representation"""
        # Arrange
        backup = BackupObject(
            backup_uid='backup-123',
            json_path='plan-1/backup-123/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.CLUSTER_BACKUP,
            status='Available'
        )
        
        # Act
        repr_str = repr(backup)
        
        # Assert
        self.assertIn('backup-123', repr_str)
        self.assertIn('cluster-backup', repr_str)
        self.assertIn('Available', repr_str)


class TestBackupType(unittest.TestCase):
    """Test BackupType enum"""
    
    def test_backup_type_values(self):
        """Test BackupType enum values"""
        self.assertEqual(BackupType.BACKUP.value, 'backup')
        self.assertEqual(BackupType.CLUSTER_BACKUP.value, 'cluster-backup')
        self.assertEqual(BackupType.SNAPSHOT.value, 'snapshot')
        self.assertEqual(BackupType.CLUSTER_SNAPSHOT.value, 'cluster-snapshot')
    
    def test_backup_type_json_filename(self):
        """Test BackupType.json_filename property"""
        self.assertEqual(BackupType.BACKUP.json_filename, 'backup.json')
        self.assertEqual(BackupType.CLUSTER_BACKUP.json_filename, 'cluster-backup.json')
        self.assertEqual(BackupType.SNAPSHOT.json_filename, 'snapshot.json')
        self.assertEqual(BackupType.CLUSTER_SNAPSHOT.json_filename, 'cluster-snapshot.json')
    
    def test_backup_type_from_string(self):
        """Test creating BackupType from string"""
        self.assertEqual(BackupType('backup'), BackupType.BACKUP)
        self.assertEqual(BackupType('cluster-backup'), BackupType.CLUSTER_BACKUP)
        
        with self.assertRaises(ValueError):
            BackupType('invalid-type')


class TestCleanupMessage(unittest.TestCase):
    """Test CleanupMessage model"""
    
    def test_cleanup_message_creation(self):
        """Test CleanupMessage creates correctly"""
        # Act
        message = CleanupMessage(
            scaninstance_name='si-123',
            backupplan_uid='plan-456',
            backup_uid='backup-789'
        )
        
        # Assert
        self.assertEqual(message.scaninstance_name, 'si-123')
        self.assertEqual(message.backupplan_uid, 'plan-456')
        self.assertEqual(message.backup_uid, 'backup-789')
    
    def test_cleanup_message_repr(self):
        """Test CleanupMessage string representation"""
        # Arrange
        message = CleanupMessage('si-123', 'plan-456', 'backup-789')
        
        # Act
        repr_str = repr(message)
        
        # Assert
        self.assertIn('si-123', repr_str)
        self.assertIn('CleanupMessage', repr_str)


class TestCreationMessage(unittest.TestCase):
    """Test CreationMessage model"""
    
    def test_creation_message_creation(self):
        """Test CreationMessage creates correctly"""
        # Act
        message = CreationMessage(
            backupplan_uid='plan-123',
            backup_uid='backup-456',
            backup_path='plan-123/backup-456',
            backup_type=BackupType.BACKUP
        )
        
        # Assert
        self.assertEqual(message.backupplan_uid, 'plan-123')
        self.assertEqual(message.backup_uid, 'backup-456')
        self.assertEqual(message.backup_path, 'plan-123/backup-456')
        self.assertEqual(message.backup_type, BackupType.BACKUP)
    
    def test_creation_message_repr(self):
        """Test CreationMessage string representation"""
        # Arrange
        message = CreationMessage('plan-123', 'backup-456', 'path', BackupType.BACKUP)
        
        # Act
        repr_str = repr(message)
        
        # Assert
        self.assertIn('plan-123', repr_str)
        self.assertIn('backup-456', repr_str)


class TestScanConfig(unittest.TestCase):
    """Test ScanConfig model and parsing"""
    
    def test_scan_config_from_dict_full(self):
        """Test ScanConfig.from_dict with complete config"""
        # Arrange
        config_dict = {
            'enabled': True,
            'scanOldBackups': True
        }
        
        # Act
        scan_config = ScanConfig.from_dict(config_dict)
        
        # Assert
        self.assertTrue(scan_config.enabled)
        self.assertTrue(scan_config.scan_old_backups)
    
    def test_scan_config_from_dict_partial(self):
        """Test ScanConfig.from_dict with partial config"""
        # Arrange
        config_dict = {
            'enabled': True
            # Missing scanOldBackups
        }
        
        # Act
        scan_config = ScanConfig.from_dict(config_dict)
        
        # Assert
        self.assertTrue(scan_config.enabled)
        self.assertFalse(scan_config.scan_old_backups)  # Default False
    
    def test_scan_config_from_dict_none(self):
        """Test ScanConfig.from_dict with None"""
        # Act
        scan_config = ScanConfig.from_dict(None)
        
        # Assert
        self.assertFalse(scan_config.enabled)
        self.assertFalse(scan_config.scan_old_backups)
    
    def test_scan_config_from_dict_empty(self):
        """Test ScanConfig.from_dict with empty dict"""
        # Act
        scan_config = ScanConfig.from_dict({})
        
        # Assert
        self.assertFalse(scan_config.enabled)
        self.assertFalse(scan_config.scan_old_backups)


class TestStorageStateComplexOperations(unittest.TestCase):
    """Test complex StorageState operations for cleanup scenarios"""
    
    def setUp(self):
        """Set up test fixtures with complex state"""
        self.state = StorageState()
        
        # Add multiple backupplans with multiple backups
        for plan_num in range(3):
            plan_uid = f'plan-{plan_num}'
            for backup_num in range(5):
                backup = BackupObject(
                    backup_uid=f'backup-{plan_num}-{backup_num}',
                    json_path=f'{plan_uid}/backup-{plan_num}-{backup_num}/backup.json',
                    last_updated_timestamp=datetime.now() - timedelta(hours=backup_num),
                    type=BackupType.BACKUP
                )
                self.state.add_backup(plan_uid, backup)
    
    def test_query_multiple_backupplans(self):
        """Test querying multiple backupplans"""
        # Act & Assert
        self.assertTrue(self.state.has_backupplan('plan-0'))
        self.assertTrue(self.state.has_backupplan('plan-1'))
        self.assertTrue(self.state.has_backupplan('plan-2'))
        self.assertFalse(self.state.has_backupplan('plan-3'))
    
    def test_query_backups_across_plans(self):
        """Test querying backups across different plans"""
        # Act & Assert
        self.assertTrue(self.state.has_backup('plan-0', 'backup-0-0'))
        self.assertTrue(self.state.has_backup('plan-1', 'backup-1-3'))
        self.assertTrue(self.state.has_backup('plan-2', 'backup-2-4'))
        
        # Cross-plan queries should fail
        self.assertFalse(self.state.has_backup('plan-0', 'backup-1-0'))
        self.assertFalse(self.state.has_backup('plan-1', 'backup-0-0'))
    
    def test_get_all_backupplan_uids(self):
        """Test get_all_backupplan_uids returns complete list"""
        # Act
        uids = self.state.get_all_backupplan_uids()
        
        # Assert
        self.assertEqual(len(uids), 3)
        self.assertEqual(set(uids), {'plan-0', 'plan-1', 'plan-2'})
    
    def test_get_backups_sorted_by_timestamp(self):
        """Test backups maintain timestamp ordering"""
        # Act
        backups = self.state.get_backups('plan-0')
        
        # Assert
        self.assertEqual(len(backups), 5)
        # Verify all backups are present
        backup_uids = [b.backup_uid for b in backups]
        for i in range(5):
            self.assertIn(f'backup-0-{i}', backup_uids)


class TestStorageStateWithDifferentBackupTypes(unittest.TestCase):
    """Test StorageState with different backup types"""
    
    def test_add_different_backup_types(self):
        """Test adding backups of different types"""
        # Arrange
        state = StorageState()
        backup_types = [
            BackupType.BACKUP,
            BackupType.CLUSTER_BACKUP,
            BackupType.SNAPSHOT,
            BackupType.CLUSTER_SNAPSHOT
        ]
        
        # Act
        for i, btype in enumerate(backup_types):
            backup = BackupObject(
                backup_uid=f'backup-{i}',
                json_path=f'plan-1/backup-{i}/{btype.json_filename}',
                last_updated_timestamp=datetime.now(),
                type=btype
            )
            state.add_backup('plan-1', backup)
        
        # Assert
        self.assertEqual(state.total_backups, 4)
        backups = state.get_backups('plan-1')
        types_found = [b.type for b in backups]
        self.assertEqual(set(types_found), set(backup_types))
    
    def test_query_mixed_backup_types(self):
        """Test querying backups with mixed types in same plan"""
        # Arrange
        state = StorageState()
        
        state.add_backup(
            'plan-1',
            BackupObject('backup-1', 'plan-1/backup-1/backup.json', datetime.now(), BackupType.BACKUP)
        )
        state.add_backup(
            'plan-1',
            BackupObject('backup-2', 'plan-1/backup-2/cluster-backup.json', datetime.now(), BackupType.CLUSTER_BACKUP)
        )
        
        # Act & Assert
        self.assertTrue(state.has_backup('plan-1', 'backup-1'))
        self.assertTrue(state.has_backup('plan-1', 'backup-2'))
        
        backup_1 = state.get_backup('plan-1', 'backup-1')
        backup_2 = state.get_backup('plan-1', 'backup-2')
        
        self.assertEqual(backup_1.type, BackupType.BACKUP)
        self.assertEqual(backup_2.type, BackupType.CLUSTER_BACKUP)


class TestStorageStateEdgeCases(unittest.TestCase):
    """Test StorageState edge cases"""
    
    def test_add_duplicate_backup_uid(self):
        """Test adding backup with duplicate UID (should be allowed)"""
        # Arrange
        state = StorageState()
        
        # Act - add same backup_uid twice
        state.add_backup(
            'plan-1',
            BackupObject('backup-1', 'path1', datetime.now(), BackupType.BACKUP)
        )
        state.add_backup(
            'plan-1',
            BackupObject('backup-1', 'path2', datetime.now(), BackupType.BACKUP)
        )
        
        # Assert - both should be stored
        backups = state.get_backups('plan-1')
        self.assertEqual(len(backups), 2)
    
    def test_empty_backupplan_uid(self):
        """Test operations with empty backupplan UID"""
        # Arrange
        state = StorageState()
        
        # Act
        state.add_backup(
            '',
            BackupObject('backup-1', 'path', datetime.now(), BackupType.BACKUP)
        )
        
        # Assert
        self.assertTrue(state.has_backupplan(''))
        self.assertTrue(state.has_backup('', 'backup-1'))
        self.assertEqual(state.total_backupplans, 1)
    
    def test_very_long_uids(self):
        """Test operations with very long UIDs"""
        # Arrange
        state = StorageState()
        long_uid = 'x' * 1000
        
        # Act
        state.add_backup(
            long_uid,
            BackupObject('backup-1', 'path', datetime.now(), BackupType.BACKUP)
        )
        
        # Assert
        self.assertTrue(state.has_backupplan(long_uid))
        self.assertTrue(state.has_backup(long_uid, 'backup-1'))
    
    def test_storage_state_repr(self):
        """Test StorageState string representation"""
        # Arrange
        state = StorageState()
        state.add_backup(
            'plan-1',
            BackupObject('backup-1', 'path', datetime.now(), BackupType.BACKUP)
        )
        state.add_backup(
            'plan-2',
            BackupObject('backup-2', 'path', datetime.now(), BackupType.BACKUP)
        )
        
        # Act
        repr_str = repr(state)
        
        # Assert
        self.assertIn('backupplans=2', repr_str)
        self.assertIn('backups=2', repr_str)


if __name__ == '__main__':
    unittest.main()
