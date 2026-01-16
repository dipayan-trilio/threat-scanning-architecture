"""
TVO backup type detector.
"""

from typing import Optional, Dict

from .base_detector import BaseBackupDetector


class TVOBackupDetector(BaseBackupDetector):
    """
    Detector for TrilioVault for OpenStack backups.
    
    NOTE: TVO detection is not yet implemented.
    """
    
    def detect(self, mount_path: Optional[str] = None) -> str:
        """
        Detect if this is a TVO backup target.
        
        NOTE: Not yet implemented.
        
        Returns:
            'UNKNOWN' - TVO detection not implemented
        """
        self.logger.warning("TVO detection is not yet implemented")
        return 'UNKNOWN'
    
    def detect_vm_workload(self, backup_path: str) -> bool:
        """
        Detect if TVO backup contains VM workload.
        
        NOTE: Not yet implemented.
        
        Args:
            backup_path: Full path to backup directory
            
        Returns:
            False - TVO VM detection not implemented
        """
        self.logger.warning("TVO VM workload detection is not yet implemented")
        return False
    
    def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
        """
        Extract metadata from TVO backup.
        
        NOTE: Not yet implemented.
        
        Args:
            backup_path: Full path to backup directory
            backup_uid: Backup UID from path
            
        Returns:
            Empty dict - TVO metadata extraction not implemented
            
        Raises:
            NotImplementedError: TVO support not yet implemented
        """
        self.logger.error("TVO metadata extraction is not yet implemented")
        raise NotImplementedError("TVO prescan support is not yet implemented")

