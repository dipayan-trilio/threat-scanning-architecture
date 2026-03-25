#!/usr/bin/env python3
"""
Integration tests for targetPoller discovery using envtest-style approach.

This test suite starts real Kubernetes API server and etcd BINARIES directly,
exactly like controller-runtime's envtest (NO kind, NO Docker required).

Tests discovery phase logic with real K8s API:
- ScanInstance creation via K8s API
- Duplicate detection (idempotency)
- Cluster backup hierarchy verification
- Worker pool integration

Shares the same EnvTestSetup infrastructure as test_cleanup_envtest.py
"""

import unittest
import os
import sys
import time
from datetime import datetime

# pytest markers
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Import EnvTestSetup from cleanup envtest
from targetPoller.tests.test_cleanup_envtest import EnvTestSetup
from targetPoller.k8s.client import K8sClient
from targetPoller.handlers.base_handler import BaseTargetHandler
from targetPoller.models.storage_state import StorageState, BackupObject, BackupType, ScanConfig
from mount_utility import logger


class MockHandlerForEnvTest(BaseTargetHandler):
    """Mock handler for envtest - overrides abstract methods"""
    
    def populate_storage_state(self):
        return StorageState()
    
    def refresh_storage_state(self):
        # Override in tests
        pass
    
    def _read_scan_config(self, backupplan_uid, backup):
        # Override in tests
        return None


@unittest.skipUnless(HAS_PYTEST, "pytest required for envtest markers")
@pytest.mark.envtest
class TestDiscoveryWithEnvTest(unittest.TestCase):
    """
    Integration tests for discovery phase using real K8s API.
    
    Tests:
    - ScanInstance creation with all labels
    - Existing ScanInstance detection (idempotency)
    - Multiple backupplans with real CRs
    - Cluster backup hierarchy
    - Worker pool integration
    """
    
    @classmethod
    def setUpClass(cls):
        """Start K8s environment once for all tests"""
        print("\n" + "="*80)
        print("Setting up envtest environment for discovery tests...")
        print("="*80)
        
        cls.env = EnvTestSetup()
        cls.env.setup()
        
        # Get kubeconfig path
        cls.kubeconfig_path = cls.env.kubeconfig_path
        print(f"✓ Kubeconfig: {cls.kubeconfig_path}")
        
        # Create K8s client
        cls.k8s_client = K8sClient(kubeconfig_path=cls.kubeconfig_path, logger=logger.logger)
        
        print("✓ EnvTest environment ready for discovery tests")
        print("="*80 + "\n")
    
    @classmethod
    def tearDownClass(cls):
        """Stop K8s environment"""
        print("\n" + "="*80)
        print("Tearing down envtest environment...")
        print("="*80)
        
        cls.env.teardown()
        
        print("✓ EnvTest environment torn down")
        print("="*80 + "\n")
    
    def setUp(self):
        """Set up for each test"""
        # Create test Target CR
        self.target_cr = self.env._create_test_target()
        
        # Clean up any existing ScanInstances from previous tests
        try:
            scaninstances = self.k8s_client.list_scan_instances(
                label_selector='trilio.io/backup-target=test-target'
            )
            for si in scaninstances:
                self.k8s_client.delete_scaninstance(si['metadata']['name'])
                logger.logger.info(f"Cleaned up ScanInstance: {si['metadata']['name']}")
        except Exception as e:
            logger.logger.warning(f"Error cleaning up ScanInstances: {e}")
    
    def tearDown(self):
        """Clean up after each test"""
        # Clean up ScanInstances
        try:
            scaninstances = self.k8s_client.list_scan_instances(
                label_selector='trilio.io/backup-target=test-target'
            )
            for si in scaninstances:
                self.k8s_client.delete_scaninstance(si['metadata']['name'])
        except Exception as e:
            pass
    
    def test_discovery_creates_scaninstance_with_labels(self):
        """Test discovery creates ScanInstance with all required labels"""
        # Arrange
        handler = MockHandlerForEnvTest(
            target_cr=self.target_cr,
            k8s_client=self.k8s_client,
            logger_instance=logger.logger
        )
        
        # Setup storage state
        handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-test-1',
            json_path='plan-test-1/backup-test-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('plan-test-1', backup)
        
        # Mock methods
        handler.refresh_storage_state = lambda: None
        handler._read_scan_config = lambda bp_uid, b: ScanConfig(enabled=True, scan_old_backups=False)
        handler._has_scaninstance = lambda bp_uid, b_uid: False
        
        # Start workers
        handler.worker_pool.start_creation_workers(self.k8s_client)
        
        # Act
        handler.perform_discovery()
        
        # Wait for worker to process
        time.sleep(2)
        
        # Assert - verify ScanInstance was created with labels
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=test-target'
        )
        
        self.assertEqual(len(scaninstances), 1)
        
        si = scaninstances[0]
        self.assertIn('triliovault.trilio.io/backupplan-uid', si['metadata']['labels'])
        self.assertEqual(si['metadata']['labels']['triliovault.trilio.io/backupplan-uid'], 'plan-test-1')
        self.assertIn('triliovault.trilio.io/backup-uid', si['metadata']['labels'])
        self.assertEqual(si['metadata']['labels']['triliovault.trilio.io/backup-uid'], 'backup-test-1')
        self.assertIn('trilio.io/backup-target', si['metadata']['labels'])
        self.assertEqual(si['metadata']['labels']['trilio.io/backup-target'], 'test-target')
        
        # Stop workers
        handler.worker_pool.stop_all_workers()
    
    def test_discovery_idempotent_no_duplicates(self):
        """Test discovery twice doesn't create duplicate ScanInstances"""
        # Arrange
        handler = MockHandlerForEnvTest(
            target_cr=self.target_cr,
            k8s_client=self.k8s_client,
            logger_instance=logger.logger
        )
        
        handler.storage_state = StorageState()
        backup = BackupObject(
            backup_uid='backup-test-2',
            json_path='plan-test-2/backup-test-2/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('plan-test-2', backup)
        
        handler.refresh_storage_state = lambda: None
        handler._read_scan_config = lambda bp_uid, b: ScanConfig(enabled=True, scan_old_backups=False)
        
        # Start workers
        handler.worker_pool.start_creation_workers(self.k8s_client)
        
        # Act - run discovery twice
        handler.perform_discovery()
        time.sleep(2)
        
        # Reset scaninstance_map for second run
        handler.scaninstance_map = {}
        handler.perform_discovery()
        time.sleep(2)
        
        # Assert - should still only have 1 ScanInstance
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=test-target'
        )
        
        self.assertEqual(len(scaninstances), 1)
        
        # Stop workers
        handler.worker_pool.stop_all_workers()
    
    def test_discovery_multiple_backupplans(self):
        """Test discovery with multiple backupplans creates multiple ScanInstances"""
        # Arrange
        handler = MockHandlerForEnvTest(
            target_cr=self.target_cr,
            k8s_client=self.k8s_client,
            logger_instance=logger.logger
        )
        
        handler.storage_state = StorageState()
        
        # Add 3 backupplans
        for i in range(3):
            backup = BackupObject(
                backup_uid=f'backup-multi-{i}',
                json_path=f'plan-multi-{i}/backup-multi-{i}/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP,
                status='available'
            )
            handler.storage_state.add_backup(f'plan-multi-{i}', backup)
        
        handler.refresh_storage_state = lambda: None
        handler._read_scan_config = lambda bp_uid, b: ScanConfig(enabled=True, scan_old_backups=False)
        handler._has_scaninstance = lambda bp_uid, b_uid: False
        
        # Start workers
        handler.worker_pool.start_creation_workers(self.k8s_client)
        
        # Act
        handler.perform_discovery()
        time.sleep(3)
        
        # Assert - should have 3 ScanInstances
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=test-target'
        )
        
        self.assertEqual(len(scaninstances), 3)
        
        # Verify each has correct labels
        backupplan_uids = set()
        backup_uids = set()
        for si in scaninstances:
            backupplan_uids.add(si['metadata']['labels']['triliovault.trilio.io/backupplan-uid'])
            backup_uids.add(si['metadata']['labels']['triliovault.trilio.io/backup-uid'])
        
        self.assertEqual(len(backupplan_uids), 3)
        self.assertEqual(len(backup_uids), 3)
        
        # Stop workers
        handler.worker_pool.stop_all_workers()
    
    def test_discovery_cluster_backup_hierarchy(self):
        """Test cluster backup structure: only cluster backup gets ScanInstance, children skipped"""
        # Arrange
        handler = MockHandlerForEnvTest(
            target_cr=self.target_cr,
            k8s_client=self.k8s_client,
            logger_instance=logger.logger
        )
        
        handler.storage_state = StorageState()
        
        # Cluster backup
        cluster_backup = BackupObject(
            backup_uid='cluster-backup-1',
            json_path='cluster-plan/cluster-backup-1/cluster-backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.CLUSTER_BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('cluster-plan', cluster_backup)
        
        # Child backups
        child_backup1 = BackupObject(
            backup_uid='child-backup-1',
            json_path='child-plan-1/child-backup-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('child-plan-1', child_backup1)
        
        child_backup2 = BackupObject(
            backup_uid='child-backup-2',
            json_path='child-plan-2/child-backup-2/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('child-plan-2', child_backup2)
        
        handler.refresh_storage_state = lambda: None
        
        # Mock: cluster enabled, children return None (owned by cluster)
        def mock_read_config(bp_uid, b):
            if bp_uid == 'cluster-plan':
                return ScanConfig(enabled=True, scan_old_backups=False)
            else:
                return None  # Child backupplan
        
        handler._read_scan_config = mock_read_config
        handler._has_scaninstance = lambda bp_uid, b_uid: False
        
        # Start workers
        handler.worker_pool.start_creation_workers(self.k8s_client)
        
        # Act
        handler.perform_discovery()
        time.sleep(2)
        
        # Assert - should only have 1 ScanInstance (for cluster backup)
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=test-target'
        )
        
        self.assertEqual(len(scaninstances), 1)
        
        # Verify it's the cluster backup
        si = scaninstances[0]
        self.assertEqual(si['metadata']['labels']['triliovault.trilio.io/backup-uid'], 'cluster-backup-1')
        self.assertEqual(si['metadata']['labels']['triliovault.trilio.io/backupplan-uid'], 'cluster-plan')
        
        # Stop workers
        handler.worker_pool.stop_all_workers()
    
    def test_discovery_scan_old_backups_true_creates_multiple(self):
        """Test scanOldBackups=true creates ScanInstances for all backups"""
        # Arrange
        handler = MockHandlerForEnvTest(
            target_cr=self.target_cr,
            k8s_client=self.k8s_client,
            logger_instance=logger.logger
        )
        
        handler.storage_state = StorageState()
        
        # Add 5 backups for same backupplan
        for i in range(5):
            backup = BackupObject(
                backup_uid=f'backup-old-{i}',
                json_path=f'plan-old/backup-old-{i}/backup.json',
                last_updated_timestamp=datetime(2024, 1, i+1),
                type=BackupType.BACKUP,
                status='available'
            )
            handler.storage_state.add_backup('plan-old', backup)
        
        handler.refresh_storage_state = lambda: None
        handler._read_scan_config = lambda bp_uid, b: ScanConfig(enabled=True, scan_old_backups=True)
        handler._has_scaninstance = lambda bp_uid, b_uid: False
        
        # Start workers
        handler.worker_pool.start_creation_workers(self.k8s_client)
        
        # Act
        handler.perform_discovery()
        time.sleep(3)
        
        # Assert - should have 5 ScanInstances
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=test-target'
        )
        
        self.assertEqual(len(scaninstances), 5)
        
        # Verify all have same backupplan but different backup UIDs
        backupplan_uids = set()
        backup_uids = set()
        for si in scaninstances:
            backupplan_uids.add(si['metadata']['labels']['triliovault.trilio.io/backupplan-uid'])
            backup_uids.add(si['metadata']['labels']['triliovault.trilio.io/backup-uid'])
        
        self.assertEqual(len(backupplan_uids), 1)  # All same backupplan
        self.assertEqual(len(backup_uids), 5)  # 5 different backups
        
        # Stop workers
        handler.worker_pool.stop_all_workers()
    
    def test_discovery_mixed_enabled_disabled_configs(self):
        """Test multiple backupplans with mixed enabled/disabled configs"""
        # Arrange
        handler = MockHandlerForEnvTest(
            target_cr=self.target_cr,
            k8s_client=self.k8s_client,
            logger_instance=logger.logger
        )
        
        handler.storage_state = StorageState()
        
        # Plan 1: enabled
        backup1 = BackupObject(
            backup_uid='backup-enabled-1',
            json_path='plan-enabled-1/backup-enabled-1/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('plan-enabled-1', backup1)
        
        # Plan 2: disabled
        backup2 = BackupObject(
            backup_uid='backup-disabled',
            json_path='plan-disabled/backup-disabled/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('plan-disabled', backup2)
        
        # Plan 3: enabled
        backup3 = BackupObject(
            backup_uid='backup-enabled-2',
            json_path='plan-enabled-2/backup-enabled-2/backup.json',
            last_updated_timestamp=datetime.now(),
            type=BackupType.BACKUP,
            status='available'
        )
        handler.storage_state.add_backup('plan-enabled-2', backup3)
        
        handler.refresh_storage_state = lambda: None
        
        # Mock: plans 1 and 3 enabled, plan 2 disabled
        def mock_read_config(bp_uid, b):
            if bp_uid == 'plan-disabled':
                return ScanConfig(enabled=False, scan_old_backups=False)
            else:
                return ScanConfig(enabled=True, scan_old_backups=False)
        
        handler._read_scan_config = mock_read_config
        handler._has_scaninstance = lambda bp_uid, b_uid: False
        
        # Start workers
        handler.worker_pool.start_creation_workers(self.k8s_client)
        
        # Act
        handler.perform_discovery()
        time.sleep(2)
        
        # Assert - should only have 2 ScanInstances (enabled plans only)
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=test-target'
        )
        
        self.assertEqual(len(scaninstances), 2)
        
        # Verify correct backups
        backup_uids = [si['metadata']['labels']['triliovault.trilio.io/backup-uid'] for si in scaninstances]
        self.assertIn('backup-enabled-1', backup_uids)
        self.assertIn('backup-enabled-2', backup_uids)
        self.assertNotIn('backup-disabled', backup_uids)
        
        # Stop workers
        handler.worker_pool.stop_all_workers()
    
    def test_discovery_worker_pool_integration(self):
        """Test worker pool processes creation messages correctly"""
        # Arrange
        handler = MockHandlerForEnvTest(
            target_cr=self.target_cr,
            k8s_client=self.k8s_client,
            logger_instance=logger.logger
        )
        
        handler.storage_state = StorageState()
        
        # Add 10 backups
        for i in range(10):
            backup = BackupObject(
                backup_uid=f'backup-worker-{i}',
                json_path=f'plan-worker-{i}/backup-worker-{i}/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP,
                status='available'
            )
            handler.storage_state.add_backup(f'plan-worker-{i}', backup)
        
        handler.refresh_storage_state = lambda: None
        handler._read_scan_config = lambda bp_uid, b: ScanConfig(enabled=True, scan_old_backups=False)
        handler._has_scaninstance = lambda bp_uid, b_uid: False
        
        # Start workers (3 workers)
        handler.worker_pool.start_creation_workers(self.k8s_client)
        
        # Act
        handler.perform_discovery()
        time.sleep(4)
        
        # Assert - all 10 ScanInstances should be created
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=test-target'
        )
        
        self.assertEqual(len(scaninstances), 10)
        
        # Verify stats
        stats = handler.worker_pool.get_stats()
        self.assertEqual(stats['creation']['processed'], 10)
        self.assertEqual(stats['creation']['errors'], 0)
        
        # Stop workers
        handler.worker_pool.stop_all_workers()


if __name__ == '__main__':
    unittest.main()
