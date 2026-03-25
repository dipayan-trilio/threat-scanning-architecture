#!/usr/bin/env python3
"""
Unit tests for targetPoller cleanup functionality.

Tests the cleanup phase logic using mocks to avoid external dependencies.
Focuses on:
- ScanInstance listing and filtering
- Stale detection algorithm
- Queue message creation
- Map building logic
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from targetPoller.handlers.base_handler import BaseTargetHandler
from targetPoller.models.storage_state import (
    StorageState, BackupObject, BackupType,
    CleanupMessage
)
from targetPoller.workers.queue_workers import WorkerPool


class MockHandler(BaseTargetHandler):
    """Concrete implementation of BaseTargetHandler for testing"""
    
    def populate_storage_state(self):
        return StorageState()
    
    def refresh_storage_state(self):
        pass
    
    def _read_scan_config(self, backupplan_uid, backup):
        return None


class TestCleanupBasicLogic(unittest.TestCase):
    """Test basic cleanup logic and control flow"""
    
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
                'type': 'ObjectStore'
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
        self.handler.worker_pool.cleanup_queue = Mock()
        self.handler.worker_pool.cleanup_workers = []  # Empty list means workers not started
        self.handler.worker_pool.start_cleanup_workers = Mock()
        self.handler.worker_pool.wait_for_cleanup_completion = Mock()
    
    def test_cleanup_with_no_scaninstances(self):
        """Test cleanup when no ScanInstances exist"""
        # Arrange
        self.mock_k8s_client.list_scan_instances.return_value = []
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.mock_k8s_client.list_scan_instances.assert_called_once_with(
            label_selector='trilio.io/backup-target=test-target'
        )
        self.handler.worker_pool.cleanup_queue.put.assert_not_called()
        self.handler.worker_pool.wait_for_cleanup_completion.assert_not_called()
    
    def test_cleanup_with_all_valid_scaninstances(self):
        """Test cleanup when all ScanInstances are valid (backups exist)"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Storage state has the backup
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-456',
                json_path='plan-123/backup-456/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.cleanup_queue.put.assert_not_called()
        self.handler.worker_pool.wait_for_cleanup_completion.assert_not_called()
    
    def test_cleanup_with_stale_backup(self):
        """Test cleanup when backup is deleted (not in storage state)"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Storage state has backupplan but NOT the backup
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-999',  # Different backup
                json_path='plan-123/backup-999/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.cleanup_queue.put.assert_called_once()
        call_args = self.handler.worker_pool.cleanup_queue.put.call_args[0][0]
        self.assertIsInstance(call_args, CleanupMessage)
        self.assertEqual(call_args.scaninstance_name, 'scaninstance-1')
        self.assertEqual(call_args.backupplan_uid, 'plan-123')
        self.assertEqual(call_args.backup_uid, 'backup-456')
        self.handler.worker_pool.wait_for_cleanup_completion.assert_called_once()
    
    def test_cleanup_with_stale_backupplan(self):
        """Test cleanup when entire backupplan is deleted"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'scaninstance-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-789'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Storage state is empty (backupplan deleted)
        self.handler.storage_state = StorageState()
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.cleanup_queue.put.call_count, 2)
        self.handler.worker_pool.wait_for_cleanup_completion.assert_called_once()
    
    def test_cleanup_skips_scaninstances_without_labels(self):
        """Test cleanup skips ScanInstances without backupplan/backup labels"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        # Missing backupplan and backup labels (prescan not done)
                    }
                }
            },
            {
                'metadata': {
                    'name': 'scaninstance-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        # Missing backup label
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.cleanup_queue.put.assert_not_called()
        self.assertEqual(len(self.handler.scaninstance_map), 0)


class TestCleanupMapBuilding(unittest.TestCase):
    """Test ScanInstance map building logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {
                'name': 'test-target',
                'uid': 'target-uid-123'
            },
            'spec': {
                'type': 'ObjectStore'
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {
                'storageType': 'objectstore'
            }
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.cleanup_queue = Mock()
        self.handler.worker_pool.cleanup_workers = []  # Empty list means workers not started
        self.handler.worker_pool.start_cleanup_workers = Mock()
        self.handler.worker_pool.wait_for_cleanup_completion = Mock()
    
    def test_map_single_backupplan_single_backup(self):
        """Test map building with single backupplan and backup"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Add to storage state to prevent cleanup
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-456',
                json_path='plan-123/backup-456/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertIn('plan-123', self.handler.scaninstance_map)
        self.assertIn('backup-456', self.handler.scaninstance_map['plan-123'])
        self.assertEqual(
            self.handler.scaninstance_map['plan-123']['backup-456'],
            ['scaninstance-1']
        )
    
    def test_map_multiple_scaninstances_same_backup(self):
        """Test map building with multiple ScanInstances for same backup"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'scaninstance-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-456',
                json_path='plan-123/backup-456/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(
            len(self.handler.scaninstance_map['plan-123']['backup-456']),
            2
        )
        self.assertIn('scaninstance-1', self.handler.scaninstance_map['plan-123']['backup-456'])
        self.assertIn('scaninstance-2', self.handler.scaninstance_map['plan-123']['backup-456'])
    
    def test_map_multiple_backupplans(self):
        """Test map building with multiple backupplans"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'scaninstance-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-789',
                        'trilio.io/backup': 'backup-999'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Add both backupplans to storage state
        for plan_uid, backup_uid in [('plan-123', 'backup-456'), ('plan-789', 'backup-999')]:
            self.handler.storage_state.add_backup(
                plan_uid,
                BackupObject(
                    backup_uid=backup_uid,
                    json_path=f'{plan_uid}/{backup_uid}/backup.json',
                    last_updated_timestamp=datetime.now(),
                    type=BackupType.BACKUP
                )
            )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(len(self.handler.scaninstance_map), 2)
        self.assertIn('plan-123', self.handler.scaninstance_map)
        self.assertIn('plan-789', self.handler.scaninstance_map)
    
    def test_map_complex_hierarchy(self):
        """Test map building with complex hierarchy: multiple plans, backups, scaninstances"""
        # Arrange
        scaninstances = [
            # Plan 1 - Backup 1 - SI 1
            {
                'metadata': {
                    'name': 'si-p1-b1-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-1',
                        'trilio.io/backup': 'backup-1'
                    }
                }
            },
            # Plan 1 - Backup 1 - SI 2
            {
                'metadata': {
                    'name': 'si-p1-b1-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-1',
                        'trilio.io/backup': 'backup-1'
                    }
                }
            },
            # Plan 1 - Backup 2 - SI 1
            {
                'metadata': {
                    'name': 'si-p1-b2-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-1',
                        'trilio.io/backup': 'backup-2'
                    }
                }
            },
            # Plan 2 - Backup 3 - SI 1
            {
                'metadata': {
                    'name': 'si-p2-b3-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-2',
                        'trilio.io/backup': 'backup-3'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Add all backups to storage state
        for plan_uid, backup_uid in [
            ('plan-1', 'backup-1'),
            ('plan-1', 'backup-2'),
            ('plan-2', 'backup-3')
        ]:
            self.handler.storage_state.add_backup(
                plan_uid,
                BackupObject(
                    backup_uid=backup_uid,
                    json_path=f'{plan_uid}/{backup_uid}/backup.json',
                    last_updated_timestamp=datetime.now(),
                    type=BackupType.BACKUP
                )
            )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(len(self.handler.scaninstance_map), 2)  # 2 backupplans
        self.assertEqual(len(self.handler.scaninstance_map['plan-1']), 2)  # 2 backups in plan-1
        self.assertEqual(len(self.handler.scaninstance_map['plan-2']), 1)  # 1 backup in plan-2
        self.assertEqual(len(self.handler.scaninstance_map['plan-1']['backup-1']), 2)  # 2 SIs
        self.assertEqual(len(self.handler.scaninstance_map['plan-1']['backup-2']), 1)  # 1 SI
        self.assertEqual(len(self.handler.scaninstance_map['plan-2']['backup-3']), 1)  # 1 SI


class TestCleanupStaleDetection(unittest.TestCase):
    """Test stale ScanInstance detection algorithm"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {
                'name': 'test-target',
                'uid': 'target-uid-123'
            },
            'spec': {
                'type': 'ObjectStore'
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {
                'storageType': 'objectstore'
            }
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.cleanup_queue = Mock()
        self.handler.worker_pool.cleanup_workers = []  # Empty list means workers not started
        self.handler.worker_pool.start_cleanup_workers = Mock()
        self.handler.worker_pool.wait_for_cleanup_completion = Mock()
    
    def test_detect_stale_when_backup_deleted(self):
        """Test detection when specific backup is deleted but plan exists"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'scaninstance-stale',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-deleted'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'scaninstance-valid',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-exists'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Only add one backup to storage state
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-exists',
                json_path='plan-123/backup-exists/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.cleanup_queue.put.assert_called_once()
        call_args = self.handler.worker_pool.cleanup_queue.put.call_args[0][0]
        self.assertEqual(call_args.scaninstance_name, 'scaninstance-stale')
        self.assertEqual(call_args.backup_uid, 'backup-deleted')
    
    def test_detect_stale_when_backupplan_deleted(self):
        """Test detection when entire backupplan is deleted"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-deleted',
                        'trilio.io/backup': 'backup-1'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'si-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-deleted',
                        'trilio.io/backup': 'backup-2'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'si-3',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-exists',
                        'trilio.io/backup': 'backup-3'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Only add one backupplan
        self.handler.storage_state.add_backup(
            'plan-exists',
            BackupObject(
                backup_uid='backup-3',
                json_path='plan-exists/backup-3/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert - should queue 2 ScanInstances from deleted plan
        self.assertEqual(self.handler.worker_pool.cleanup_queue.put.call_count, 2)
        
        # Verify the deleted plan is removed from map
        self.assertNotIn('plan-deleted', self.handler.scaninstance_map)
        self.assertIn('plan-exists', self.handler.scaninstance_map)
    
    def test_mixed_scenario_some_stale_some_valid(self):
        """Test mixed scenario with both stale and valid ScanInstances"""
        # Arrange
        scaninstances = [
            # Valid
            {
                'metadata': {
                    'name': 'si-valid-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-1',
                        'trilio.io/backup': 'backup-1'
                    }
                }
            },
            # Stale - backup deleted
            {
                'metadata': {
                    'name': 'si-stale-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-1',
                        'trilio.io/backup': 'backup-deleted'
                    }
                }
            },
            # Stale - plan deleted
            {
                'metadata': {
                    'name': 'si-stale-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-deleted',
                        'trilio.io/backup': 'backup-2'
                    }
                }
            },
            # Valid
            {
                'metadata': {
                    'name': 'si-valid-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-2',
                        'trilio.io/backup': 'backup-3'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Add valid backups to storage state
        for plan_uid, backup_uid in [('plan-1', 'backup-1'), ('plan-2', 'backup-3')]:
            self.handler.storage_state.add_backup(
                plan_uid,
                BackupObject(
                    backup_uid=backup_uid,
                    json_path=f'{plan_uid}/{backup_uid}/backup.json',
                    last_updated_timestamp=datetime.now(),
                    type=BackupType.BACKUP
                )
            )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert - should queue exactly 2 stale ScanInstances
        self.assertEqual(self.handler.worker_pool.cleanup_queue.put.call_count, 2)
        
        # Verify correct ones were queued
        queued_names = [
            call[0][0].scaninstance_name 
            for call in self.handler.worker_pool.cleanup_queue.put.call_args_list
        ]
        self.assertIn('si-stale-1', queued_names)
        self.assertIn('si-stale-2', queued_names)
        self.assertNotIn('si-valid-1', queued_names)
        self.assertNotIn('si-valid-2', queued_names)


class TestCleanupQueueMessages(unittest.TestCase):
    """Test cleanup queue message creation and content"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {
                'name': 'test-target',
                'uid': 'target-uid-123'
            },
            'spec': {
                'type': 'ObjectStore'
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {
                'storageType': 'objectstore'
            }
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.cleanup_queue = Mock()
        self.handler.worker_pool.cleanup_workers = []  # Empty list means workers not started
        self.handler.worker_pool.start_cleanup_workers = Mock()
        self.handler.worker_pool.wait_for_cleanup_completion = Mock()
    
    def test_cleanup_message_structure(self):
        """Test CleanupMessage structure and content"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'test-scaninstance',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-abc',
                        'trilio.io/backup': 'backup-xyz'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Empty storage state to trigger cleanup
        self.handler.storage_state = StorageState()
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.cleanup_queue.put.assert_called_once()
        message = self.handler.worker_pool.cleanup_queue.put.call_args[0][0]
        
        self.assertIsInstance(message, CleanupMessage)
        self.assertEqual(message.scaninstance_name, 'test-scaninstance')
        self.assertEqual(message.backupplan_uid, 'plan-abc')
        self.assertEqual(message.backup_uid, 'backup-xyz')
    
    def test_multiple_cleanup_messages_for_same_plan(self):
        """Test multiple CleanupMessages when multiple backups deleted"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-1'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'si-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-2'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'si-3',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-3'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Empty storage state - all should be cleaned up
        self.handler.storage_state = StorageState()
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.cleanup_queue.put.call_count, 3)
        
        # Verify all messages have correct structure
        for call_obj in self.handler.worker_pool.cleanup_queue.put.call_args_list:
            message = call_obj[0][0]
            self.assertIsInstance(message, CleanupMessage)
            self.assertEqual(message.backupplan_uid, 'plan-123')
            self.assertIn(message.scaninstance_name, ['si-1', 'si-2', 'si-3'])


class TestCleanupCompletion(unittest.TestCase):
    """Test cleanup completion and waiting logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {
                'name': 'test-target',
                'uid': 'target-uid-123'
            },
            'spec': {
                'type': 'ObjectStore'
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {
                'storageType': 'objectstore'
            }
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.cleanup_queue = Mock()
        self.handler.worker_pool.cleanup_workers = []  # Empty list means workers not started
        self.handler.worker_pool.start_cleanup_workers = Mock()
        self.handler.worker_pool.wait_for_cleanup_completion = Mock()
    
    def test_wait_called_when_stale_scaninstances_exist(self):
        """Test wait_for_cleanup_completion is called when items queued"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-stale',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        self.handler.storage_state = StorageState()  # Empty - trigger cleanup
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.wait_for_cleanup_completion.assert_called_once()
    
    def test_wait_not_called_when_no_stale_scaninstances(self):
        """Test wait_for_cleanup_completion is NOT called when nothing to clean"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-valid',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Add backup to storage state
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-456',
                json_path='plan-123/backup-456/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.wait_for_cleanup_completion.assert_not_called()


class TestCleanupEdgeCases(unittest.TestCase):
    """Test edge cases and error handling in cleanup"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.mock_logger = Mock()
        
        self.target_cr = {
            'metadata': {
                'name': 'test-target',
                'uid': 'target-uid-123'
            },
            'spec': {
                'type': 'ObjectStore'
            }
        }
        
        with patch('targetPoller.handlers.base_handler.triliodata_crd_parser') as mock_parser:
            mock_parser.parse_cr_response.return_value = {
                'storageType': 'objectstore'
            }
            self.handler = MockHandler(
                target_cr=self.target_cr,
                k8s_client=self.mock_k8s_client,
                logger_instance=self.mock_logger
            )
        
        self.handler.worker_pool = Mock(spec=WorkerPool)
        self.handler.worker_pool.cleanup_queue = Mock()
        self.handler.worker_pool.cleanup_workers = []  # Empty list means workers not started
        self.handler.worker_pool.start_cleanup_workers = Mock()
        self.handler.worker_pool.wait_for_cleanup_completion = Mock()
    
    def test_cleanup_with_malformed_scaninstance(self):
        """Test cleanup handles malformed ScanInstance gracefully"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-malformed',
                    # Missing labels entirely
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Act & Assert - should not raise exception
        self.handler.perform_cleanup()
        
        # Should skip malformed ScanInstance
        self.handler.worker_pool.cleanup_queue.put.assert_not_called()
    
    def test_cleanup_with_empty_label_values(self):
        """Test cleanup handles empty label values"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-empty-labels',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': '',  # Empty
                        'trilio.io/backup': ''  # Empty
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert - should skip due to empty labels
        self.handler.worker_pool.cleanup_queue.put.assert_not_called()
        self.assertEqual(len(self.handler.scaninstance_map), 0)
    
    def test_cleanup_with_large_number_of_scaninstances(self):
        """Test cleanup can handle large number of ScanInstances"""
        # Arrange - create 1000 stale ScanInstances
        scaninstances = []
        for i in range(1000):
            scaninstances.append({
                'metadata': {
                    'name': f'si-{i}',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': f'plan-{i % 10}',  # 10 different plans
                        'trilio.io/backup': f'backup-{i}'
                    }
                }
            })
        
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        self.handler.storage_state = StorageState()  # Empty - all stale
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(self.handler.worker_pool.cleanup_queue.put.call_count, 1000)
        self.handler.worker_pool.wait_for_cleanup_completion.assert_called_once()
    
    def test_cleanup_label_selector_correct(self):
        """Test cleanup uses correct label selector"""
        # Arrange
        self.mock_k8s_client.list_scan_instances.return_value = []
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.mock_k8s_client.list_scan_instances.assert_called_once_with(
            label_selector='trilio.io/backup-target=test-target'
        )


if __name__ == '__main__':
    unittest.main()
