"""
Base backup type detector interface.

Provides common utilities and abstract methods for metadata extraction.
Target type (TVK/TVO) is now specified via command-line argument instead of auto-detection.
VM workload detection is still performed on a per-backup basis.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict
import boto3
from botocore.config import Config

from mount_utility import constants


class BaseBackupDetector(ABC):
    """
    Abstract base class for backup metadata extraction.
    
    Provides common utilities for both NFS and S3 operations.
    """
    
    def __init__(self, parsed_target: Dict, target_type: str, logger):
        """
        Initialize detector.
        
        Args:
            parsed_target: Parsed target metadata
            target_type: Target type (NFS/ObjectStore)
            logger: Logger instance
        """
        self.parsed_target = parsed_target
        self.target_type = target_type
        self.logger = logger
    
    @abstractmethod
    def detect_vm_workload(self, backup_path: str) -> bool:
        """
        Detect if backup contains VM workload.
        
        Implementation is type-specific (TVK vs TVO).
        
        Args:
            backup_path: Full path to backup directory (already mounted)
            
        Returns:
            True if VM workload detected, False otherwise
        """
        pass
    
    @abstractmethod
    def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
        """
        Extract metadata from backup.
        
        Implementation is type-specific (TVK vs TVO).
        
        Args:
            backup_path: Full path to backup directory (already mounted)
            backup_uid: Backup UID from path
            
        Returns:
            Dict with keys:
            - instance_id: TVK/TVO instance ID
            - backupplan_uid: BackupPlan UID
            - backup_uid: Backup UID (validated)
            - is_vm_workload: True if VM workload, False otherwise
        """
        pass
    
    def _create_s3_client(self):
        """Create and return configured S3 client."""
        metadata = self.parsed_target['metaData']
        
        s3_config = Config(
            region_name=metadata.get('regionName', ''),
            signature_version='s3v4'
        )
        
        verify_ssl = not metadata.get('skipCertVerification', False)
        
        return boto3.client(
            's3',
            endpoint_url=metadata.get('s3EndpointUrl'),
            aws_access_key_id=metadata.get('accessKeyID'),
            aws_secret_access_key=metadata.get('accessKey'),
            config=s3_config,
            verify=verify_ssl
        )
    
    def _get_s3_bucket_name(self) -> str:
        """Get S3 bucket name from parsed target."""
        return self.parsed_target['metaData']['s3Bucket']

