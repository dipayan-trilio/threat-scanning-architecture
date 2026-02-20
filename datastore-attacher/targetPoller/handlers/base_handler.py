"""
Base handler for targetPoller with queue-based architecture.

Defines the common interface and orchestration logic for all backup types.
"""

import os
import sys
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from mount_utility import logger, constants
from mount_utility.mount_by_target_crd import triliodata_crd_parser

from targetPoller.models.storage_state import (
    StorageState, BackupObject, BackupType,
    CleanupMessage, CreationMessage, ScanConfig
)
from targetPoller.workers.queue_workers import WorkerPool

logging = logger.logger

# Standard mount point for all targets
TRILIODATA_MOUNT_PATH = '/triliodata'

# Ignore backups updated within last 5 minutes (might still be in progress)
IGNORE_RECENT_UPDATES_MINUTES = 5


class BaseTargetHandler(ABC):
    """
    Abstract base class for backup target handlers.
    
    Provides common orchestration logic for:
    - Initialization (storage state population)
    - Cleanup phase (ScanInstance cleanup)
    - Discovery phase (new backup detection and ScanInstance creation)
    """
    
    def __init__(self, target_cr: Dict, k8s_client, logger_instance):
        """
        Initialize handler.
        
        Args:
            target_cr: Target custom resource dictionary
            k8s_client: Kubernetes client instance
            logger_instance: Logger instance
        """
        self.target_cr = target_cr
        self.k8s_client = k8s_client
        self.logger = logger_instance
        # Parse target CR
        self.parsed_target = triliodata_crd_parser.parse_cr_response(target_cr)
        self.target_name = target_cr['metadata']['name']
        self.target_uid = target_cr['metadata']['uid']
        self.target_type = self.parsed_target.get('storageType', '').lower()
        
        # Storage state - populated during initialization
        self.storage_state = StorageState()
        
        # Worker pool for async queue processing
        self.worker_pool = WorkerPool(num_workers=3)
        
        # ScanInstance map (populated during cleanup phase)
        # Structure: {backupplan_uid: {backup_uid: [scaninstance_names]}}
        self.scaninstance_map = {}
        
        self.logger.info(
            f"Initialized handler for target: {self.target_name} "
            f"(type: {self.target_type}, uid: {self.target_uid})"
        )
    
    # ============= Abstract Methods (Type-specific) =============
    
    @abstractmethod
    def detect_backup_type(self) -> str:
        """
        Detect the backup type (TVK/TVO).
        
        Should check for type-specific marker files (e.g., tvk-meta.json).
        
        Returns:
            'TVK', 'TVO', or 'UNKNOWN'
        """
        pass
    
    @abstractmethod
    def populate_storage_state(self) -> StorageState:
        """
        Populate the storage state with all backups from the target.
        
        Should:
        1. Mount target (if NFS) or connect (if S3)
        2. Scan for all backupplans and backups
        3. For each backup, extract:
           - backup_uid
           - json_path (path to backup.json/cluster-backup.json/etc.)
           - last_updated_timestamp (from file metadata)
           - type (backup/cluster-backup/snapshot/cluster-snapshot)
        4. Filter out backups updated within last 5 minutes
        5. Return populated StorageState
        
        Returns:
            StorageState object with all backups
        """
        pass
    
    @abstractmethod
    def refresh_storage_state(self):
        """
        Refresh the storage state with latest data from target.
        
        Called at the start of discovery phase to get any new backups
        that may have been created since initialization.
        """
        pass
    
    @abstractmethod
    def _read_scan_config(self, backupplan_uid: str, backup: BackupObject) -> Optional[ScanConfig]:
        """
        Read scan configuration for a backup.
        
        Implementation is type-specific (TVK vs TVO).
        Uses the backup type to determine which backupplan file to read.
        
        Also checks if backupplan is a child of ClusterBackupPlan (via ownerReferences).
        If yes, returns None to skip this backupplan entirely.
        
        Args:
            backupplan_uid: BackupPlan UID (since it's not stored in BackupObject)
            backup: BackupObject containing backup details including type
            
        Returns:
            ScanConfig object or None if not found/configured/child of cluster
        """
        pass
    
    # ============= Initialization Phase =============
    
    def initialize(self):
        """
        Initialize the handler.
        
        Steps:
        1. Detect backup type (if not already detected by factory)
        2. Populate storage state
        3. Start worker threads
        """
        self.logger.info("Starting initialization phase")
        
        # Step 1: Detect backup type (skip if already detected by factory)
        if not hasattr(self, 'backup_type_detected') or not self.backup_type_detected:
            backup_type = self.detect_backup_type()
            self.logger.info(f"Detected backup type: {backup_type}")
            
            if backup_type == 'UNKNOWN':
                raise RuntimeError(
                    f"Could not determine backup type for target {self.target_name}"
                )
        else:
            self.logger.info(f"Backup type already detected by factory: {self.backup_type}")
        
        # Step 2: Populate storage state
        self.logger.info("Populating storage state...")
        self.storage_state = self.populate_storage_state()
        self.logger.info(
            f"✓ Storage state populated: {self.storage_state.total_backupplans} backupplans, "
            f"{self.storage_state.total_backups} backups"
        )
        
        # Step 3: Start worker threads
        self.logger.info("Starting worker threads...")
        self.worker_pool.start_all_workers(self.k8s_client, self.target_cr)
        self.logger.info("Completed initialization phase")
    
    # ============= Cleanup Phase =============
    
    def perform_cleanup(self):
        """
        Cleanup phase: Remove stale ScanInstance CRs.
        
        Steps:
        1. List all ScanInstances for this target
        2. Group by backupplan UID
        3. For each ScanInstance:
           - Extract backupplan_uid and backup_uid
           - If backupplan not in storage_state → Queue for cleanup
           - If backup not in storage_state → Queue for cleanup
        4. Wait for cleanup queue to finish
        """
        self.logger.info("Starting cleanup phase")
        
        # Step 1: List all ScanInstances for this target
        # Use target name for filtering (matches label set at creation)
        label_selector = f"trilio.io/backup-target={self.target_name}"
        scaninstances = self.k8s_client.list_scan_instances(label_selector=label_selector)
        
        self.logger.info(f"Found {len(scaninstances)} ScanInstances for this target")
        
        if not scaninstances:
            self.logger.info("No ScanInstances found, cleanup complete")
            return
        
        # Step 2: Group by backupplan and build map
        for si in scaninstances:
            si_name = si['metadata']['name']
            si_labels = si['metadata'].get('labels', {})
            
            backupplan_uid = si_labels.get('trilio.io/backupplan', '')
            backup_uid = si_labels.get('trilio.io/backup', '')
            
            if not backupplan_uid or not backup_uid:
                # ScanInstance hasn't gone through prescan yet
                # Prescan will add these labels after validation
                # Skip for now - will be processed in next polling cycle
                self.logger.debug(
                    f"ScanInstance {si_name} missing backupplan/backup labels "
                    f"(prescan not completed yet), skipping"
                )
                continue
            
            # Add to map
            if backupplan_uid not in self.scaninstance_map:
                self.scaninstance_map[backupplan_uid] = {}
            if backup_uid not in self.scaninstance_map[backupplan_uid]:
                self.scaninstance_map[backupplan_uid][backup_uid] = []
            self.scaninstance_map[backupplan_uid][backup_uid].append(si_name)
        
        self.logger.info(
            f"Grouped ScanInstances into {len(self.scaninstance_map)} backupplans"
        )
        
        # Step 3: Check each ScanInstance against storage state
        stale_count = 0
        
        for backupplan_uid, backups_map in list(self.scaninstance_map.items()):
            # Check if backupplan exists in storage state
            if not self.storage_state.has_backupplan(backupplan_uid):
                # Entire backupplan deleted - queue all ScanInstances for cleanup
                self.logger.info(
                    f"BackupPlan {backupplan_uid} not found in storage, "
                    f"queueing {sum(len(sis) for sis in backups_map.values())} ScanInstances for cleanup"
                )
                
                for backup_uid, si_names in backups_map.items():
                    for si_name in si_names:
                        message = CleanupMessage(
                            scaninstance_name=si_name,
                            backupplan_uid=backupplan_uid,
                            backup_uid=backup_uid
                        )
                        self.worker_pool.cleanup_queue.put(message)
                        stale_count += 1
                
                # Remove from map
                del self.scaninstance_map[backupplan_uid]
                continue
            
            # BackupPlan exists, check individual backups
            for backup_uid, si_names in list(backups_map.items()):
                if not self.storage_state.has_backup(backupplan_uid, backup_uid):
                    # Backup deleted - queue ScanInstances for cleanup
                    self.logger.debug(
                        f"Backup {backup_uid} not found in backupplan {backupplan_uid}, "
                        f"queueing {len(si_names)} ScanInstances for cleanup"
                    )
                    
                    for si_name in si_names:
                        message = CleanupMessage(
                            scaninstance_name=si_name,
                            backupplan_uid=backupplan_uid,
                            backup_uid=backup_uid
                        )
                        self.worker_pool.cleanup_queue.put(message)
                        stale_count += 1
                    
                    # Remove from map
                    del backups_map[backup_uid]
        
        self.logger.info(f"Queued {stale_count} stale ScanInstances for cleanup")
        
        # Step 4: Wait for cleanup to complete
        if stale_count > 0:
            self.worker_pool.wait_for_cleanup_completion()
        
        self.logger.info("Completed cleanup phase")
    
    # ============= Discovery Phase =============
    
    def perform_discovery(self):
        """
        Discovery phase: Find new backups and create ScanInstances.
        
        Steps:
        1. Refresh storage state
        2. For each backupplan:
           a. Get latest backup
           b. Check if it's available and has no ScanInstance
           c. Read backupplan.json to get scanConfig
           d. If scanEnabled=true, scanOldBackups=false: Process latest backup only
           e. If scanEnabled=true, scanOldBackups=true: Process all unprocessed backups
        3. Wait for creation queue to finish
        """
        self.logger.info("Starting discovery phase")
        
        # Step 1: Refresh storage state
        self.logger.info("Refreshing storage state...")
        self.refresh_storage_state()
        self.logger.info(
            f"Storage state refreshed: {self.storage_state.total_backupplans} backupplans, "
            f"{self.storage_state.total_backups} backups"
        )
        
        # Step 2: Process each backupplan
        backupplan_uids = self.storage_state.get_all_backupplan_uids()
        self.logger.info(f"Processing {len(backupplan_uids)} backupplans...")
        
        for backupplan_uid in backupplan_uids:
            self.logger.info(f"")
            
            try:
                self._process_backupplan(backupplan_uid)
            except Exception as e:
                self.logger.error(
                    f"Error processing backupplan {backupplan_uid}: {str(e)}",
                    exc_info=True
                )
        
        # Step 3: Wait for creation queue to finish
        stats = self.worker_pool.get_stats()
        if stats['creation']['queue_size'] > 0:
            self.logger.info(
                f"Waiting for {stats['creation']['queue_size']} ScanInstance creations to complete..."
            )
            self.worker_pool.wait_for_creation_completion()
        
        self.logger.info("Completed discovery phase")
    
    def _process_backupplan(self, backupplan_uid: str):
        """
        Process a single backupplan for discovery.
        """
        # Get latest backup
        latest_backup = self.get_latest_backup_for_backupplan(backupplan_uid)
        
        if not latest_backup:
            self.logger.warning(f"  No backups found for backupplan {backupplan_uid}")
            return
        
        self.logger.info(f"  Latest backup: {latest_backup.backup_uid}")
        
        # Check if latest backup is available and process
        self._process_backup_chain(backupplan_uid, latest_backup)
    
    def _process_backup_chain(self, backupplan_uid: str, latest_backup: BackupObject):
        """
        Process backup chain starting from latest backup.
        
        Implements the discovery logic per the architecture.
        """
        # Get all backups sorted by timestamp (latest first)
        all_backups = self.get_all_backups_for_backupplan_sorted(backupplan_uid)
        
        # Process from latest to oldest
        for backup in all_backups:
            # Step a: Check if backup is available and has ScanInstance
            if not self._is_backup_available(backup):
                self.logger.debug(f"    Backup {backup.backup_uid} is not available, skipping")
                continue
            
            # Check if ScanInstance already exists
            if self._has_scaninstance(backupplan_uid, backup.backup_uid):
                self.logger.info(
                    f"    ScanInstance exists for backup {backup.backup_uid}, "
                    f"discovery complete for this backupplan"
                )
                return
            
            # Step b: Read backupplan.json to get scanConfig
            scan_config = self._read_scan_config(backupplan_uid, backup)
            
            if not scan_config or not scan_config.enabled:
                self.logger.info(
                    f"    Scanning not enabled for backupplan {backupplan_uid} or the backupplan is a child of ClusterBackupPlan, "
                    f"discovery complete"
                )
                return
            
            # Handle scenarios based on scanOldBackups flag
            if backup == latest_backup and scan_config.scan_old_backups:
                # Scenario 2: Process all unprocessed backups
                self.logger.info(
                    f"    scanOldBackups=true, processing all unprocessed backups"
                )
                self._process_all_unprocessed_backups(backupplan_uid, all_backups)
                return
            else:
                # Scenario 1: Process this backup and continue to older backups
                self.logger.info(f"    Queueing backup {backup.backup_uid} for ScanInstance creation")
                self._queue_backup_for_creation(backupplan_uid, backup)
                
                # Continue to previous backup
                # Will stop when: scanEnabled=false, scanConfig missing, or ScanInstance exists
                continue
    
    def _process_all_unprocessed_backups(
        self,
        backupplan_uid: str,
        all_backups: List[BackupObject]
    ):
        """
        Process all unprocessed backups for a backupplan (scanOldBackups=true scenario).
        """
        queued_count = 0
        
        for backup in all_backups:
            # Check if available
            if not self._is_backup_available(backup):
                continue
            
            # Check if ScanInstance exists
            if self._has_scaninstance(backupplan_uid, backup.backup_uid):
                continue
            
            # Queue for creation
            self._queue_backup_for_creation(backupplan_uid, backup)
            queued_count += 1
        
        self.logger.info(f"    Queued {queued_count} backups for ScanInstance creation")
    
    def _is_backup_available(self, backup: BackupObject) -> bool:
        """Check if backup status is Available"""
        # If status already cached, use it
        if backup.status:
            return backup.status.lower() == 'available'
        
        # Otherwise, read from file
        # Note: For S3 mounted via s3fuse, files appear as .json even though
        # they're stored as .json.manifest.<hex> in the bucket
        try:
            backup_json_path = os.path.join(TRILIODATA_MOUNT_PATH, backup.json_path)
            
            with open(backup_json_path, 'r') as f:
                import json
                metadata = json.load(f)
            
            status = metadata.get('status', {}).get('status', '').lower()
            backup.status = status
            
            return status == 'available'
            
        except Exception as e:
            self.logger.warning(
                f"Failed to read backup status for {backup.backup_uid}: {str(e)}"
            )
            return False
    
    def _has_scaninstance(self, backupplan_uid: str, backup_uid: str) -> bool:
        """Check if ScanInstance exists for this backup"""
        return (
            backupplan_uid in self.scaninstance_map and
            backup_uid in self.scaninstance_map.get(backupplan_uid, {})
        )
    
    def _queue_backup_for_creation(self, backupplan_uid: str, backup: BackupObject):
        """
        Queue a backup for ScanInstance creation.
        
        Note: Child backupplans (owned by ClusterBackupPlan) are filtered in
        _read_scan_config() method. This is more efficient than checking each
        backup individually.
        """
        backup_path = os.path.join(backupplan_uid, backup.backup_uid)
        
        message = CreationMessage(
            backupplan_uid=backupplan_uid,
            backup_uid=backup.backup_uid,
            backup_path=backup_path,
            backup_type=backup.type
        )
        
        self.worker_pool.creation_queue.put(message)
    
    # ============= Helper Methods =============
    
    def get_latest_backup_for_backupplan(self, backupplan_uid: str) -> Optional[BackupObject]:
        """
        Get the latest backup for a backupplan.
        
        Returns backup with most recent last_updated_timestamp.
        """
        backups = self.storage_state.get_backups(backupplan_uid)
        
        if not backups:
            return None
        
        # Sort by timestamp (most recent first)
        sorted_backups = sorted(
            backups,
            key=lambda b: b.last_updated_timestamp,
            reverse=True
        )
        
        return sorted_backups[0]
    
    def get_all_backups_for_backupplan_sorted(self, backupplan_uid: str) -> List[BackupObject]:
        """
        Get all backups for a backupplan sorted by timestamp (latest first).
        """
        backups = self.storage_state.get_backups(backupplan_uid)
        
        # Sort by timestamp (most recent first)
        return sorted(
            backups,
            key=lambda b: b.last_updated_timestamp,
            reverse=True
        )
    
    def shutdown(self):
        """Shutdown handler and cleanup resources"""
        self.logger.info("Shutting down handler...")
        self.worker_pool.stop_all_workers()
        self.logger.info("✓ Handler shutdown complete")


