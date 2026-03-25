#!/usr/bin/env python3
"""
Unit tests for targetPoller discovery functionality.

Tests the discovery phase logic using mocks to avoid external dependencies.
Focuses on:
- Storage state refresh
- Backup availability checking
- ScanConfig reading and processing
- Cluster backup hierarchy (ownerReferences)
- Queue message creation for ScanInstance creation
- scanOldBackups flag handling
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call, mock_open
from datetime import datetime, timedelta
import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from targetPoller.handlers.base_handler import BaseTargetHandler
from targetPoller.models.storage_state import (
    StorageState, BackupObject, BackupType,
    CreationMessage, ScanConfig
)
from targetPoller.workers.queue_workers import WorkerPool


class MockHandler(BaseTargetHandler):
    """Concrete implementation of BaseTargetHandler for testing"""
    
    def populate_storage_state(self):
        return StorageState()
    
    def refresh_storage_state(self):
        # Override in tests
        pass
    
    def _read_scan_config(self, backupplan_uid, backup):
        # Override in tests
        return None


class TestDiscoveryBasicLogic(unittest.TestCase):
    """Test basic discovery logic and control flow"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        # Create mock target CR
        self.target_cr = {
            'metadata': {
                'name': 'test-target',
                'uid': 'target-uid-123'
            },
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {
                        'name': 'test-secret',
                        'namespace': 'default'
                    },
                    'skipCertVerification': True
                }
            }
        }
        
        # Create handler
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {
                'storageType': 'objectstore'
            }
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        # Mock worker pool
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
    
    def test_discovery_with_empty_storage_state(self):
        """Test discovery when no backupplans exist"""
        # Arrange
        self.handler.storage_state = StorageState()
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.handler.worker_pool.creation_queue.put.assert_not_called()
        self.handler.worker_pool.wait_for_creation_completion.assert_not_called()
    
    def test_discovery_with_backupplan_no_backups(self):
        """Test discovery when backupplan exists but has no backups"""
        # Arrange
        self.handler.storage_state = StorageState()
        self.handler.storage_state.backupplans['plan-1'] = []
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.handler.worker_pool.creation_queue.put.assert_not_called()
    
    def test_discovery_refresh_storage_state_called(self):
        """Test that refresh_storage_state is called at start of discovery"""
        # Arrange
        refresh_called = False
        def mock_refresh():
            nonlocal refresh_called
            refresh_called = True
        
        self.handler.refresh_storage_state = mock_refresh
        self.handler.storage_state = StorageState()
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.assertTrue(refresh_called)


class TestDiscoveryBackupAvailability(unittest.TestCase):
    """Test backup availability checking"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {'name': 'test-target', 'uid': 'target-uid-123'},
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {'name': 'test-secret', 'namespace': 'default'},
                    'skipCertVerification': True
                }
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {'storageType': 'objectstore'}
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_backup_available_status(self, mock_path_join, mock_file):
        """Test backup with Available status is processed"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        
        # Act
        result = self.handler._is_backup_available(backup)
        
        # Assert
        self.assertTrue(result)
        self.assertEqual(backup.status, 'available')
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Failed"}}')
    @patch('os.path.join')
    def test_backup_failed_status(self, mock_path_join, mock_file):
        """Test backup with Failed status is skipped"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        
        # Act
        result = self.handler._is_backup_available(backup)
        
        # Assert
        self.assertFalse(result)
        self.assertEqual(backup.status, 'failed')
    
    @patch('builtins.open', side_effect=FileNotFoundError())
    @patch('os.path.join')
    def test_backup_json_not_exists_inprogress(self, mock_path_join, mock_file):
        """Test backup JSON not exists (in-progress backup) is skipped"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        
        # Act
        result = self.handler._is_backup_available(backup)
        
        # Assert
        self.assertFalse(result)
    
    @patch('builtins.open', side_effect=PermissionError())
    @patch('os.path.join')
    def test_backup_json_permission_error(self, mock_path_join, mock_file):
        """Test backup JSON read error (permission) is handled gracefully"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        
        # Act
        result = self.handler._is_backup_available(backup)
        
        # Assert
        self.assertFalse(result)


class TestDiscoveryScanConfigScenarios(unittest.TestCase):
    """Test scanConfig reading and processing scenarios"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {'name': 'test-target', 'uid': 'target-uid-123'},
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {'name': 'test-secret', 'namespace': 'default'},
                    'skipCertVerification': True
                }
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {'storageType': 'objectstore'}
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        # Mock scaninstance map
        self.handler.scaninstance_map = {}
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_scan_config_enabled_false(self, mock_path_join, mock_file):
        """Test scanConfig.enabled=false skips the backupplan"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup)
        
        # Mock _read_scan_config to return disabled config
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=False, scan_old_backups=False))
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.handler.worker_pool.creation_queue.put.assert_not_called()
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_scan_config_enabled_true_scan_old_backups_false(self, mock_path_join, mock_file):
        """Test scanConfig.enabled=true, scanOldBackups=false processes only latest"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup)
        
        # Mock _read_scan_config
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        
        # Mock _has_scaninstance to return False
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_uid, 'backup-1')
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_scan_config_enabled_true_scan_old_backups_true(self, mock_path_join, mock_file):
        """Test scanConfig.enabled=true, scanOldBackups=true processes all backups"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        self.handler.storage_state = StorageState()
        backup1 = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime(2024, 1, 3),
            type=BackupType.BACKUP
        )
        backup2 = BackupObject(
            backup_uid='backup-2',
            json_path='plan-1/backup-2/backup.json',
            last_updated_timestamp=datetime(2024, 1, 2),
            type=BackupType.BACKUP
        )
        backup3 = BackupObject(
            backup_uid='backup-3',
            json_path='plan-1/backup-3/backup.json',
            last_updated_timestamp=datetime(2024, 1, 1),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup1)
        self.handler.storage_state.add_backup('plan-1', backup2)
        self.handler.storage_state.add_backup('plan-1', backup3)
        
        # Mock _read_scan_config
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=True))
        
        # Mock _has_scaninstance to return False for all
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should queue all 3 backups
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 3)
    
    def test_scan_config_missing_returns_none(self):
        """Test missing scanConfig (file not found) skips backupplan"""
        # Arrange
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup)
        
        # Mock _read_scan_config to return None (missing config)
        self.handler._read_scan_config = Mock(return_value=None)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.handler.worker_pool.creation_queue.put.assert_not_called()


class TestDiscoveryClusterBackupHierarchy(unittest.TestCase):
    """Test cluster backup hierarchy with ownerReferences"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {'name': 'test-target', 'uid': 'target-uid-123'},
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {'name': 'test-secret', 'namespace': 'default'},
                    'skipCertVerification': True
                }
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {'storageType': 'objectstore'}
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        self.handler.scaninstance_map = {}
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_child_backupplan_with_owner_references_skipped(self, mock_path_join, mock_file):
        """Test child backupplan (ownerReferences → ClusterBackupPlan) is skipped"""
        # Arrange
        mock_path_join.return_value = '/triliodata/child-plan-1/backup-1/backup.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='child-plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('child-plan-1', backup)
        
        # Mock _read_scan_config to return None (child of cluster)
        self.handler._read_scan_config = Mock(return_value=None)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.handler.worker_pool.creation_queue.put.assert_not_called()
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_cluster_backup_structure_complete_scenario(self, mock_path_join, mock_file):
        """
        Test complete cluster backup scenario:
        - 1 cluster backup (should create ScanInstance)
        - 2 child backups (should skip, no ScanInstances)
        """
        # Arrange
        mock_path_join.return_value = '/triliodata/cluster-plan/cluster-backup-1/cluster-backup.json'
        
        self.handler.storage_state = StorageState()
        
        # Cluster backup
        cluster_backup = BackupObject(
            backup_uid='cluster-backup-1',
            json_path='cluster-plan/cluster-backup-1/cluster-backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.CLUSTER_BACKUP
        )
        self.handler.storage_state.add_backup('cluster-plan', cluster_backup)
        
        # Child backup 1
        child_backup1 = BackupObject(
            backup_uid='child-backup-1',
            json_path='child-plan-1/child-backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('child-plan-1', child_backup1)
        
        # Child backup 2
        child_backup2 = BackupObject(
            backup_uid='child-backup-2',
            json_path='child-plan-2/child-backup-2/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('child-plan-2', child_backup2)
        
        # Mock _read_scan_config: enabled for cluster, None for children
        def mock_read_config(backupplan_uid, backup):
            if backupplan_uid == 'cluster-plan':
                return ScanConfig(enabled=True, scan_old_backups=False)
            else:
                return None  # Child backupplan
        
        self.handler._read_scan_config = Mock(side_effect=mock_read_config)
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should only create ScanInstance for cluster backup
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_uid, 'cluster-backup-1')
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_mixed_cluster_and_regular_backups(self, mock_path_join, mock_file):
        """Test mixed scenario: cluster backup + regular backup + child backup"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan/backup.json'
        
        self.handler.storage_state = StorageState()
        
        # Cluster backup (enabled)
        cluster_backup = BackupObject(
            backup_uid='cluster-backup-1',
            json_path='cluster-plan/cluster-backup-1/cluster-backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.CLUSTER_BACKUP
        )
        self.handler.storage_state.add_backup('cluster-plan', cluster_backup)
        
        # Regular backup (enabled)
        regular_backup = BackupObject(
            backup_uid='regular-backup-1',
            json_path='regular-plan/regular-backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('regular-plan', regular_backup)
        
        # Child backup (should skip)
        child_backup = BackupObject(
            backup_uid='child-backup-1',
            json_path='child-plan/child-backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('child-plan', child_backup)
        
        # Mock _read_scan_config
        def mock_read_config(backupplan_uid, backup):
            if backupplan_uid in ['cluster-plan', 'regular-plan']:
                return ScanConfig(enabled=True, scan_old_backups=False)
            else:
                return None  # Child
        
        self.handler._read_scan_config = Mock(side_effect=mock_read_config)
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should create 2 ScanInstances (cluster + regular)
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 2)


class TestDiscoveryBackupOrdering(unittest.TestCase):
    """Test backup ordering and timestamp handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {'name': 'test-target', 'uid': 'target-uid-123'},
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {'name': 'test-secret', 'namespace': 'default'},
                    'skipCertVerification': True
                }
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {'storageType': 'objectstore'}
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        self.handler.scaninstance_map = {}
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_latest_backup_has_scaninstance_stops_discovery(self, mock_path_join, mock_file):
        """Test latest backup has ScanInstance → stops processing (discovery complete)"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        self.handler.storage_state = StorageState()
        latest_backup = BackupObject(
            backup_uid='backup-latest',
            json_path='plan-1/backup-latest/backup.json',
            last_updated_timestamp=datetime(2024, 1, 3),
            type=BackupType.BACKUP
        )
        older_backup = BackupObject(
            backup_uid='backup-old',
            json_path='plan-1/backup-old/backup.json',
            last_updated_timestamp=datetime(2024, 1, 1),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', latest_backup)
        self.handler.storage_state.add_backup('plan-1', older_backup)
        
        # Mock: latest has ScanInstance, older doesn't
        def mock_has_scaninstance(bp_uid, b_uid):
            return b_uid == 'backup-latest'
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(side_effect=mock_has_scaninstance)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should not queue any backups (latest already has ScanInstance)
        self.handler.worker_pool.creation_queue.put.assert_not_called()
    
    @patch('builtins.open')
    @patch('os.path.join')
    def test_latest_backup_missing_json_older_available(self, mock_path_join, mock_open_func):
        """Test latest backup JSON missing (in-progress), older is available → process older"""
        # Arrange
        def mock_open_side_effect(path, *args, **kwargs):
            if 'backup-latest' in path:
                raise FileNotFoundError()  # In-progress
            else:
                return mock_open(read_data='{"status": {"status": "Available"}}')()
        
        mock_open_func.side_effect = mock_open_side_effect
        mock_path_join.side_effect = lambda *args: '/'.join(args)
        
        self.handler.storage_state = StorageState()
        latest_backup = BackupObject(
            backup_uid='backup-latest',
            json_path='plan-1/backup-latest/backup.json',
            last_updated_timestamp=datetime(2024, 1, 3),
            type=BackupType.BACKUP
        )
        older_backup = BackupObject(
            backup_uid='backup-old',
            json_path='plan-1/backup-old/backup.json',
            last_updated_timestamp=datetime(2024, 1, 1),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', latest_backup)
        self.handler.storage_state.add_backup('plan-1', older_backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should queue older backup only
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_uid, 'backup-old')
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_multiple_available_backups_scan_old_backups_false(self, mock_path_join, mock_file):
        """Test multiple available backups, scanOldBackups=false → process backwards until ScanInstance found"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup.json'
        
        self.handler.storage_state = StorageState()
        backup1 = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime(2024, 1, 5),
            type=BackupType.BACKUP
        )
        backup2 = BackupObject(
            backup_uid='backup-2',
            json_path='plan-1/backup-2/backup.json',
            last_updated_timestamp=datetime(2024, 1, 4),
            type=BackupType.BACKUP
        )
        backup3 = BackupObject(
            backup_uid='backup-3',
            json_path='plan-1/backup-3/backup.json',
            last_updated_timestamp=datetime(2024, 1, 3),
            type=BackupType.BACKUP
        )
        backup4 = BackupObject(
            backup_uid='backup-4',
            json_path='plan-1/backup-4/backup.json',
            last_updated_timestamp=datetime(2024, 1, 2),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup1)
        self.handler.storage_state.add_backup('plan-1', backup2)
        self.handler.storage_state.add_backup('plan-1', backup3)
        self.handler.storage_state.add_backup('plan-1', backup4)
        
        # Mock: backup-3 has ScanInstance
        def mock_has_scaninstance(bp_uid, b_uid):
            return b_uid == 'backup-3'
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(side_effect=mock_has_scaninstance)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should queue backup-1 and backup-2, then stop at backup-3
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 2)
        queued_uids = [
            call[0][0].backup_uid 
            for call in self.handler.worker_pool.creation_queue.put.call_args_list
        ]
        self.assertIn('backup-1', queued_uids)
        self.assertIn('backup-2', queued_uids)


class TestDiscoveryBackupTypes(unittest.TestCase):
    """Test different backup types (backup, cluster-backup, snapshot, cluster-snapshot)"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {'name': 'test-target', 'uid': 'target-uid-123'},
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {'name': 'test-secret', 'namespace': 'default'},
                    'skipCertVerification': True
                }
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {'storageType': 'objectstore'}
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        self.handler.scaninstance_map = {}
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_regular_backup_type(self, mock_path_join, mock_file):
        """Test regular backup (backup.json) is processed correctly"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_type, BackupType.BACKUP)
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_cluster_backup_type(self, mock_path_join, mock_file):
        """Test cluster backup (cluster-backup.json) is processed correctly"""
        # Arrange
        mock_path_join.return_value = '/triliodata/cluster-plan/backup-1/cluster-backup.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='cluster-plan/backup-1/cluster-backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.CLUSTER_BACKUP
        )
        self.handler.storage_state.add_backup('cluster-plan', backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_type, BackupType.CLUSTER_BACKUP)
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_snapshot_type(self, mock_path_join, mock_file):
        """Test snapshot (snapshot.json) is processed correctly"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/snapshot.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/snapshot.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.SNAPSHOT
        )
        self.handler.storage_state.add_backup('plan-1', backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_type, BackupType.SNAPSHOT)
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_cluster_snapshot_type(self, mock_path_join, mock_file):
        """Test cluster snapshot (cluster-snapshot.json) is processed correctly"""
        # Arrange
        mock_path_join.return_value = '/triliodata/cluster-plan/backup-1/cluster-snapshot.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='cluster-plan/backup-1/cluster-snapshot.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.CLUSTER_SNAPSHOT
        )
        self.handler.storage_state.add_backup('cluster-plan', backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_type, BackupType.CLUSTER_SNAPSHOT)


class TestDiscoveryQueueIntegration(unittest.TestCase):
    """Test queue and worker integration"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {'name': 'test-target', 'uid': 'target-uid-123'},
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {'name': 'test-secret', 'namespace': 'default'},
                    'skipCertVerification': True
                }
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {'storageType': 'objectstore'}
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.scaninstance_map = {}
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_single_backup_to_queue(self, mock_path_join, mock_file):
        """Test single backup adds 1 CreationMessage to queue"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup-1/backup.json'
        
        self.handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=False))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Mock get_stats to return non-empty queue
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 1, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.handler.worker_pool.creation_queue.put.assert_called_once()
        self.handler.worker_pool.wait_for_creation_completion.assert_called_once()
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_multiple_backups_to_queue_scan_old_backups_true(self, mock_path_join, mock_file):
        """Test multiple backups add multiple CreationMessages (scanOldBackups=true)"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup.json'
        
        self.handler.storage_state = StorageState()
        for i in range(5):
            backup = BackupObject(
                backup_uid=f'backup-{i}',
                json_path=f'plan-1/backup-{i}/backup.json',
                last_updated_timestamp=datetime(2024, 1, i+1),
                type=BackupType.BACKUP
            )
            self.handler.storage_state.add_backup('plan-1', backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=True))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Mock get_stats to return non-empty queue
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 5, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 5)
        self.handler.worker_pool.wait_for_creation_completion.assert_called_once()
    
    def test_creation_queue_empty_no_waiting(self):
        """Test creation queue empty → no waiting"""
        # Arrange
        self.handler.storage_state = StorageState()
        
        # Mock get_stats to return empty queue
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        # Act
        self.handler.perform_discovery()
        
        # Assert
        self.handler.worker_pool.wait_for_creation_completion.assert_not_called()


class TestDiscoveryEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {'name': 'test-target', 'uid': 'target-uid-123'},
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {'name': 'test-secret', 'namespace': 'default'},
                    'skipCertVerification': True
                }
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {'storageType': 'objectstore'}
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.creation_queue = Mock()
        self.handler.worker_pool.creation_workers = []
        self.handler.worker_pool.start_creation_workers = Mock()
        self.handler.worker_pool.wait_for_creation_completion = Mock()
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 0, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        self.handler.scaninstance_map = {}
    
    def test_empty_backupplan_no_backups(self):
        """Test empty backupplan (no backups in storage) logs warning and continues"""
        # Arrange
        self.handler.storage_state = StorageState()
        self.handler.storage_state.backupplans['empty-plan'] = []
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should complete without errors
        self.handler.worker_pool.creation_queue.put.assert_not_called()
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_very_large_number_of_backups(self, mock_path_join, mock_file):
        """Test backupplan with 100+ backups, scanOldBackups=true processes all"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup.json'
        
        self.handler.storage_state = StorageState()
        num_backups = 150
        for i in range(num_backups):
            backup = BackupObject(
                backup_uid=f'backup-{i}',
                json_path=f'plan-1/backup-{i}/backup.json',
                last_updated_timestamp=datetime(2024, 1, 1) + timedelta(minutes=i),
                type=BackupType.BACKUP
            )
            self.handler.storage_state.add_backup('plan-1', backup)
        
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=True))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Mock get_stats
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': num_backups, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should queue all 150 backups
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, num_backups)
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_multiple_backupplans_some_with_errors(self, mock_path_join, mock_file):
        """Test multiple backupplans, one throws error → continues processing others"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan/backup.json'
        
        self.handler.storage_state = StorageState()
        
        # Plan 1: will throw error
        backup1 = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup1)
        
        # Plan 2: normal
        backup2 = BackupObject(
            backup_uid='backup-2',
            json_path='plan-2/backup-2/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-2', backup2)
        
        # Mock _read_scan_config to throw error for plan-1, return config for plan-2
        def mock_read_config(bp_uid, backup):
            if bp_uid == 'plan-1':
                raise Exception("Config read error")
            else:
                return ScanConfig(enabled=True, scan_old_backups=False)
        
        self.handler._read_scan_config = Mock(side_effect=mock_read_config)
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Mock get_stats
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 1, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should queue backup-2 despite plan-1 error
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 1)
        creation_msg = self.handler.worker_pool.creation_queue.put.call_args[0][0]
        self.assertEqual(creation_msg.backup_uid, 'backup-2')
    
    @patch('builtins.open', new_callable=mock_open, read_data='{"status": {"status": "Available"}}')
    @patch('os.path.join')
    def test_storage_state_refresh_adds_new_backup(self, mock_path_join, mock_file):
        """Test storage state refresh detects new backup added between phases"""
        # Arrange
        mock_path_join.return_value = '/triliodata/plan-1/backup.json'
        
        # Initial state: 2 backups
        self.handler.storage_state = StorageState()
        backup1 = BackupObject(
            backup_uid='backup-1',
            json_path='plan-1/backup-1/backup.json',
            last_updated_timestamp=datetime(2024, 1, 1),
            type=BackupType.BACKUP
        )
        backup2 = BackupObject(
            backup_uid='backup-2',
            json_path='plan-1/backup-2/backup.json',
            last_updated_timestamp=datetime(2024, 1, 2),
            type=BackupType.BACKUP
        )
        self.handler.storage_state.add_backup('plan-1', backup1)
        self.handler.storage_state.add_backup('plan-1', backup2)
        
        # Mock refresh to add new backup
        def mock_refresh():
            backup3 = BackupObject(
                backup_uid='backup-3',
                json_path='plan-1/backup-3/backup.json',
                last_updated_timestamp=datetime(2024, 1, 3),
                type=BackupType.BACKUP
            )
            self.handler.storage_state.add_backup('plan-1', backup3)
        
        self.handler.refresh_storage_state = mock_refresh
        self.handler._read_scan_config = Mock(return_value=ScanConfig(enabled=True, scan_old_backups=True))
        self.handler._has_scaninstance = Mock(return_value=False)
        
        # Mock get_stats
        self.handler.worker_pool.get_stats = Mock(return_value={
            'creation': {'queue_size': 3, 'processed': 0, 'errors': 0},
            'cleanup': {'queue_size': 0, 'processed': 0, 'errors': 0}
        })
        
        # Act
        self.handler.perform_discovery()
        
        # Assert - should queue all 3 backups (including newly added)
        self.assertEqual(self.handler.worker_pool.creation_queue.put.call_count, 3)


if __name__ == '__main__':
    unittest.main()
