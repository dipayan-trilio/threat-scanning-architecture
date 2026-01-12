"""
Base handler for backup target cleanup operations.
Provides abstract interface and common functionality for TVK/TVO handlers.
"""

import os
import sys
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta

# Add parent directory to path to import mount_utility
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from mount_utility.mount_by_target_crd import triliodata_crd_parser
from mount_utility import utilities
from mount_utility import constants
from mount_utility import logger

logging = logger.logger

# Standard mount point for all targets
TRILIODATA_MOUNT_PATH = '/triliodata'


@dataclass
class CleanupResult:
    """Result of cleanup operation."""
    success: bool = False
    deleted_count: int = 0
    deleted_scan_instances: List[str] = field(default_factory=list)
    failed_deletions: List[str] = field(default_factory=list)
    error: Optional[str] = None
    backupplan_count: int = 0
    total_backups_found: int = 0


@dataclass
class DiscoveryResult:
    """Result of discovery operation."""
    success: bool = False
    new_backups_found: int = 0
    scan_instances_created: int = 0
    backupplans_processed: List[str] = field(default_factory=list)
    failed_creations: List[str] = field(default_factory=list)
    error: Optional[str] = None


class BaseBackupTargetHandler(ABC):
    """
    Abstract base class for handling backup target cleanup operations.
    Leverages existing datastore-attacher utilities for credential parsing and mounting.
    
    Implements template method pattern where subclasses provide specific implementations
    for TVK/TVO backup structure parsing.
    """
    
    def __init__(self, target_cr: Dict, k8s_client, logger_instance):
        """
        Initialize handler with Target CR.
        
        Args:
            target_cr: Target custom resource dictionary
            k8s_client: K8s client for ScanInstance operations
            logger_instance: Logger instance
        """
        self.target_cr = target_cr
        self.target_uid = target_cr['metadata']['uid']
        self.target_name = target_cr['metadata']['name']
        self.k8s_client = k8s_client
        self.logger = logger_instance
        self.backup_type = None
        
        # Parse target using existing parser
        self.parsed_target = triliodata_crd_parser.parse_cr_response(target_cr)
        self.target_type = self.parsed_target['storageType']
        
        self.logger.info(
            f"Initialized handler for target {self.target_name} "
            f"(type: {self.target_type}, uid: {self.target_uid})"
        )
    
    # ============= ABSTRACT METHODS (Subclass must implement) =============
    
    @abstractmethod
    def detect_backup_type(self, sample_structure: Dict) -> str:
        """
        Detect backup type (TVK/TVO) based on sample directory structure.
        
        Args:
            sample_structure: Dict containing sample files/dirs from target
            
        Returns:
            'TVK' or 'TVO' or 'UNKNOWN'
        """
        pass
    
    @abstractmethod
    def parse_directory_structure(self, target_data: Dict) -> Dict[str, Set[str]]:
        """
        Parse target directory structure into backupplan -> backups mapping.
        This is the ONLY method that reads from target (S3/NFS).
        Must be optimized to minimize API calls.
        
        Args:
            target_data: Raw data from S3 list or NFS find command
            
        Returns:
            {
                'backupplan-uid-1': {'backup-uid-1', 'backup-uid-2', ...},
                'backupplan-uid-2': {'backup-uid-3', 'backup-uid-4', ...},
            }
        """
        pass
    
    @abstractmethod
    def get_backups_with_new_activity(
        self, 
        since_time: datetime,
        s3_client=None
    ):
        """
        Discover all backups with activity since the given time.
        
        For S3: Use S3 API (boto3) to check LastModified timestamps.
        For NFS: Use find command on mounted filesystem.
        
        Args:
            since_time: Only return backups modified after this time
            s3_client: Pre-configured S3 client (for S3 targets only)
            
        Returns:
            DiscoveredBackups object containing all discovered backups
        """
        pass
    
    @abstractmethod
    def filter_available_backups(
        self,
        discovered_backups
    ):
        """
        Filter discovered backups to only include those in Available state.
        
        Reads metadata files and verifies status.
        
        Args:
            discovered_backups: DiscoveredBackups object with all discovered backups
            
        Returns:
            DiscoveredBackups object containing only available backups
        """
        pass
    
    @abstractmethod
    def get_latest_backup_per_plan(
        self,
        available_backups
    ) -> Dict:
        """
        From the available backups, get the latest backup for each backupplan.
        
        Args:
            available_backups: DiscoveredBackups object with available backups
            
        Returns:
            Dictionary mapping backupplan_uid -> BackupInfo
        """
        pass
    
    @abstractmethod
    def get_latest_backup_for_backupplan(
        self,
        backupplan_uid: str
    ) -> Optional[str]:
        """
        Get the latest backup UID for a given backupplan.
        
        DEPRECATED: Use get_latest_backup_per_plan() instead.
        This method is kept for backward compatibility.
        
        Args:
            backupplan_uid: BackupPlan UID to get latest backup for
            
        Returns:
            Latest backup UID or None if no backups found
        """
        pass
    
    # ============= CONCRETE METHODS (Shared implementation) =============
    
    def is_early_mount_needed(self) -> bool:
        """
        Determine if target needs to be mounted before detection.
        
        Returns:
            True for NFS (need to mount to probe structure)
            False for S3 (can use API without mounting)
        """
        return self.target_type.lower() == constants.NFS
    
    def get_target_data(self) -> Tuple[Dict, Optional[str]]:
        """
        Get directory structure from target with minimal operations.
        Uses existing utilities for mounting/S3 access.
        
        Returns:
            (target_data_dict, mount_path_or_none)
            
        For S3:
            - Use boto3 list_objects_v2 with delimiter
            - Return (list_result, None)
            
        For NFS:
            - Mount target to /triliodata (will be reused for discovery)
            - Run: find <mount> -mindepth 2 -maxdepth 2 -type d
            - Return (find_result, mount_path)
        """
        if self.target_type.lower() == constants.OBJECT_STORE:
            # S3 target - no mount needed for cleanup (uses API)
            s3_data = self._list_s3_structure()
            return (s3_data, None)
        else:
            # NFS target - mount to /triliodata (will be reused for discovery)
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
            
            self.logger.info(f"Mount command: {' '.join(mount_cmd)}")
            
            try:
                result = subprocess.run(
                    mount_cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )
                if result.stdout:
                    self.logger.info(f"Mount stdout: {result.stdout}")
                self.logger.info(f"Successfully mounted NFS {self.target_name} at {TRILIODATA_MOUNT_PATH}")
                nfs_data = self._list_nfs_structure(TRILIODATA_MOUNT_PATH)
                return (nfs_data, TRILIODATA_MOUNT_PATH)
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Mount failed with exit code {e.returncode}")
                self.logger.error(f"Stdout: {e.stdout}")
                self.logger.error(f"Stderr: {e.stderr}")
                raise RuntimeError(f"Failed to mount NFS target {self.target_name}: {e.stderr}")
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"Mount command timed out after 300 seconds: {str(e)}")
            except Exception as e:
                raise RuntimeError(f"Failed to mount NFS target {self.target_name}: {str(e)}")
    
    def _list_s3_structure(self) -> Dict:
        """
        Single S3 API call to get all backup structure.
        Uses boto3 with credentials from parsed_target.
        
        Returns:
            {
                'type': 's3',
                'objects': ['backupplan-uid-1/backup-uid-1/', ...],
                'bucket': 'bucket-name'
            }
        """
        import boto3
        from botocore.config import Config
        
        metadata = self.parsed_target['metaData']
        
        # Create S3 client using parsed credentials
        s3_config = Config(
            region_name=metadata.get('regionName', ''),
            signature_version='s3v4',
            max_pool_connections=int(constants.S3_MAX_POOL_CONNECTIONS)
        )
        
        # Determine SSL verification
        verify_ssl = True
        if metadata.get('skipCertVerification', False):
            verify_ssl = False
        elif os.path.exists(utilities.getSSLPath()):
            verify_ssl = utilities.getSSLPath()
        
        s3_client = boto3.client(
            's3',
            endpoint_url=metadata.get('s3EndpointUrl', ''),
            aws_access_key_id=metadata['accessKeyID'],
            aws_secret_access_key=metadata['accessKey'],
            config=s3_config,
            verify=verify_ssl
        )
        
        bucket_name = metadata['s3Bucket']
        
        # Single paginated call to list all backup directories
        all_objects = []
        paginator = s3_client.get_paginator('list_objects_v2')
        
        try:
            # List all backupplan directories (top level)
            for page in paginator.paginate(Bucket=bucket_name, Prefix='', Delimiter='/'):
                for prefix in page.get('CommonPrefixes', []):
                    backupplan_uid = prefix['Prefix'].rstrip('/')
                    
                    # Skip data segments directory (used for storing backup data, not metadata)
                    if backupplan_uid == '80bc80ff-0c51-4534-86a2-ec5e719643c2':
                        continue
                    
                    # List backup directories under this backupplan
                    for backup_page in paginator.paginate(
                        Bucket=bucket_name,
                        Prefix=f'{backupplan_uid}/',
                        Delimiter='/'
                    ):
                        for backup_prefix in backup_page.get('CommonPrefixes', []):
                            # Skip data segment subdirectories
                            if '-segments' not in backup_prefix['Prefix']:
                                all_objects.append(backup_prefix['Prefix'])
            
            self.logger.info(
                f"Listed {len(all_objects)} backup directories from S3 bucket {bucket_name}"
            )
            
            return {
                'type': 's3',
                'objects': all_objects,
                'bucket': bucket_name
            }
            
        except Exception as e:
            self.logger.error(f"Failed to list S3 structure: {str(e)}")
            raise
    
    def _list_nfs_structure(self, mount_path: str) -> Dict:
        """
        Single find command to get all backup structure.
        
        Command: find <mount> -mindepth 2 -maxdepth 2 -type d
        
        Returns:
            {
                'type': 'nfs',
                'paths': ['/mount/backupplan-uid-1/backup-uid-1', ...],
                'mount_path': '/mount/path'
            }
        """
        try:
            # Single find command to get all backup directories
            # Note: utilities.run_cmd outputs to stdout/stderr directly, so we use subprocess for this
            # to capture the output
            import subprocess
            result = subprocess.run(
                ['find', mount_path, '-mindepth', '2', '-maxdepth', '2', '-type', 'd'],
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minute timeout
            )
            
            paths = [p for p in result.stdout.strip().split('\n') if p]
            
            self.logger.info(
                f"Listed {len(paths)} backup directories from NFS mount {mount_path}"
            )
            
            return {
                'type': 'nfs',
                'paths': paths,
                'mount_path': mount_path
            }
            
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Find command timed out on {mount_path}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Find command failed: {e.stderr}")
    
    def _mount_nfs(self) -> str:
        """
        Mount NFS target using datastore-attacher's mount script.
        
        Reuses the same mount_datastores.py script that handles all mounting logic.
        For cleanup phase, we mount to /triliodata (same as discovery).
        
        Returns:
            Mount path (/triliodata)
        """
        # Get the path to mount_datastores.py
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        mount_script = os.path.join(
            script_dir, 
            'mount_utility', 
            'mount_by_target_crd', 
            'mount_datastores.py'
        )
        
        if not os.path.exists(mount_script):
            raise RuntimeError(f"Mount script not found at {mount_script}")
        
        # Create mount point
        os.makedirs(TRILIODATA_MOUNT_PATH, exist_ok=True)
        
        # Build command string for utilities.run_cmd
        mount_cmd = (
            f"python3 {mount_script} "
            f"--target-name={self.target_name} "
            f"--group=threatscanning.trilio.io"
        )
        
        try:
            self.logger.info(f"Mounting NFS target {self.target_name} to {TRILIODATA_MOUNT_PATH}")
            
            # Use utilities.run_cmd which handles logging, timeout, and error checking
            utilities.run_cmd(mount_cmd)
            
            self.logger.info(f"Successfully mounted {self.target_name} at {TRILIODATA_MOUNT_PATH}")
            return TRILIODATA_MOUNT_PATH
            
        except Exception as e:
            error_msg = f"Failed to mount NFS target {self.target_name}: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    
    def perform_cleanup(self) -> CleanupResult:
        """
        Main cleanup orchestration using template method pattern.
        This is the ONLY public method called by main.py.
        
        Implements AGGRESSIVE cleanup approach:
        - Deletes ScanInstances for non-existent backups
        - Deletes ALL ScanInstances for deleted backupplans
        
        Flow:
        1. Get target data (single S3 call or single find command)
        2. Parse directory structure into backupplan->backups map
        3. List ALL ScanInstances for this target (single K8s call)
        4. Group ScanInstances by backupplan
        5. For each backupplan:
           a. If backupplan exists in target: compare backups and delete stale
           b. If backupplan NOT in target: delete ALL ScanInstances (AGGRESSIVE)
        6. Cleanup (unmount if needed)
        
        Returns:
            CleanupResult with statistics and status
        """
        result = CleanupResult()
        mount_path = None
        
        try:
            self.logger.info(f"Starting cleanup for target: {self.target_name}")
            
            # Step 1: Get target data (optimized - single operation)
            target_data, mount_path = self.get_target_data()
            
            # Step 2: Parse into backupplan->backups map (single pass)
            backupplan_backups_map = self.parse_directory_structure(target_data)
            result.backupplan_count = len(backupplan_backups_map)
            result.total_backups_found = sum(len(b) for b in backupplan_backups_map.values())
            
            self.logger.info(
                f"Found {result.backupplan_count} backupplans "
                f"with total {result.total_backups_found} backups"
            )
            
            # Step 3: List ALL ScanInstances for this target (single K8s call)
            all_scan_instances = self.k8s_client.list_scan_instances(
                label_selector=f"target-uid={self.target_uid}"
            )
            
            self.logger.info(
                f"Found {len(all_scan_instances)} total ScanInstances for target"
            )
            
            # Step 4: Group ScanInstances by backupplan
            si_by_backupplan = defaultdict(list)
            for si in all_scan_instances:
                bp_uid = si['metadata']['labels'].get('backupplan-uid')
                if bp_uid:
                    si_by_backupplan[bp_uid].append(si)
            
            # Step 6: Process each backupplan
            for backupplan_uid, scan_instances in si_by_backupplan.items():
                
                # Check if backupplan exists in target
                if backupplan_uid in backupplan_backups_map:
                    # Backupplan exists - compare backups
                    actual_backup_uids = backupplan_backups_map[backupplan_uid]
                    
                    self.logger.debug(
                        f"Backupplan {backupplan_uid}: "
                        f"{len(actual_backup_uids)} actual backups, "
                        f"{len(scan_instances)} ScanInstances"
                    )
                    
                    # Check each ScanInstance
                    for si in scan_instances:
                        si_name = si['metadata']['name']
                        si_backup_uid = si['metadata']['labels'].get('backup-uid')
                        
                        # Delete if backup doesn't exist
                        if si_backup_uid not in actual_backup_uids:
                            self.logger.info(
                                f"STALE: ScanInstance {si_name} references "
                                f"backup {si_backup_uid} which no longer exists"
                            )
                            
                            if self.k8s_client.delete_scan_instance(si_name):
                                result.deleted_count += 1
                                result.deleted_scan_instances.append(si_name)
                            else:
                                result.failed_deletions.append(si_name)
                
                else:
                    # Backupplan NOT in target - delete ALL ScanInstances (AGGRESSIVE)
                    self.logger.info(
                        f"AGGRESSIVE: Backupplan {backupplan_uid} deleted from target, "
                        f"cleaning up {len(scan_instances)} ScanInstances"
                    )
                    
                    for si in scan_instances:
                        si_name = si['metadata']['name']
                        
                        if self.k8s_client.delete_scan_instance(si_name):
                            result.deleted_count += 1
                            result.deleted_scan_instances.append(si_name)
                        else:
                            result.failed_deletions.append(si_name)
            
            result.success = True
            self.logger.info(
                f"Cleanup completed: deleted {result.deleted_count} stale ScanInstances"
            )
            
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}", exc_info=True)
            result.success = False
            result.error = str(e)
        
        # Note: For NFS, mount_path is /triliodata and will be reused for discovery
        # For S3, mount_path is None (no mount during cleanup)
        # No unmount logic needed - mount persists for discovery phase
        
        return result
    
    def _extract_sample_structure(self, target_data: Dict) -> Dict:
        """
        Extract sample structure for backup type detection.
        
        For TVK detection, we sample one backup directory and check for tvk-meta.json.
        
        Args:
            target_data: Data from get_target_data()
            
        Returns:
            Dict with sample files for detection
        """
        if target_data['type'] == 's3':
            # Sample first backup directory and list its files
            objects = target_data.get('objects', [])
            if not objects:
                return {'objects': []}
            
            # Get first backup directory
            first_backup = objects[0].rstrip('/')
            
            # List files in this backup directory
            try:
                import boto3
                from botocore.config import Config
                
                metadata = self.parsed_target['metaData']
                s3_config = Config(
                    region_name=metadata.get('regionName', ''),
                    signature_version='s3v4',
                )
                
                verify_ssl = True
                if metadata.get('skipCertVerification', False):
                    verify_ssl = False
                elif os.path.exists(utilities.getSSLPath()):
                    verify_ssl = utilities.getSSLPath()
                
                s3_client = boto3.client(
                    's3',
                    endpoint_url=metadata.get('s3EndpointUrl', ''),
                    aws_access_key_id=metadata['accessKeyID'],
                    aws_secret_access_key=metadata['accessKey'],
                    config=s3_config,
                    verify=verify_ssl
                )
                
                bucket_name = metadata['s3Bucket']
                
                # List objects in first backup directory
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=first_backup + '/',
                    MaxKeys=100  # Only need a sample
                )
                
                sample_objects = [obj['Key'] for obj in response.get('Contents', [])]
                return {'objects': sample_objects}
                
            except Exception as e:
                self.logger.warning(f"Failed to sample S3 structure: {str(e)}")
                return {'objects': []}
        
        else:  # NFS
            # Sample first backup directory and list its files
            paths = target_data.get('paths', [])
            if not paths:
                return {'paths': []}
            
            # Get first backup directory
            first_backup = paths[0]
            
            # List files in this backup directory
            try:
                import glob
                sample_files = glob.glob(os.path.join(first_backup, '*'))
                # Convert to relative paths like S3
                sample_paths = [os.path.join(first_backup, os.path.basename(f)) for f in sample_files]
                return {'paths': sample_paths}
            except Exception as e:
                self.logger.warning(f"Failed to sample NFS structure: {str(e)}")
                return {'paths': []}
    
    # ============= DISCOVERY PHASE METHODS =============
    
    def get_last_successful_run_time(self, cronjob_name: str) -> datetime:
        """
        Get the last successful run time of the CronJob.
        
        Args:
            cronjob_name: Name of the CronJob (passed by controller)
            
        Returns:
            Last successful run time, or N hours ago if no successful run found
            (N defaults to 6, configurable via DISCOVERY_LOOKBACK_HOURS env var)
        """
        # Get lookback hours from environment variable (default: 6 hours)
        lookback_hours = int(os.getenv('DISCOVERY_LOOKBACK_HOURS', '6'))
        
        try:
            cronjob = self.k8s_client.get_cronjob(cronjob_name)
            last_successful_time = cronjob.get('status', {}).get('lastSuccessfulTime')
            
            if last_successful_time:
                # Parse Kubernetes timestamp (ISO 8601 format)
                from dateutil import parser
                return parser.isoparse(last_successful_time)
            else:
                # No successful run yet, default to N hours ago
                self.logger.info(
                    f"No lastSuccessfulTime found for CronJob {cronjob_name}, "
                    f"defaulting to {lookback_hours} hours ago"
                )
                return datetime.utcnow() - timedelta(hours=lookback_hours)
                
        except Exception as e:
            self.logger.warning(
                f"Failed to get CronJob status: {str(e)}, "
                f"defaulting to {lookback_hours} hours ago"
            )
            return datetime.utcnow() - timedelta(hours=lookback_hours)
    
    def mount_target_for_discovery(self) -> str:
        """
        Mount target for discovery phase (S3 only).
        
        For NFS: Already mounted during cleanup phase, so this is a no-op.
        For S3: Mount to /triliodata using datastore-attacher's mount script.
        
        Returns:
            Mount path (/triliodata)
        """
        if self.target_type.lower() != constants.OBJECT_STORE:
            # NFS already mounted during cleanup phase
            self.logger.info(f"NFS target already mounted at {TRILIODATA_MOUNT_PATH}, reusing for discovery")
            return TRILIODATA_MOUNT_PATH
        
        # S3 target - mount now
        self.logger.info(f"Mounting S3 target {self.target_name} to {TRILIODATA_MOUNT_PATH}")
        
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
        
        self.logger.info(f"Mount command: {' '.join(mount_cmd)}")
        
        try:
            result = subprocess.run(
                mount_cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            if result.stdout:
                self.logger.info(f"Mount stdout: {result.stdout}")
            self.logger.info(f"Successfully mounted S3 {self.target_name} at {TRILIODATA_MOUNT_PATH}")
            return TRILIODATA_MOUNT_PATH
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Mount failed with exit code {e.returncode}")
            self.logger.error(f"Stdout: {e.stdout}")
            self.logger.error(f"Stderr: {e.stderr}")
            raise RuntimeError(f"Failed to mount S3 target {self.target_name}: {e.stderr}")
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"Mount command timed out after 300 seconds: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Failed to mount S3 target {self.target_name}: {str(e)}")
    
    def _get_s3_client(self):
        """
        Create and return a configured S3 client using parsed credentials.
        
        Returns:
            boto3 S3 client
        """
        import boto3
        from botocore.config import Config
        
        metadata = self.parsed_target['metaData']
        
        s3_config = Config(
            region_name=metadata.get('regionName', ''),
            signature_version='s3v4',
            max_pool_connections=int(constants.S3_MAX_POOL_CONNECTIONS)
        )
        
        verify_ssl = True
        if metadata.get('skipCertVerification', False):
            verify_ssl = False
        elif os.path.exists(utilities.getSSLPath()):
            verify_ssl = utilities.getSSLPath()
        
        return boto3.client(
            's3',
            endpoint_url=metadata.get('s3EndpointUrl', ''),
            aws_access_key_id=metadata['accessKeyID'],
            aws_secret_access_key=metadata['accessKey'],
            config=s3_config,
            verify=verify_ssl
        )
    
    def perform_discovery(self, cronjob_name: str) -> DiscoveryResult:
        """
        Main discovery orchestration.
        
        Flow:
        1. Get last successful run time from CronJob status (or default to 6 hours ago)
        2. For S3: Use S3 API to detect backupplans with new backups
           For NFS: Already mounted during cleanup, use find to detect new backups
        3. For S3: Mount target to /triliodata (only if new backups found)
        4. For each backupplan with new backups:
           a. Get latest backup UID
           b. Create ScanInstance CR
        
        Note: No unmount logic needed - mount persists until pod terminates
        
        Args:
            cronjob_name: Name of the CronJob (passed by controller)
            
        Returns:
            DiscoveryResult with statistics and status
        """
        result = DiscoveryResult()
        
        try:
            self.logger.info(f"Starting discovery for target: {self.target_name}")
            
            # Step 1: Get last successful run time
            since_time = self.get_last_successful_run_time(cronjob_name)
            self.logger.info(f"Looking for backups created since: {since_time}")
            
            # Step 2: Discover backups with new activity
            if self.target_type.lower() == constants.OBJECT_STORE:
                # S3: Use API first (faster than s3fuse)
                s3_client = self._get_s3_client()
                discovered_backups = self.get_backups_with_new_activity(
                    since_time, s3_client
                )
                
                # Only mount if new backups found
                if discovered_backups.total_backups > 0:
                    self.logger.info(
                        f"Found {discovered_backups.total_backups} backups in "
                        f"{discovered_backups.total_backupplans} backupplans, mounting S3 target"
                    )
                    self.mount_target_for_discovery()
                else:
                    self.logger.info("No new backups found, skipping mount")
                    result.success = True
                    return result
            else:
                # NFS: Already mounted during cleanup phase, reuse it
                self.logger.info(f"Using existing NFS mount at {TRILIODATA_MOUNT_PATH} for discovery")
                discovered_backups = self.get_backups_with_new_activity(
                    since_time, None
                )
            
            result.new_backups_found = discovered_backups.total_backups
            
            # Step 3: Filter to only available backups
            available_backups = self.filter_available_backups(discovered_backups)
            
            if available_backups.total_backups == 0:
                self.logger.info("No available backups found")
                result.success = True
                return result
            
            # Step 4: Get latest backup per backupplan
            latest_backups = self.get_latest_backup_per_plan(available_backups)
            
            if not latest_backups:
                self.logger.info("No latest backups to process")
                result.success = True
                return result
            
            # Step 5: Process each backupplan's latest backup
            self.logger.info(f"Processing {len(latest_backups)} backupplans for ScanInstance creation...")
            
            for idx, (backupplan_uid, backup_info) in enumerate(latest_backups.items(), 1):
                try:
                    self.logger.info("")
                    self.logger.info(
                        f"Processing backupplan {idx}/{len(latest_backups)}: {backupplan_uid}"
                    )
                    self.logger.info(
                        f"  Latest backup: {backup_info.backup_uid} "
                        f"(type: {backup_info.metadata_type.value})"
                    )
                    
                    # TODO: Create ScanInstance CR
                    # This will be implemented later with event-based architecture
                    # For now, just log
                    self.logger.info(
                        f"  → Would create ScanInstance for backup {backup_info.backup_uid}"
                    )
                    
                    result.scan_instances_created += 1
                    result.backupplans_processed.append(backupplan_uid)
                    
                except Exception as e:
                    self.logger.error(
                        f"  ✗ Failed to process backupplan {backupplan_uid}: {str(e)}"
                    )
                    result.failed_creations.append(backupplan_uid)
            
            result.success = True
            self.logger.info(
                f"Discovery completed: processed {len(result.backupplans_processed)} backupplans"
            )
            
        except Exception as e:
            self.logger.error(f"Discovery failed: {str(e)}", exc_info=True)
            result.success = False
            result.error = str(e)
        
        # Note: No unmount logic needed
        # For NFS: Mount persists from cleanup phase
        # For S3: Mount persists until pod terminates
        # This is intentional - no need to unmount
        
        return result

