"""
TVK (TrilioVault for Kubernetes) handler for targetPoller.

Implements TVK-specific logic for storage state population and backup detection.
"""

import os
import re
import subprocess
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import sys

# Add parent directory to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from .base_handler import BaseTargetHandler, TRILIODATA_MOUNT_PATH, IGNORE_RECENT_UPDATES_MINUTES
from targetPoller.models.storage_state import StorageState, BackupObject, BackupType
from shared.backup_detection import TVKBackupDetector

from mount_utility import constants


class TVKTargetHandler(BaseTargetHandler):
    """
    TVK-specific implementation of target handler.
    
    TVK backup structure:
        <backupplan-uid>/
          └── <backup-uid>/
              ├── tvk-meta.json (or tvk-meta.json.manifest.<hex> for S3)
              ├── backup.json (or backup.json.manifest.<hex> for S3)
              ├── cluster-backup.json
              ├── snapshot.json
              ├── cluster-snapshot.json
              └── ... other files ...
    """
    
    def __init__(self, target_cr: Dict, k8s_client, logger_instance):
        """Initialize TVK handler"""
        super().__init__(target_cr, k8s_client, logger_instance)
        self.backup_type = 'TVK'
        self.is_mounted = False
        # Initialize shared detector
        self.detector = TVKBackupDetector(self.parsed_target, self.target_type, self.logger)
    
    def detect_backup_type(self) -> str:
        """
        Detect if this is a TVK backup target.
        
        Uses shared TVKBackupDetector for detection logic.
        
        Returns:
            'TVK' if TVK markers found, 'UNKNOWN' otherwise
        """
        self.logger.info("Detecting backup type...")
        print(f"Target type: {self.target_type}")
        
        # For NFS, mount first if not already mounted
        mount_path = None
        if self.target_type != constants.OBJECT_STORE:
            if not self.is_mounted:
                mount_path = self._mount_target()
            else:
                mount_path = TRILIODATA_MOUNT_PATH
        
        # Use shared detector
        return self.detector.detect(mount_path)
    
    def populate_storage_state(self) -> StorageState:
        """
        Populate storage state with all backups from TVK target.
        
        Scans target for all backupplans and backups, extracting:
        - backup_uid
        - json_path (to backup.json/cluster-backup.json/etc.)
        - last_updated_timestamp
        - type (backup/cluster-backup/snapshot/cluster-snapshot)
        
        Filters out backups updated within last 5 minutes.
        """
        storage_state = StorageState()
        
        self.logger.info("Populating storage state from target...")
        
        if self.target_type == constants.OBJECT_STORE:
            self._populate_from_s3(storage_state)
        else:
            self._populate_from_nfs(storage_state)
        
        return storage_state
    
    def _populate_from_s3(self, storage_state: StorageState):
        """
        Populate storage state from S3 target.
        
        Note: S3 uses s3fuse which creates manifest files (.json.manifest.<hex>)
        and segment directories (-segments). These are S3-specific and not used in NFS.
        Also filters out the data segments directory (80bc80ff-...).
        """
        import boto3
        from botocore.config import Config
        
        metadata = self.parsed_target['metaData']
        bucket_name = metadata['s3Bucket']
        
        # Create S3 client
        s3_config = Config(
            region_name=metadata.get('regionName', ''),
            signature_version='s3v4'
        )
        
        verify_ssl = True
        if metadata.get('skipCertVerification', False):
            verify_ssl = False
        
        s3_client = boto3.client(
            's3',
            endpoint_url=metadata.get('s3EndpointUrl'),
            aws_access_key_id=metadata.get('accessKeyID'),
            aws_secret_access_key=metadata.get('accessKey'),
            config=s3_config,
            verify=verify_ssl
        )
        
        # Pattern for backup metadata files (S3 s3fuse format)
        metadata_pattern = re.compile(
            r'^(.*?)/(backup|cluster-backup|snapshot|cluster-snapshot)\.json\.manifest\.([0-9a-f]{8})$'
        )
        
        cutoff_time = datetime.utcnow() - timedelta(minutes=IGNORE_RECENT_UPDATES_MINUTES)
        
        self.logger.info(f"Scanning S3 bucket '{bucket_name}' for backups...")
        
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            
            total_count = 0
            filtered_count = 0
            
            for page in paginator.paginate(Bucket=bucket_name, Prefix=''):
                for obj in page.get('Contents', []):
                    obj_key = obj['Key']
                    last_modified = obj['LastModified'].replace(tzinfo=None)
                    
                    # Skip data segments directory
                    if obj_key.startswith('80bc80ff-0c51-4534-86a2-ec5e719643c2/'):
                        continue
                    
                    # Check if this is a backup metadata file
                    match = metadata_pattern.match(obj_key)
                    if not match:
                        continue
                    
                    total_count += 1
                    
                    # Filter out recent updates
                    if last_modified >= cutoff_time:
                        filtered_count += 1
                        self.logger.debug(
                            f"Ignoring recent backup: {obj_key} "
                            f"(updated {last_modified})"
                        )
                        continue
                    
                    # Extract components
                    path_prefix = match.group(1)  # backupplan-uid/backup-uid
                    metadata_type_str = match.group(2)  # backup, cluster-backup, etc.
                    
                    parts = path_prefix.split('/')
                    if len(parts) != 2:
                        continue
                    
                    backupplan_uid, backup_uid = parts
                    
                    # Skip segment directories
                    if '-segments' in backupplan_uid or '-segments' in backup_uid:
                        continue
                    
                    # Create BackupObject
                    try:
                        backup_type = BackupType(metadata_type_str)
                    except ValueError:
                        self.logger.warning(f"Unknown backup type: {metadata_type_str}")
                        continue
                    
                    # Skip child namespace backups that belong to a cluster-backup
                    # For S3, we can't easily read the file content here, so we'll rely on
                    # the prescan job to handle cluster-backup children properly.
                    # The controller will only create ScanInstances for top-level backups/cluster-backups
                    # Note: Child backups will be skipped during prescan if they have ClusterBackup owner
                    
                    # For S3, store path without manifest suffix for easier file reading
                    # When mounted via s3fuse, the file will have the manifest suffix
                    # but we'll search for it dynamically when reading
                    json_path_without_manifest = f"{backupplan_uid}/{backup_uid}/{metadata_type_str}.json"
                    
                    backup_obj = BackupObject(
                        backup_uid=backup_uid,
                        json_path=json_path_without_manifest,
                        last_updated_timestamp=last_modified,
                        type=backup_type
                    )
                    
                    storage_state.add_backup(backupplan_uid, backup_obj)
            
            self.logger.info(
                f"S3 scan complete: found {total_count} backups, "
                f"filtered {filtered_count} recent, "
                f"added {storage_state.total_backups} to storage state"
            )
            
        except Exception as e:
            self.logger.error(f"Error populating from S3: {str(e)}", exc_info=True)
            raise
    
    def _populate_from_nfs(self, storage_state: StorageState):
        """
        Populate storage state from NFS target.
        
        Note: NFS uses plain JSON files (backup.json, cluster-backup.json, etc.)
        No manifest files or segment directories - those are S3/s3fuse specific.
        """
        # Ensure target is mounted
        if not self.is_mounted:
            self._mount_target()
        
        cutoff_time = datetime.utcnow() - timedelta(minutes=IGNORE_RECENT_UPDATES_MINUTES)
        
        self.logger.info(f"Scanning NFS mount '{TRILIODATA_MOUNT_PATH}' for backups...")
        
        try:
            # Find all backup metadata files
            # Search for backup.json, cluster-backup.json, snapshot.json, cluster-snapshot.json
            result = subprocess.run(
                [
                    'find', TRILIODATA_MOUNT_PATH,
                    '-mindepth', '3', '-maxdepth', '3',
                    '-type', 'f',
                    '(',
                    '-name', 'backup.json',
                    '-o', '-name', 'cluster-backup.json',
                    '-o', '-name', 'snapshot.json',
                    '-o', '-name', 'cluster-snapshot.json',
                    ')'
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=300
            )
            
            metadata_files = [f for f in result.stdout.strip().split('\n') if f]
            
            self.logger.info(f"Found {len(metadata_files)} metadata files")
            
            total_count = 0
            filtered_count = 0
            
            for metadata_file in metadata_files:
                # Get file modification time
                try:
                    file_stat = os.stat(metadata_file)
                    last_modified = datetime.fromtimestamp(file_stat.st_mtime)
                except Exception as e:
                    self.logger.warning(f"Failed to stat {metadata_file}: {str(e)}")
                    continue
                
                total_count += 1
                
                # Filter out recent updates
                if last_modified >= cutoff_time:
                    filtered_count += 1
                    continue
                
                # Parse path to extract backupplan_uid and backup_uid
                # Format: /triliodata/backupplan-uid/backup-uid/backup.json
                parts = metadata_file.replace(TRILIODATA_MOUNT_PATH + '/', '').split('/')
                
                if len(parts) != 3:
                    continue
                
                backupplan_uid = parts[0]
                backup_uid = parts[1]
                filename = parts[2]
                
                # Determine backup type
                metadata_type_str = filename.replace('.json', '')
                try:
                    backup_type = BackupType(metadata_type_str)
                except ValueError:
                    continue
                
                # Note: Child backupplans (owned by ClusterBackupPlan) are filtered
                # in _read_scan_config() method which reads backupplan.json
                # and checks ownerReferences. This is more efficient than checking
                # every backup individually.
                
                # Create relative json_path (relative to mount point)
                json_path = f"{backupplan_uid}/{backup_uid}/{filename}"
                
                backup_obj = BackupObject(
                    backup_uid=backup_uid,
                    json_path=json_path,
                    last_updated_timestamp=last_modified,
                    type=backup_type
                )
                
                storage_state.add_backup(backupplan_uid, backup_obj)
            
            self.logger.info(
                f"NFS scan complete: found {total_count} backups, "
                f"filtered {filtered_count} recent, "
                f"added {storage_state.total_backups} to storage state"
            )
            
        except Exception as e:
            self.logger.error(f"Error populating from NFS: {str(e)}", exc_info=True)
            raise
    
    def refresh_storage_state(self):
        """
        Refresh storage state with latest data.
        
        Re-scans the target and updates the storage state.
        """
        self.logger.info("Refreshing storage state...")
        self.storage_state = self.populate_storage_state()
        self.logger.info("✓ Storage state refreshed")
    
    def _read_scan_config(self, backupplan_uid: str, backup: BackupObject):
        """
        Read scanConfig from backupplan.json or cluster-backupplan.json (TVK format).
        
        First checks if the backupplan is a child of ClusterBackupPlan by reading
        ownerReferences. If yes, returns None to skip this entire backupplan since
        all backups under it are children of a cluster-backup.
        """
        import json
        from targetPoller.models.storage_state import ScanConfig, BackupType
        
        # Determine which backupplan file to read based on backup type
        if backup.type in [BackupType.CLUSTER_BACKUP, BackupType.CLUSTER_SNAPSHOT]:
            backupplan_file = 'cluster-backupplan.json'
        else:  # BACKUP or SNAPSHOT
            backupplan_file = 'backupplan.json'
        
        try:
            backupplan_json_path = os.path.join(
                TRILIODATA_MOUNT_PATH,
                backupplan_uid,
                backup.backup_uid,
                backupplan_file
            )
            
            with open(backupplan_json_path, 'r') as f:
                backupplan_data = json.load(f)
            
            # Check if this backupplan is a child of ClusterBackupPlan
            owner_refs = backupplan_data.get('metadata', {}).get('ownerReferences', [])
            is_child_of_cluster = any(
                owner.get('kind') == 'ClusterBackupPlan' 
                for owner in owner_refs
            )
            
            if is_child_of_cluster:
                cluster_plan_name = next(
                    (owner.get('name') for owner in owner_refs 
                     if owner.get('kind') == 'ClusterBackupPlan'),
                    'unknown'
                )
                self.logger.info(
                    f"  BackupPlan {backupplan_uid} is child of ClusterBackupPlan '{cluster_plan_name}', "
                    f"skipping entire backupplan (all backups will be handled via cluster-backup parent)"
                )
                return None
            
            # Not a child backupplan - proceed with reading scanConfig
            scan_config_dict = backupplan_data.get('spec', {}).get('scanConfig')
            
            return ScanConfig.from_dict(scan_config_dict)
            
        except FileNotFoundError:
            self.logger.warning(
                f"{backupplan_file} not found for {backupplan_uid}/{backup.backup_uid}"
            )
            return None
        except Exception as e:
            self.logger.warning(
                f"Failed to read scanConfig from {backupplan_file} for {backupplan_uid}: {str(e)}"
            )
            return None
    
    def _mount_target(self) -> str:
        """
        Mount NFS target to /triliodata.
        
        Returns:
            Mount path
        """
        if self.is_mounted:
            return TRILIODATA_MOUNT_PATH
        
        self.logger.info(f"Mounting NFS target {self.target_name} to {TRILIODATA_MOUNT_PATH}")
        
        # Get absolute path to mount_datastores.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        mount_script = os.path.abspath(os.path.join(
            current_dir,
            '../../mount_utility/mount_by_target_crd/mount_datastores.py'
        ))
        
        mount_cmd = [
            'python3',
            mount_script,
            f'--target-name={self.target_name}',
            '--group=threatscanning.trilio.io'
        ]
        
        try:
            subprocess.run(
                mount_cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            self.logger.info(f"✓ Successfully mounted {self.target_name} at {TRILIODATA_MOUNT_PATH}")
            self.is_mounted = True
            return TRILIODATA_MOUNT_PATH
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to mount NFS target {self.target_name}: {e.stderr}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
        except subprocess.TimeoutExpired:
            error_msg = f"Mount command timed out for {self.target_name}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)


