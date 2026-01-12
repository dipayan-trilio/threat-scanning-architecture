"""
Backup type detector - detects TVK/TVO by examining backup directory structure.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from mount_utility.mount_by_target_crd import triliodata_crd_parser
from mount_utility import utilities
from mount_utility import constants


class BackupTypeDetector:
    """
    Detects backup type (TVK/TVO) by examining the backup directory structure.
    This runs before handler creation to determine which handler to use.
    """
    
    def __init__(self, target_cr: dict, logger_instance):
        """
        Initialize detector.
        
        Args:
            target_cr: Target CR dictionary
            logger_instance: Logger instance
        """
        self.target_cr = target_cr
        self.logger = logger_instance
        self.parsed_target = triliodata_crd_parser.parse_cr_response(target_cr)
        self.target_type = self.parsed_target['storageType']
        self.target_uid = target_cr['metadata']['uid']
    
    def detect(self) -> str:
        """
        Detect backup type by examining backup directory structure.
        
        Flow:
        1. Mount target (if NFS) or setup S3 client
        2. List one backup directory
        3. Check for tvk-meta.json
        4. Return 'TVK' or 'UNKNOWN'
        5. Cleanup (unmount if needed)
        
        Returns:
            'TVK' if TVK backup detected, 'UNKNOWN' otherwise
        """
        mount_path = None
        
        try:
            # Get sample backup directory
            if self.target_type.lower() == constants.OBJECT_STORE:
                # S3 - get sample without mounting
                backup_type = self._detect_s3()
            else:
                # NFS - mount and sample
                mount_path = self._mount_nfs()
                backup_type = self._detect_nfs(mount_path)
            
            return backup_type
            
        except Exception as e:
            self.logger.error(f"Failed to detect backup type: {str(e)}")
            self.logger.warning("Defaulting to UNKNOWN backup type")
            return 'UNKNOWN'
            
        finally:
            # Cleanup
            if mount_path:
                try:
                    self._unmount_nfs(mount_path)
                except Exception as e:
                    self.logger.warning(f"Failed to unmount: {str(e)}")
    
    def _detect_s3(self) -> str:
        """
        Detect backup type from S3 target.
        
        Returns:
            'TVK' or 'UNKNOWN'
        """
        import boto3
        from botocore.config import Config
        
        metadata = self.parsed_target['metaData']
        
        # Create S3 client
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
        
        try:
            # List first level (backupplans)
            paginator = s3_client.get_paginator('list_objects_v2')
            
            backups_checked = 0
            max_backups_to_check = 5  # Check up to 5 backups before giving up
            
            for page in paginator.paginate(Bucket=bucket_name, Prefix='', Delimiter='/', MaxKeys=10):
                for prefix in page.get('CommonPrefixes', []):
                    backupplan_uid = prefix['Prefix'].rstrip('/')
                    
                    # Skip data segments directory
                    if backupplan_uid == '80bc80ff-0c51-4534-86a2-ec5e719643c2':
                        continue
                    
                    # List second level (backups) under this backupplan
                    for backup_page in paginator.paginate(
                        Bucket=bucket_name,
                        Prefix=f'{backupplan_uid}/',
                        Delimiter='/',
                        MaxKeys=10
                    ):
                        for backup_prefix in backup_page.get('CommonPrefixes', []):
                            backup_path = backup_prefix['Prefix'].rstrip('/')
                            
                            # Skip segment directories
                            if '-segments' in backup_path:
                                continue
                            
                            # Check for tvk-meta.json.manifest.* (s3fuse format)
                            # S3fuse stores files as <filename>.manifest.<hex_number_in_decimal>
                            try:
                                manifest_prefix = f'{backup_path}/tvk-meta.json.manifest.'
                                response = s3_client.list_objects_v2(
                                    Bucket=bucket_name,
                                    Prefix=manifest_prefix,
                                    MaxKeys=1
                                )
                                
                                if response.get('Contents'):
                                    manifest_file = response['Contents'][0]['Key']
                                    self.logger.info(f"Found {manifest_file}, detected TVK backup")
                                    return 'TVK'
                                else:
                                    # No manifest file found, continue checking
                                    backups_checked += 1
                                    if backups_checked >= max_backups_to_check:
                                        self.logger.warning(f"Checked {backups_checked} backups, no tvk-meta.json.manifest.* found")
                                        return 'UNKNOWN'
                            except Exception as e:
                                self.logger.debug(f"Error checking manifest in {backup_path}: {str(e)}")
                                backups_checked += 1
                                if backups_checked >= max_backups_to_check:
                                    self.logger.warning(f"Checked {backups_checked} backups, error or no manifest found")
                                    return 'UNKNOWN'
                    
                    # Check first backupplan only
                    break
            
            self.logger.warning("No backupplans found or all were data segments")
            return 'UNKNOWN'
            
        except Exception as e:
            self.logger.error(f"S3 detection failed: {str(e)}")
            return 'UNKNOWN'
    
    def _detect_nfs(self, mount_path: str) -> str:
        """
        Detect backup type from NFS target.
        
        Args:
            mount_path: Path where NFS is mounted
            
        Returns:
            'TVK' or 'UNKNOWN'
        """
        import subprocess
        
        try:
            # Find first backup directory (depth 2)
            result = subprocess.run(
                ['find', mount_path, '-mindepth', '2', '-maxdepth', '2', '-type', 'd'],
                capture_output=True,
                text=True,
                check=True,
                timeout=60
            )
            
            paths = [p for p in result.stdout.strip().split('\n') if p]
            
            if not paths:
                self.logger.warning("No backup directories found")
                return 'UNKNOWN'
            
            # Check first backup directory for tvk-meta.json
            # Note: For NFS, file is stored directly as tvk-meta.json (not manifest format)
            first_backup = paths[0]
            tvk_meta_path = os.path.join(first_backup, 'tvk-meta.json')
            
            if os.path.exists(tvk_meta_path):
                self.logger.info(f"Found tvk-meta.json at {tvk_meta_path}, detected TVK backup")
                return 'TVK'
            
            self.logger.warning(f"tvk-meta.json not found in {first_backup}")
            return 'UNKNOWN'
            
        except Exception as e:
            self.logger.error(f"NFS detection failed: {str(e)}")
            return 'UNKNOWN'
    
    def _mount_nfs(self) -> str:
        """Mount NFS target."""
        import subprocess
        
        metadata = self.parsed_target['metaData']
        nfs_export = metadata['nfsExport']
        mount_options = metadata.get('mountOptions', 'rw,hard,intr')
        
        mount_path = f'/mnt/targets/{self.target_uid}'
        os.makedirs(mount_path, exist_ok=True)
        
        mount_cmd = ['mount', '-t', 'nfs']
        if mount_options:
            mount_cmd.extend(['-o', mount_options])
        mount_cmd.extend([nfs_export, mount_path])
        
        subprocess.run(mount_cmd, check=True, capture_output=True, text=True, timeout=60)
        self.logger.debug(f"Mounted NFS {nfs_export} at {mount_path}")
        return mount_path
    
    def _unmount_nfs(self, mount_path: str):
        """Unmount NFS target."""
        import subprocess
        
        try:
            subprocess.run(['umount', mount_path], check=True, capture_output=True, text=True, timeout=30)
            os.rmdir(mount_path)
            self.logger.debug(f"Unmounted NFS from {mount_path}")
        except Exception as e:
            self.logger.warning(f"Failed to unmount {mount_path}: {str(e)}")

