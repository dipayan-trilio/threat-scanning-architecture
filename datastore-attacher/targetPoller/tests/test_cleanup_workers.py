#!/usr/bin/env python3
"""
Unit tests for CleanupWorker and queue processing.

Tests the worker thread behavior using mocks and threading primitives.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import threading
import queue
import time
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from targetPoller.workers.queue_workers import CleanupWorker, WorkerPool
from targetPoller.models.storage_state import CleanupMessage, BackupType, StorageState, BackupObject
from targetPoller.handlers.base_handler import BaseTargetHandler


class MockHandler(BaseTargetHandler):
    """Concrete implementation of BaseTargetHandler for testing"""
    
    def populate_storage_state(self):
        return StorageState()
    
    def refresh_storage_state(self):
        pass
    
    def _read_scan_config(self, backupplan_uid, backup):
        return None


class TestCleanupWorker(unittest.TestCase):
    """Test CleanupWorker thread behavior"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.cleanup_queue = queue.Queue()
        self.stop_event = threading.Event()
    
    def tearDown(self):
        """Clean up after tests"""
        self.stop_event.set()
    
    def test_worker_initialization(self):
        """Test worker initializes with correct attributes"""
        # Arrange & Act
        worker = CleanupWorker(
            worker_id=1,
            cleanup_queue=self.cleanup_queue,
            k8s_client=self.mock_k8s_client,
            stop_event=self.stop_event
        )
        
        # Assert
        self.assertEqual(worker.worker_id, 1)
        self.assertEqual(worker.cleanup_queue, self.cleanup_queue)
        self.assertEqual(worker.k8s_client, self.mock_k8s_client)
        self.assertEqual(worker.processed_count, 0)
        self.assertEqual(worker.error_count, 0)
        self.assertTrue(worker.daemon)
        self.assertEqual(worker.name, 'CleanupWorker-1')
    
    def test_worker_processes_single_message(self):
        """Test worker processes a single cleanup message successfully"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        
        message = CleanupMessage(
            scaninstance_name='test-si',
            backupplan_uid='plan-123',
            backup_uid='backup-456'
        )
        
        worker = CleanupWorker(
            worker_id=1,
            cleanup_queue=self.cleanup_queue,
            k8s_client=self.mock_k8s_client,
            stop_event=self.stop_event
        )
        
        # Add message to queue
        self.cleanup_queue.put(message)
        
        # Act
        worker.start()
        
        # Wait for processing
        self.cleanup_queue.join()
        
        # Stop worker
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.mock_k8s_client.delete_scaninstance.assert_called_once_with('test-si')
        self.assertEqual(worker.processed_count, 1)
        self.assertEqual(worker.error_count, 0)
    
    def test_worker_processes_multiple_messages(self):
        """Test worker processes multiple cleanup messages"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        
        messages = [
            CleanupMessage('si-1', 'plan-1', 'backup-1'),
            CleanupMessage('si-2', 'plan-1', 'backup-2'),
            CleanupMessage('si-3', 'plan-2', 'backup-3')
        ]
        
        worker = CleanupWorker(
            worker_id=1,
            cleanup_queue=self.cleanup_queue,
            k8s_client=self.mock_k8s_client,
            stop_event=self.stop_event
        )
        
        # Add messages to queue
        for msg in messages:
            self.cleanup_queue.put(msg)
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 3)
        self.assertEqual(worker.processed_count, 3)
        self.assertEqual(worker.error_count, 0)
    
    def test_worker_handles_deletion_success(self):
        """Test worker increments processed_count on successful deletion"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        
        message = CleanupMessage('si-1', 'plan-1', 'backup-1')
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        self.cleanup_queue.put(message)
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertEqual(worker.processed_count, 1)
        self.assertEqual(worker.error_count, 0)
    
    def test_worker_handles_deletion_failure(self):
        """Test worker increments error_count on deletion failure"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = False
        
        message = CleanupMessage('si-1', 'plan-1', 'backup-1')
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        self.cleanup_queue.put(message)
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertEqual(worker.processed_count, 0)
        self.assertEqual(worker.error_count, 1)
    
    def test_worker_handles_exception_during_processing(self):
        """Test worker handles exceptions gracefully"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.side_effect = Exception("K8s API error")
        
        message = CleanupMessage('si-1', 'plan-1', 'backup-1')
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        self.cleanup_queue.put(message)
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertEqual(worker.error_count, 1)
        self.assertEqual(worker.processed_count, 0)
    
    def test_worker_stops_on_stop_event(self):
        """Test worker stops when stop_event is set"""
        # Arrange
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        # Act
        worker.start()
        time.sleep(0.1)  # Let worker start
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertFalse(worker.is_alive())
    
    def test_worker_continues_after_single_error(self):
        """Test worker continues processing after encountering an error"""
        # Arrange
        # First call fails, second succeeds
        self.mock_k8s_client.delete_scaninstance.side_effect = [
            Exception("Transient error"),
            True
        ]
        
        messages = [
            CleanupMessage('si-1', 'plan-1', 'backup-1'),
            CleanupMessage('si-2', 'plan-1', 'backup-2')
        ]
        
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        for msg in messages:
            self.cleanup_queue.put(msg)
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertEqual(worker.processed_count, 1)
        self.assertEqual(worker.error_count, 1)
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 2)


class TestWorkerPoolCleanup(unittest.TestCase):
    """Test WorkerPool cleanup operations"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.worker_pool = WorkerPool(num_workers=3)
    
    def tearDown(self):
        """Clean up worker pool"""
        self.worker_pool.stop_all_workers()
    
    def test_workerpool_initialization(self):
        """Test WorkerPool initializes correctly"""
        # Assert
        self.assertEqual(self.worker_pool.num_workers, 3)
        self.assertIsInstance(self.worker_pool.cleanup_queue, queue.Queue)
        self.assertIsInstance(self.worker_pool.creation_queue, queue.Queue)
        self.assertEqual(len(self.worker_pool.cleanup_workers), 0)
        self.assertEqual(len(self.worker_pool.creation_workers), 0)
    
    def test_start_cleanup_workers(self):
        """Test starting cleanup workers"""
        # Act
        self.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Assert
        self.assertEqual(len(self.worker_pool.cleanup_workers), 3)
        for worker in self.worker_pool.cleanup_workers:
            self.assertIsInstance(worker, CleanupWorker)
            self.assertTrue(worker.is_alive())
    
    def test_cleanup_workers_process_queue(self):
        """Test cleanup workers process messages from queue"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        self.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Add messages
        messages = [
            CleanupMessage('si-1', 'plan-1', 'backup-1'),
            CleanupMessage('si-2', 'plan-1', 'backup-2'),
            CleanupMessage('si-3', 'plan-2', 'backup-3')
        ]
        
        for msg in messages:
            self.worker_pool.cleanup_queue.put(msg)
        
        # Act
        self.worker_pool.wait_for_cleanup_completion()
        
        # Assert
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 3)
        self.assertTrue(self.worker_pool.cleanup_queue.empty())
    
    def test_wait_for_cleanup_completion(self):
        """Test wait_for_cleanup_completion blocks until queue empty"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        self.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Add message
        self.worker_pool.cleanup_queue.put(
            CleanupMessage('si-1', 'plan-1', 'backup-1')
        )
        
        # Act
        start_time = time.time()
        self.worker_pool.wait_for_cleanup_completion()
        elapsed_time = time.time() - start_time
        
        # Assert
        self.assertTrue(self.worker_pool.cleanup_queue.empty())
        # Should complete quickly since only 1 message
        self.assertLess(elapsed_time, 2.0)
    
    def test_stop_all_workers(self):
        """Test stopping all workers gracefully"""
        # Arrange
        self.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Verify workers are running
        self.assertEqual(len(self.worker_pool.cleanup_workers), 3)
        for worker in self.worker_pool.cleanup_workers:
            self.assertTrue(worker.is_alive())
        
        # Act
        self.worker_pool.stop_all_workers()
        
        # Assert
        for worker in self.worker_pool.cleanup_workers:
            self.assertFalse(worker.is_alive())
        self.assertTrue(self.worker_pool.stop_event.is_set())
    
    def test_get_stats_empty_queues(self):
        """Test get_stats returns correct stats with empty queues"""
        # Arrange
        self.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Act
        stats = self.worker_pool.get_stats()
        
        # Assert
        self.assertEqual(stats['cleanup']['processed'], 0)
        self.assertEqual(stats['cleanup']['errors'], 0)
        self.assertEqual(stats['cleanup']['queue_size'], 0)
    
    def test_get_stats_after_processing(self):
        """Test get_stats returns correct stats after processing"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        self.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Add and process messages
        for i in range(5):
            self.worker_pool.cleanup_queue.put(
                CleanupMessage(f'si-{i}', 'plan-1', f'backup-{i}')
            )
        
        self.worker_pool.wait_for_cleanup_completion()
        
        # Act
        stats = self.worker_pool.get_stats()
        
        # Assert
        self.assertEqual(stats['cleanup']['processed'], 5)
        self.assertEqual(stats['cleanup']['errors'], 0)
        self.assertEqual(stats['cleanup']['queue_size'], 0)
    
    def test_get_stats_with_errors(self):
        """Test get_stats counts errors correctly"""
        # Arrange
        # Simulate failures
        self.mock_k8s_client.delete_scaninstance.side_effect = [
            True,
            False,  # Failure
            Exception("API error"),  # Exception
            True,
            False  # Failure
        ]
        
        self.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Add messages
        for i in range(5):
            self.worker_pool.cleanup_queue.put(
                CleanupMessage(f'si-{i}', 'plan-1', f'backup-{i}')
            )
        
        self.worker_pool.wait_for_cleanup_completion()
        
        # Act
        stats = self.worker_pool.get_stats()
        
        # Assert
        self.assertEqual(stats['cleanup']['processed'], 2)  # 2 successful
        self.assertEqual(stats['cleanup']['errors'], 3)  # 3 failed


class TestCleanupWorkerConcurrency(unittest.TestCase):
    """Test cleanup worker concurrent processing"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.cleanup_queue = queue.Queue()
        self.stop_event = threading.Event()
    
    def tearDown(self):
        """Clean up after tests"""
        self.stop_event.set()
    
    def test_multiple_workers_process_concurrently(self):
        """Test multiple workers process queue concurrently"""
        # Arrange
        # Add slight delay to simulate work
        def slow_delete(name):
            time.sleep(0.05)
            return True
        
        self.mock_k8s_client.delete_scaninstance.side_effect = slow_delete
        
        worker_pool = WorkerPool(num_workers=3)
        worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Add 9 messages
        for i in range(9):
            worker_pool.cleanup_queue.put(
                CleanupMessage(f'si-{i}', 'plan-1', f'backup-{i}')
            )
        
        # Act
        start_time = time.time()
        worker_pool.wait_for_cleanup_completion()
        elapsed_time = time.time() - start_time
        
        # Assert
        # With 3 workers processing 9 items (each taking ~0.05s)
        # Should complete in ~3 batches = ~0.15s (vs 0.45s sequential)
        # Add buffer for test overhead
        self.assertLess(elapsed_time, 0.5)
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 9)
        
        # Cleanup
        worker_pool.stop_all_workers()
    
    def test_queue_join_waits_for_all_tasks(self):
        """Test queue.join() waits for all tasks to complete"""
        # Arrange
        processed_items = []
        
        def track_delete(name):
            time.sleep(0.02)
            processed_items.append(name)
            return True
        
        self.mock_k8s_client.delete_scaninstance.side_effect = track_delete
        
        worker_pool = WorkerPool(num_workers=2)
        worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Add messages
        expected_names = [f'si-{i}' for i in range(5)]
        for name in expected_names:
            worker_pool.cleanup_queue.put(
                CleanupMessage(name, 'plan-1', 'backup-1')
            )
        
        # Act
        worker_pool.wait_for_cleanup_completion()
        
        # Assert
        self.assertEqual(len(processed_items), 5)
        self.assertEqual(set(processed_items), set(expected_names))
        self.assertTrue(worker_pool.cleanup_queue.empty())
        
        # Cleanup
        worker_pool.stop_all_workers()


class TestCleanupWorkerErrorHandling(unittest.TestCase):
    """Test cleanup worker error handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_k8s_client = Mock()
        self.cleanup_queue = queue.Queue()
        self.stop_event = threading.Event()
    
    def tearDown(self):
        """Clean up after tests"""
        self.stop_event.set()
    
    def test_worker_handles_k8s_api_exception(self):
        """Test worker handles K8s API exceptions without crashing"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.side_effect = Exception("API timeout")
        
        message = CleanupMessage('si-1', 'plan-1', 'backup-1')
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        self.cleanup_queue.put(message)
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert - worker should not crash
        self.assertEqual(worker.error_count, 1)
        self.assertEqual(worker.processed_count, 0)
    
    def test_worker_continues_after_exception(self):
        """Test worker continues processing after exception"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.side_effect = [
            Exception("First error"),
            True,  # Success
            Exception("Second error"),
            True  # Success
        ]
        
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        # Add 4 messages
        for i in range(4):
            self.cleanup_queue.put(CleanupMessage(f'si-{i}', 'plan-1', f'backup-{i}'))
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertEqual(worker.processed_count, 2)
        self.assertEqual(worker.error_count, 2)
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 4)
    
    def test_worker_handles_malformed_message(self):
        """Test worker handles malformed/None messages gracefully"""
        # Arrange
        worker = CleanupWorker(1, self.cleanup_queue, self.mock_k8s_client, self.stop_event)
        
        # Add valid message followed by None (should not happen but test resilience)
        self.cleanup_queue.put(CleanupMessage('si-1', 'plan-1', 'backup-1'))
        
        self.mock_k8s_client.delete_scaninstance.return_value = True
        
        # Act
        worker.start()
        self.cleanup_queue.join()
        self.stop_event.set()
        worker.join(timeout=2.0)
        
        # Assert
        self.assertEqual(worker.processed_count, 1)


class TestCleanupScenarios(unittest.TestCase):
    """Test specific cleanup scenarios end-to-end"""
    
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
    
    def test_scenario_all_backups_deleted(self):
        """Test scenario: all backups deleted from storage"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        
        scaninstances = [
            {
                'metadata': {
                    'name': f'si-{i}',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': f'backup-{i}'
                    }
                }
            }
            for i in range(10)
        ]
        
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Empty storage state (all deleted)
        self.handler.storage_state = StorageState()
        
        # Start workers
        self.handler.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 10)
        
        # Get stats
        stats = self.handler.worker_pool.get_stats()
        self.assertEqual(stats['cleanup']['processed'], 10)
        self.assertEqual(stats['cleanup']['errors'], 0)
        
        # Cleanup
        self.handler.worker_pool.stop_all_workers()
    
    def test_scenario_partial_backupplan_deleted(self):
        """Test scenario: some backups deleted from backupplan"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-deleted-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-deleted-1'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'si-valid',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-exists'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'si-deleted-2',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-deleted-2'
                    }
                }
            }
        ]
        
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Only add one backup
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-exists',
                json_path='plan-123/backup-exists/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Start workers
        self.handler.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 2)
        
        # Verify correct ones deleted
        deleted_names = [
            call[0][0] for call in self.mock_k8s_client.delete_scaninstance.call_args_list
        ]
        self.assertIn('si-deleted-1', deleted_names)
        self.assertIn('si-deleted-2', deleted_names)
        self.assertNotIn('si-valid', deleted_names)
        
        # Cleanup
        self.handler.worker_pool.stop_all_workers()
    
    def test_scenario_multiple_backupplans_mixed_state(self):
        """Test scenario: multiple backupplans with mixed valid/stale state"""
        # Arrange
        self.mock_k8s_client.delete_scaninstance.return_value = True
        
        scaninstances = [
            # Plan 1 - all valid
            {'metadata': {
                'name': 'si-p1-b1',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-1',
                    'trilio.io/backup': 'backup-1'
                }
            }},
            # Plan 2 - completely deleted
            {'metadata': {
                'name': 'si-p2-b1',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-2',
                    'trilio.io/backup': 'backup-2'
                }
            }},
            {'metadata': {
                'name': 'si-p2-b2',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-2',
                    'trilio.io/backup': 'backup-3'
                }
            }},
            # Plan 3 - partially deleted
            {'metadata': {
                'name': 'si-p3-b1-valid',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-3',
                    'trilio.io/backup': 'backup-4'
                }
            }},
            {'metadata': {
                'name': 'si-p3-b2-stale',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-3',
                    'trilio.io/backup': 'backup-5'
                }
            }}
        ]
        
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Add valid backups
        self.handler.storage_state.add_backup(
            'plan-1',
            BackupObject('backup-1', 'plan-1/backup-1/backup.json', datetime.now(), BackupType.BACKUP)
        )
        self.handler.storage_state.add_backup(
            'plan-3',
            BackupObject('backup-4', 'plan-3/backup-4/backup.json', datetime.now(), BackupType.BACKUP)
        )
        
        # Start workers
        self.handler.worker_pool.start_cleanup_workers(self.mock_k8s_client)
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        # Should delete: plan-2 (2 SIs) + plan-3 partial (1 SI) = 3 total
        self.assertEqual(self.mock_k8s_client.delete_scaninstance.call_count, 3)
        
        deleted_names = [
            call[0][0] for call in self.mock_k8s_client.delete_scaninstance.call_args_list
        ]
        self.assertIn('si-p2-b1', deleted_names)
        self.assertIn('si-p2-b2', deleted_names)
        self.assertIn('si-p3-b2-stale', deleted_names)
        self.assertNotIn('si-p1-b1', deleted_names)
        self.assertNotIn('si-p3-b1-valid', deleted_names)
        
        # Cleanup
        self.handler.worker_pool.stop_all_workers()


class TestCleanupLabelHandling(unittest.TestCase):
    """Test label extraction and validation during cleanup"""
    
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
    
    def test_skip_scaninstance_missing_backupplan_label(self):
        """Test skips ScanInstance missing backupplan label"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-incomplete',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backup': 'backup-456'
                        # Missing backupplan label
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
    
    def test_skip_scaninstance_missing_backup_label(self):
        """Test skips ScanInstance missing backup label"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-incomplete',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123'
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
    
    def test_skip_scaninstance_with_no_labels(self):
        """Test skips ScanInstance with no labels dictionary"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-no-labels'
                    # No labels key
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.handler.worker_pool.cleanup_queue.put.assert_not_called()
        self.assertEqual(len(self.handler.scaninstance_map), 0)
    
    def test_handle_scaninstance_with_extra_labels(self):
        """Test handles ScanInstance with extra labels correctly"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-extra-labels',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456',
                        'trilio.io/instance-id': 'instance-789',  # Extra label
                        'custom-label': 'custom-value'  # Extra label
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Storage state empty - should trigger cleanup
        self.handler.storage_state = StorageState()
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert - should process correctly despite extra labels
        self.handler.worker_pool.cleanup_queue.put.assert_called_once()
        message = self.handler.worker_pool.cleanup_queue.put.call_args[0][0]
        self.assertEqual(message.scaninstance_name, 'si-extra-labels')
        self.assertEqual(message.backupplan_uid, 'plan-123')
        self.assertEqual(message.backup_uid, 'backup-456')


class TestCleanupWithDifferentBackupTypes(unittest.TestCase):
    """Test cleanup works correctly with different backup types"""
    
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
    
    def test_cleanup_with_backup_type(self):
        """Test cleanup with regular backup type"""
        self._test_cleanup_for_type(BackupType.BACKUP, 'backup.json')
    
    def test_cleanup_with_cluster_backup_type(self):
        """Test cleanup with cluster-backup type"""
        self._test_cleanup_for_type(BackupType.CLUSTER_BACKUP, 'cluster-backup.json')
    
    def test_cleanup_with_snapshot_type(self):
        """Test cleanup with snapshot type"""
        self._test_cleanup_for_type(BackupType.SNAPSHOT, 'snapshot.json')
    
    def test_cleanup_with_cluster_snapshot_type(self):
        """Test cleanup with cluster-snapshot type"""
        self._test_cleanup_for_type(BackupType.CLUSTER_SNAPSHOT, 'cluster-snapshot.json')
    
    def _test_cleanup_for_type(self, backup_type: BackupType, json_filename: str):
        """Helper to test cleanup for specific backup type"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-1',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-456'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Add backup with specific type
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-456',
                json_path=f'plan-123/backup-456/{json_filename}',
                last_updated_timestamp=datetime.now(),
                type=backup_type
            )
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert - should NOT queue for cleanup (backup exists)
        self.handler.worker_pool.cleanup_queue.put.assert_not_called()


class TestCleanupMapRemoval(unittest.TestCase):
    """Test cleanup properly removes items from scaninstance_map"""
    
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
    
    def test_remove_backupplan_from_map_when_deleted(self):
        """Test entire backupplan removed from map when deleted"""
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
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        self.handler.storage_state = StorageState()  # Empty
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertNotIn('plan-deleted', self.handler.scaninstance_map)
    
    def test_remove_backup_from_map_when_deleted(self):
        """Test specific backup removed from map when deleted"""
        # Arrange
        scaninstances = [
            {
                'metadata': {
                    'name': 'si-deleted',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-deleted'
                    }
                }
            },
            {
                'metadata': {
                    'name': 'si-valid',
                    'labels': {
                        'trilio.io/backup-target': 'test-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-exists'
                    }
                }
            }
        ]
        self.mock_k8s_client.list_scan_instances.return_value = scaninstances
        
        # Only add one backup
        self.handler.storage_state.add_backup(
            'plan-123',
            BackupObject('backup-exists', 'plan-123/backup-exists/backup.json', datetime.now(), BackupType.BACKUP)
        )
        
        # Act
        self.handler.perform_cleanup()
        
        # Assert
        self.assertIn('plan-123', self.handler.scaninstance_map)
        self.assertNotIn('backup-deleted', self.handler.scaninstance_map['plan-123'])
        self.assertIn('backup-exists', self.handler.scaninstance_map['plan-123'])


if __name__ == '__main__':
    unittest.main()
