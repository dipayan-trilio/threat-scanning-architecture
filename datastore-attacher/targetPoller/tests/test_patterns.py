#!/usr/bin/env python3
"""
Example test patterns for targetPoller cleanup testing.

This file demonstrates common test patterns used in the test suite.
Use these as templates when adding new tests.
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from targetPoller.models.storage_state import (
    StorageState, BackupObject, BackupType, CleanupMessage
)


# =============================================================================
# PATTERN 1: Testing Cleanup Logic with Mocked K8s Client
# =============================================================================

class ExampleCleanupLogicTest(unittest.TestCase):
    """
    Pattern: Test cleanup logic by mocking K8s API and pre-populating storage state
    
    Use this when testing:
    - Stale detection algorithm
    - Queue message creation
    - Map building
    """
    
    def test_example_stale_detection(self):
        """Example: Detect stale ScanInstance when backup is deleted"""
        # Step 1: Mock the K8s client
        mock_k8s_client = Mock()
        mock_k8s_client.list_scan_instances.return_value = [
            {
                'metadata': {
                    'name': 'scaninstance-to-delete',
                    'labels': {
                        'trilio.io/backup-target': 'my-target',
                        'trilio.io/backupplan': 'plan-123',
                        'trilio.io/backup': 'backup-deleted'
                    }
                }
            }
        ]
        
        # Step 2: Create handler with mocked dependencies
        # (In real tests, use MockHandler from test_cleanup.py)
        
        # Step 3: Pre-populate storage state (simulate what's on storage)
        storage_state = StorageState()
        # Note: NOT adding 'backup-deleted' to trigger cleanup
        storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-exists',  # Different backup
                json_path='plan-123/backup-exists/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Step 4: Run cleanup
        # handler.perform_cleanup()
        
        # Step 5: Assert cleanup was triggered
        # assert mock_worker_pool.cleanup_queue.put.called
        # assert message.scaninstance_name == 'scaninstance-to-delete'


# =============================================================================
# PATTERN 2: Testing Worker Thread Processing
# =============================================================================

class ExampleWorkerTest(unittest.TestCase):
    """
    Pattern: Test worker threads with real queue and mocked K8s API
    
    Use this when testing:
    - Worker message processing
    - Error handling
    - Concurrency
    """
    
    def test_example_worker_processes_message(self):
        """Example: Worker processes cleanup message and calls delete API"""
        # Step 1: Mock K8s client to simulate deletion
        mock_k8s_client = Mock()
        mock_k8s_client.delete_scaninstance.return_value = True
        
        # Step 2: Create real queue (not mocked!)
        import queue
        cleanup_queue = queue.Queue()
        
        # Step 3: Create real threading primitives
        import threading
        stop_event = threading.Event()
        
        # Step 4: Create worker
        from targetPoller.workers.queue_workers import CleanupWorker
        worker = CleanupWorker(
            worker_id=1,
            cleanup_queue=cleanup_queue,
            k8s_client=mock_k8s_client,
            stop_event=stop_event
        )
        
        # Step 5: Add message to queue
        message = CleanupMessage('si-1', 'plan-1', 'backup-1')
        cleanup_queue.put(message)
        
        # Step 6: Start worker and wait
        worker.start()
        cleanup_queue.join()  # Block until processed
        
        # Step 7: Stop worker
        stop_event.set()
        worker.join(timeout=2.0)
        
        # Step 8: Assert
        mock_k8s_client.delete_scaninstance.assert_called_once_with('si-1')
        assert worker.processed_count == 1
        assert worker.error_count == 0


# =============================================================================
# PATTERN 3: Testing Storage State Operations
# =============================================================================

class ExampleStorageStateTest(unittest.TestCase):
    """
    Pattern: Test storage state with pure data structures (no mocks needed)
    
    Use this when testing:
    - Add/query operations
    - Data structure integrity
    - Query correctness
    """
    
    def test_example_has_backup_query(self):
        """Example: Query if backup exists in storage state"""
        # Step 1: Create storage state
        state = StorageState()
        
        # Step 2: Add test data
        state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-456',
                json_path='plan-123/backup-456/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Step 3: Query
        exists = state.has_backup('plan-123', 'backup-456')
        not_exists = state.has_backup('plan-123', 'backup-999')
        
        # Step 4: Assert
        assert exists is True
        assert not_exists is False


# =============================================================================
# PATTERN 4: Testing Error Handling
# =============================================================================

class ExampleErrorHandlingTest(unittest.TestCase):
    """
    Pattern: Test error handling by making mocks raise exceptions
    
    Use this when testing:
    - Exception handling
    - Error recovery
    - Graceful degradation
    """
    
    def test_example_worker_handles_exception(self):
        """Example: Worker handles K8s API exception without crashing"""
        # Step 1: Mock K8s client to raise exception
        mock_k8s_client = Mock()
        mock_k8s_client.delete_scaninstance.side_effect = Exception("API timeout")
        
        # Step 2: Set up worker and queue
        import queue
        import threading
        cleanup_queue = queue.Queue()
        stop_event = threading.Event()
        
        from targetPoller.workers.queue_workers import CleanupWorker
        worker = CleanupWorker(1, cleanup_queue, mock_k8s_client, stop_event)
        
        # Step 3: Add message
        cleanup_queue.put(CleanupMessage('si-1', 'plan-1', 'backup-1'))
        
        # Step 4: Run
        worker.start()
        cleanup_queue.join()
        stop_event.set()
        worker.join(timeout=2.0)
        
        # Step 5: Assert - worker should NOT crash
        assert worker.error_count == 1
        assert worker.processed_count == 0
        assert not worker.is_alive()  # Clean shutdown


# =============================================================================
# PATTERN 5: Testing Complex Scenarios
# =============================================================================

class ExampleComplexScenarioTest(unittest.TestCase):
    """
    Pattern: Test complex real-world scenarios with multiple components
    
    Use this when testing:
    - End-to-end flows
    - Multiple interactions
    - Complex state
    """
    
    def test_example_mixed_valid_and_stale(self):
        """
        Example: Complex scenario with multiple plans, some valid, some stale
        
        Setup:
        - Plan 1: All backups exist → no cleanup
        - Plan 2: Completely deleted → cleanup all ScanInstances
        - Plan 3: Partially deleted → cleanup only stale ones
        """
        # Step 1: Create comprehensive test data
        scaninstances = [
            # Plan 1 - Valid
            {'metadata': {
                'name': 'si-p1-valid',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-1',
                    'trilio.io/backup': 'backup-1'
                }
            }},
            # Plan 2 - Stale (plan deleted)
            {'metadata': {
                'name': 'si-p2-stale-1',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-2-deleted',
                    'trilio.io/backup': 'backup-2'
                }
            }},
            {'metadata': {
                'name': 'si-p2-stale-2',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-2-deleted',
                    'trilio.io/backup': 'backup-3'
                }
            }},
            # Plan 3 - Mixed
            {'metadata': {
                'name': 'si-p3-valid',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-3',
                    'trilio.io/backup': 'backup-4'
                }
            }},
            {'metadata': {
                'name': 'si-p3-stale',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-3',
                    'trilio.io/backup': 'backup-5-deleted'
                }
            }}
        ]
        
        # Step 2: Mock K8s client
        mock_k8s_client = Mock()
        mock_k8s_client.list_scan_instances.return_value = scaninstances
        mock_k8s_client.delete_scaninstance.return_value = True
        
        # Step 3: Create storage state with valid backups only
        storage_state = StorageState()
        storage_state.add_backup(
            'plan-1',
            BackupObject('backup-1', 'path', datetime.now(), BackupType.BACKUP)
        )
        storage_state.add_backup(
            'plan-3',
            BackupObject('backup-4', 'path', datetime.now(), BackupType.BACKUP)
        )
        # Note: plan-2 and backup-5 are NOT added
        
        # Step 4: Run cleanup
        # handler.storage_state = storage_state
        # handler.perform_cleanup()
        
        # Step 5: Assert
        # Expected: 3 deletions (2 from plan-2, 1 from plan-3)
        # assert mock_k8s_client.delete_scaninstance.call_count == 3
        # deleted = [call[0][0] for call in mock_k8s_client.delete_scaninstance.call_args_list]
        # assert 'si-p2-stale-1' in deleted
        # assert 'si-p2-stale-2' in deleted
        # assert 'si-p3-stale' in deleted
        # assert 'si-p1-valid' not in deleted
        # assert 'si-p3-valid' not in deleted


# =============================================================================
# PATTERN 6: Testing with Side Effects
# =============================================================================

class ExampleSideEffectsTest(unittest.TestCase):
    """
    Pattern: Use mock side_effect for different responses per call
    
    Use this when testing:
    - Retries
    - Partial failures
    - Changing behavior over time
    """
    
    def test_example_partial_failure(self):
        """Example: Some deletions succeed, some fail"""
        # Step 1: Mock with side_effect (different result per call)
        mock_k8s_client = Mock()
        mock_k8s_client.delete_scaninstance.side_effect = [
            True,                           # First call: success
            False,                          # Second call: failure
            Exception("Network timeout"),   # Third call: exception
            True                            # Fourth call: success
        ]
        
        # Step 2: Add messages and process
        # (worker processes 4 messages)
        
        # Step 3: Assert
        # Expected: 2 successes, 2 failures
        # assert worker.processed_count == 2
        # assert worker.error_count == 2


# =============================================================================
# Key Points for Test Implementation
# =============================================================================

"""
GOLDEN RULES:

1. MOCK EXTERNAL DEPENDENCIES
   - K8s API (list_scan_instances, delete_scaninstance)
   - File system (pre-populate storage_state)
   - Network (S3 client, NFS mount)
   
2. USE REAL DATA STRUCTURES
   - StorageState (test queries work correctly)
   - BackupObject (test data integrity)
   - queue.Queue (test real blocking behavior)
   - threading.Event (test real synchronization)

3. TEST BOTH PATHS
   - Happy path: everything works
   - Sad path: failures and exceptions
   
4. ISOLATE TESTS
   - Each test has own setUp()
   - No shared state between tests
   - Clean up in tearDown()

5. DESCRIPTIVE NAMES
   - test_what_when_expected
   - Example: test_cleanup_queues_message_when_backup_deleted

6. ARRANGE-ACT-ASSERT
   - Arrange: Set up mocks and data
   - Act: Call the method under test
   - Assert: Verify behavior

7. USE REAL THREADS FOR CONCURRENCY TESTS
   - Mock queue would miss race conditions
   - Use real workers to catch thread bugs
   - Always set stop_event in tearDown()
"""


if __name__ == '__main__':
    print(__doc__)
