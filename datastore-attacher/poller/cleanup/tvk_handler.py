"""
TVK (TrilioVault for Kubernetes) specific handler for cleanup operations.
"""

import os
import re
import json
from collections import defaultdict
from typing import Dict, Set, List, Optional
from datetime import datetime

from .base_handler import BaseBackupTargetHandler, TRILIODATA_MOUNT_PATH
from .models import BackupInfo, DiscoveredBackups, BackupMetadataType


class TVKBackupTargetHandler(BaseBackupTargetHandler):
    """
    TVK-specific implementation of backup target handler.
    
    TVK directory structure:
        <backupplan-uid>/
          └── <backup-uid>/
              ├── backup.json (or cluster-backup.json)
              ├── backupplan.json (or cluster-backupplan.json)
              ├── metadata.qcow2
              ├── tvk-meta.json
              ├── custom/
              ├── operator/
              ├── helm/
              └── ...
    """
    
    def __init__(self, target_cr: Dict, k8s_client, logger_instance):
        """Initialize TVK handler."""
        super().__init__(target_cr, k8s_client, logger_instance)
        self.backup_type = 'TVK'
    
    def detect_backup_type(self, sample_structure: Dict) -> str:
        """
        Detect if this is a TVK backup target.
        
        TVK structure: <backupplan-uid>/<backup-uid>/tvk-meta.json
        
        Detection strategy:
        - Check if tvk-meta.json exists in the expected directory structure
        - Path format: backupplan-uid/backup-uid/tvk-meta.json
        
        Args:
            sample_structure: Dict containing:
                - 'objects': List of S3 object keys, OR
                - 'paths': List of NFS file paths
            
        Returns:
            'TVK' if tvk-meta.json found in proper structure, 'UNKNOWN' otherwise
        """
        # Check S3 objects
        if 'objects' in sample_structure:
            for obj_key in sample_structure['objects']:
                # Expected format: backupplan-uid/backup-uid/tvk-meta.json
                if obj_key.endswith('tvk-meta.json'):
                    parts = obj_key.strip('/').split('/')
                    # Should have at least 3 parts: backupplan-uid, backup-uid, tvk-meta.json
                    if len(parts) >= 3 and parts[-1] == 'tvk-meta.json':
                        self.logger.info(f"Detected TVK backup (found tvk-meta.json in {obj_key})")
                        return 'TVK'
        
        # Check NFS paths
        if 'paths' in sample_structure:
            for path in sample_structure['paths']:
                # Expected format: /mount/backupplan-uid/backup-uid/tvk-meta.json
                if path.endswith('tvk-meta.json'):
                    parts = path.strip('/').split('/')
                    # Should have at least 3 parts after mount: backupplan-uid, backup-uid, tvk-meta.json
                    if len(parts) >= 3 and parts[-1] == 'tvk-meta.json':
                        self.logger.info(f"Detected TVK backup (found tvk-meta.json in {path})")
                        return 'TVK'
        
        self.logger.warning("Could not detect TVK backup type (tvk-meta.json not found)")
        return 'UNKNOWN'
    
    def parse_directory_structure(self, target_data: Dict) -> Dict[str, Set[str]]:
        """
        Parse TVK directory structure into backupplan -> backups mapping.
        
        TVK structure: <backupplan-uid>/<backup-uid>/
        
        Single pass parsing - no additional S3/NFS operations.
        
        Args:
            target_data: Data from get_target_data() containing either:
                - S3 object keys: 'backupplan-uid/backup-uid/...'
                - NFS paths: '/mount/backupplan-uid/backup-uid'
        
        Returns:
            Dict mapping backupplan UIDs to sets of backup UIDs:
            {
                'backupplan-uid-1': {'backup-uid-1', 'backup-uid-2'},
                'backupplan-uid-2': {'backup-uid-3', 'backup-uid-4'},
            }
        """
        backupplan_map = defaultdict(set)
        
        if target_data['type'] == 's3':
            # Parse S3 object keys
            # Format: 'backupplan-uid/backup-uid/...'
            for obj_key in target_data['objects']:
                parts = obj_key.strip('/').split('/')
                if len(parts) >= 2:
                    backupplan_uid = parts[0]
                    backup_uid = parts[1]
                    backupplan_map[backupplan_uid].add(backup_uid)
            
            self.logger.debug(
                f"Parsed {len(backupplan_map)} backupplans from S3 structure"
            )
        
        else:  # NFS
            # Parse file paths
            # Format: '/mount/backupplan-uid/backup-uid'
            for path in target_data['paths']:
                parts = path.strip('/').split('/')
                if len(parts) >= 2:
                    backupplan_uid = parts[-2]  # Second last component
                    backup_uid = parts[-1]      # Last component
                    backupplan_map[backupplan_uid].add(backup_uid)
            
            self.logger.debug(
                f"Parsed {len(backupplan_map)} backupplans from NFS structure"
            )
        
        return dict(backupplan_map)
    
    def get_backups_with_new_activity(
        self, 
        since_time: datetime,
        s3_client=None
    ) -> DiscoveredBackups:
        """
        Discover all backups with activity since the given time.
        
        For S3: Use S3 API (boto3) to check LastModified timestamps on backup metadata files.
        For NFS: Use find command on mounted filesystem to find metadata files.
        
        This method only discovers backups based on file modification time.
        It does NOT verify backup status - use filter_available_backups() for that.
        
        TVK structure: <backupplan-uid>/<backup-uid>/
        
        Args:
            since_time: Only return backups modified after this time
            s3_client: Pre-configured S3 client (for S3 targets only)
            
        Returns:
            DiscoveredBackups object containing all discovered backups grouped by backupplan
        """
        discovered_backups = DiscoveredBackups()
        
        if self.target_type.lower() == 'objectstore':
            # S3: Use API to check LastModified on backup metadata files
            if not s3_client:
                s3_client = self._get_s3_client()
            
            metadata = self.parsed_target['metaData']
            bucket_name = metadata['s3Bucket']
            
            # Regex to match backup/snapshot metadata files with s3fuse manifest format
            # Format: <path>/(backup|snapshot|cluster-backup|cluster-snapshot).json.manifest.<hex>
            backup_metadata_pattern = re.compile(
                r'^(.*?)/(backup|snapshot|cluster-backup|cluster-snapshot)\.json\.manifest\.([0-9a-f]{8})$'
            )
            
            try:
                self.logger.info(f"Scanning S3 bucket '{bucket_name}' for new backup metadata files...")
                paginator = s3_client.get_paginator('list_objects_v2')
                
                total_objects_checked = 0
                metadata_files_found = 0
                
                # List all objects and filter for backup metadata files
                for page in paginator.paginate(Bucket=bucket_name, Prefix=''):
                    for obj in page.get('Contents', []):
                        obj_key = obj['Key']
                        last_modified = obj['LastModified']
                        total_objects_checked += 1
                        
                        # Skip data segments directory
                        if obj_key.startswith('80bc80ff-0c51-4534-86a2-ec5e719643c2/'):
                            continue
                        
                        # Check if this is a backup metadata file
                        match = backup_metadata_pattern.match(obj_key)
                        if not match:
                            continue
                        
                        metadata_files_found += 1
                        
                        # Check if modified since the given time
                        if last_modified.replace(tzinfo=None) <= since_time:
                            continue
                        
                        # Extract path components
                        path_prefix = match.group(1)  # e.g., "backupplan-uid/backup-uid"
                        metadata_type_str = match.group(2)  # e.g., "backup", "cluster-backup", etc.
                        manifest_id = match.group(3)   # hex number
                        
                        # Parse path to get backupplan and backup UIDs
                        # Expected format: backupplan-uid/backup-uid
                        parts = path_prefix.strip('/').split('/')
                        if len(parts) < 2:
                            self.logger.debug(f"Skipping malformed path: {obj_key}")
                            continue
                        
                        backupplan_uid = parts[0]
                        backup_uid = parts[1]
                        
                        # Skip segment directories
                        if '-segments' in backupplan_uid:
                            continue
                        
                        # Convert metadata type string to enum
                        try:
                            metadata_type = BackupMetadataType(metadata_type_str)
                        except ValueError:
                            self.logger.warning(f"Unknown metadata type: {metadata_type_str}")
                            continue
                        
                        # Create BackupInfo object
                        backup_info = BackupInfo(
                            backupplan_uid=backupplan_uid,
                            backup_uid=backup_uid,
                            metadata_type=metadata_type,
                            last_modified=last_modified.replace(tzinfo=None),
                            metadata_file_path=obj_key
                        )
                        
                        discovered_backups.add_backup(backup_info)
                        self.logger.debug(
                            f"Discovered backup: {backup_uid} in backupplan {backupplan_uid} "
                            f"(type: {metadata_type.value})"
                        )
                
                self.logger.info(
                    f"S3 scan complete: checked {total_objects_checked} objects, "
                    f"found {metadata_files_found} metadata files"
                )
                self.logger.info(
                    f"Discovered {discovered_backups.total_backups} backups in "
                    f"{discovered_backups.total_backupplans} backupplans (since {since_time})"
                )
                
            except Exception as e:
                self.logger.error(f"Failed to list S3 objects for discovery: {str(e)}")
                raise
        
        else:
            # NFS: Use find command to search for specific backup metadata files
            import subprocess
            
            try:
                # Find backup metadata files modified since the given time
                # Convert datetime to find-compatible format
                time_str = since_time.strftime('%Y-%m-%d %H:%M:%S')
                
                self.logger.info(f"Scanning NFS mount '{TRILIODATA_MOUNT_PATH}' for new backup metadata files...")
                
                # Search for backup/snapshot metadata files at depth 3
                # Format: /triliodata/backupplan-uid/backup-uid/(backup|cluster-backup|snapshot|cluster-snapshot).json
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
                        ')',
                        '-newermt', time_str
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=300
                )
                
                metadata_files_found = [p for p in result.stdout.strip().split('\n') if p]
                self.logger.info(
                    f"NFS scan complete: found {len(metadata_files_found)} metadata files modified since {since_time}"
                )
                
                # Parse paths and create BackupInfo objects
                for metadata_file_path in metadata_files_found:
                    # Format: /triliodata/backupplan-uid/backup-uid/backup.json
                    parts = metadata_file_path.strip('/').split('/')
                    if len(parts) < 3:
                        self.logger.debug(f"Skipping malformed path: {metadata_file_path}")
                        continue
                    
                    backupplan_uid = parts[-3]
                    backup_uid = parts[-2]
                    metadata_type_str = parts[-1].replace('.json', '')
                    
                    # Skip segment directories
                    if '-segments' in backupplan_uid:
                        continue
                    
                    # Convert metadata type string to enum
                    try:
                        metadata_type = BackupMetadataType(metadata_type_str)
                    except ValueError:
                        self.logger.warning(f"Unknown metadata type: {metadata_type_str}")
                        continue
                    
                    # Get file modification time
                    try:
                        file_stat = os.stat(metadata_file_path)
                        last_modified = datetime.fromtimestamp(file_stat.st_mtime)
                    except Exception as e:
                        self.logger.warning(f"Failed to stat file {metadata_file_path}: {str(e)}")
                        continue
                    
                    # Create BackupInfo object
                    backup_info = BackupInfo(
                        backupplan_uid=backupplan_uid,
                        backup_uid=backup_uid,
                        metadata_type=metadata_type,
                        last_modified=last_modified,
                        metadata_file_path=metadata_file_path
                    )
                    
                    discovered_backups.add_backup(backup_info)
                    self.logger.debug(
                        f"Discovered backup: {backup_uid} in backupplan {backupplan_uid} "
                        f"(type: {metadata_type.value})"
                    )
                
                self.logger.info(
                    f"Discovered {discovered_backups.total_backups} backups in "
                    f"{discovered_backups.total_backupplans} backupplans"
                )
                
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"Find command timed out on {TRILIODATA_MOUNT_PATH}")
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Find command failed: {e.stderr}")
        
        return discovered_backups
    
    def filter_available_backups(
        self,
        discovered_backups: DiscoveredBackups
    ) -> DiscoveredBackups:
        """
        Filter discovered backups to only include those in Available state.
        
        Reads metadata files from /triliodata mount and verifies status.
        For each backup:
        1. Construct path: {TRILIODATA_MOUNT_PATH}/{backupplan_uid}/{backup_uid}/{metadata_type}.json
        2. Read and parse JSON (handles both NFS and s3fuse manifest formats)
        3. Check status.status == "Available"
        4. Keep only available backups
        
        Args:
            discovered_backups: DiscoveredBackups object with all discovered backups
            
        Returns:
            DiscoveredBackups object containing only available backups
        """
        available_backups = DiscoveredBackups()
        
        total_checked = 0
        total_available = 0
        
        self.logger.info(
            f"Filtering {discovered_backups.total_backups} discovered backups "
            f"to find available ones..."
        )
        
        for backupplan_uid, backup_list in discovered_backups.backups_by_plan.items():
            for backup_info in backup_list:
                total_checked += 1
                
                # Construct the base path for the backup
                backup_base_path = os.path.join(
                    TRILIODATA_MOUNT_PATH,
                    backup_info.backupplan_uid,
                    backup_info.backup_uid
                )
                
                # Try to find and read the metadata file
                metadata_file = None
                metadata = None
                
                # Try exact match first (NFS format)
                exact_path = os.path.join(backup_base_path, backup_info.metadata_type.filename)
                if os.path.exists(exact_path):
                    metadata_file = exact_path
                else:
                    # Try manifest format (S3 s3fuse format)
                    # Pattern: <filename>.json.manifest.<8-hex-digits>
                    try:
                        for filename in os.listdir(backup_base_path):
                            if filename.startswith(backup_info.metadata_type.filename + '.manifest.'):
                                manifest_path = os.path.join(backup_base_path, filename)
                                if os.path.isfile(manifest_path):
                                    metadata_file = manifest_path
                                    break
                    except FileNotFoundError:
                        self.logger.debug(
                            f"Backup directory not found: {backup_base_path}"
                        )
                        continue
                    except Exception as e:
                        self.logger.warning(
                            f"Error listing directory {backup_base_path}: {str(e)}"
                        )
                        continue
                
                if not metadata_file:
                    self.logger.debug(
                        f"Metadata file not found for backup {backup_info.backup_uid} "
                        f"(type: {backup_info.metadata_type.value})"
                    )
                    continue
                
                # Read and parse the metadata file
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to read metadata file {metadata_file}: {str(e)}"
                    )
                    continue
                
                # Check if backup is in Available state
                status = metadata.get('status', {})
                backup_status = status.get('status', '').lower()
                
                if backup_status == 'available':
                    total_available += 1
                    available_backups.add_backup(backup_info)
                    self.logger.debug(
                        f"✓ Backup {backup_info.backup_uid} is available "
                        f"(backupplan: {backup_info.backupplan_uid}, type: {backup_info.metadata_type.value})"
                    )
                else:
                    self.logger.debug(
                        f"✗ Skipping backup {backup_info.backup_uid} with status '{backup_status}' "
                        f"(not Available)"
                    )
        
        self.logger.info(
            f"Filtering complete: {total_available}/{total_checked} backups are available"
        )
        self.logger.info(
            f"Available backups: {available_backups.total_backups} backups in "
            f"{available_backups.total_backupplans} backupplans"
        )
        
        return available_backups
    
    def get_latest_backup_per_plan(
        self,
        available_backups: DiscoveredBackups
    ) -> Dict[str, BackupInfo]:
        """
        From the available backups, get the latest backup for each backupplan.
        
        The "latest" backup is determined by reading the creationTimestamp from
        the backup metadata file and selecting the most recent one.
        
        Args:
            available_backups: DiscoveredBackups object with available backups
            
        Returns:
            Dictionary mapping backupplan_uid -> latest BackupInfo
        """
        latest_backups = {}
        
        self.logger.info(
            f"Finding latest backup for each of {available_backups.total_backupplans} backupplans..."
        )
        
        for backupplan_uid, backup_list in available_backups.backups_by_plan.items():
            if not backup_list:
                continue
            
            # Read creation timestamps for all backups in this backupplan
            backups_with_timestamps = []
            
            for backup_info in backup_list:
                # Construct path to metadata file
                backup_base_path = os.path.join(
                    TRILIODATA_MOUNT_PATH,
                    backup_info.backupplan_uid,
                    backup_info.backup_uid
                )
                
                # Try to find the metadata file
                metadata_file = None
                exact_path = os.path.join(backup_base_path, backup_info.metadata_type.filename)
                
                if os.path.exists(exact_path):
                    metadata_file = exact_path
                else:
                    # Try manifest format
                    try:
                        for filename in os.listdir(backup_base_path):
                            if filename.startswith(backup_info.metadata_type.filename + '.manifest.'):
                                manifest_path = os.path.join(backup_base_path, filename)
                                if os.path.isfile(manifest_path):
                                    metadata_file = manifest_path
                                    break
                    except Exception:
                        continue
                
                if not metadata_file:
                    continue
                
                # Read metadata to get creationTimestamp
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                    
                    creation_timestamp = metadata.get('metadata', {}).get('creationTimestamp')
                    if creation_timestamp:
                        # Parse ISO 8601 timestamp
                        from dateutil import parser
                        creation_time = parser.isoparse(creation_timestamp)
                        backups_with_timestamps.append((backup_info, creation_time))
                except Exception as e:
                    self.logger.warning(
                        f"Failed to read creationTimestamp for backup {backup_info.backup_uid}: {str(e)}"
                    )
                    continue
            
            if not backups_with_timestamps:
                self.logger.warning(
                    f"No backups with valid creationTimestamp found for backupplan {backupplan_uid}"
                )
                continue
            
            # Sort by creation time (most recent first)
            backups_with_timestamps.sort(key=lambda x: x[1], reverse=True)
            latest_backup_info, latest_creation_time = backups_with_timestamps[0]
            
            latest_backups[backupplan_uid] = latest_backup_info
            
            self.logger.info(
                f"Latest backup for backupplan {backupplan_uid}: "
                f"{latest_backup_info.backup_uid} (created at {latest_creation_time})"
            )
        
        self.logger.info(
            f"Found latest backups for {len(latest_backups)} backupplans"
        )
        
        return latest_backups
    
    def get_latest_backup_for_backupplan(
        self,
        backupplan_uid: str
    ) -> Optional[str]:
        """
        Get the latest backup UID for a given backupplan.
        
        Reads backup metadata (backup.json or cluster-backup.json) and
        returns the backup with the most recent creationTimestamp.
        
        TVK metadata files:
        - backup.json: For namespace-scoped backups
        - cluster-backup.json: For cluster-scoped backups
        
        Args:
            backupplan_uid: BackupPlan UID to get latest backup for
            
        Returns:
            Latest backup UID or None if no backups found
        """
        backupplan_path = os.path.join(TRILIODATA_MOUNT_PATH, backupplan_uid)
        
        if not os.path.exists(backupplan_path):
            self.logger.warning(f"Backupplan path does not exist: {backupplan_path}")
            return None
        
        backups = []
        
        try:
            # List all backup directories
            for backup_uid in os.listdir(backupplan_path):
                backup_path = os.path.join(backupplan_path, backup_uid)
                
                if not os.path.isdir(backup_path):
                    continue
                
                # Try to read backup metadata
                # For S3 with s3fuse, files are stored as .json.manifest.<hex>
                # For NFS, files are stored as .json
                metadata = None
                metadata_file = None
                
                # Try different metadata file patterns
                metadata_patterns = [
                    'backup.json',
                    'cluster-backup.json',
                    'snapshot.json',
                    'cluster-snapshot.json'
                ]
                
                for pattern in metadata_patterns:
                    # First try exact match (NFS)
                    exact_path = os.path.join(backup_path, pattern)
                    if os.path.exists(exact_path):
                        metadata_file = exact_path
                        break
                    
                    # Then try manifest format (S3 with s3fuse)
                    # Pattern: <filename>.json.manifest.<8-hex-digits>
                    try:
                        for filename in os.listdir(backup_path):
                            if filename.startswith(pattern + '.manifest.'):
                                manifest_path = os.path.join(backup_path, filename)
                                if os.path.isfile(manifest_path):
                                    metadata_file = manifest_path
                                    break
                        if metadata_file:
                            break
                    except Exception:
                        continue
                
                if metadata_file:
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                    except Exception as e:
                        self.logger.debug(f"Failed to read {metadata_file}: {str(e)}")
                        continue
                
                if metadata:
                    # Extract creationTimestamp
                    creation_timestamp = metadata.get('metadata', {}).get('creationTimestamp')
                    if creation_timestamp:
                        # Parse ISO 8601 timestamp
                        from dateutil import parser
                        creation_time = parser.isoparse(creation_timestamp)
                        backups.append((backup_uid, creation_time))
            
            if not backups:
                self.logger.warning(f"No backups with metadata found for backupplan {backupplan_uid}")
                return None
            
            # Sort by creation time (most recent first)
            backups.sort(key=lambda x: x[1], reverse=True)
            latest_backup_uid = backups[0][0]
            
            self.logger.info(
                f"Latest backup for backupplan {backupplan_uid}: {latest_backup_uid} "
                f"(created at {backups[0][1]})"
            )
            
            return latest_backup_uid
            
        except Exception as e:
            self.logger.error(
                f"Failed to get latest backup for backupplan {backupplan_uid}: {str(e)}"
            )
            return None

