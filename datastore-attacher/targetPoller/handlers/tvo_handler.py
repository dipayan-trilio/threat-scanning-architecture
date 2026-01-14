"""
TVO (TrilioVault for OpenStack) handler for targetPoller.

Stub implementation - TVO support will be added later.
"""

from typing import Dict

from .base_handler import BaseTargetHandler
from targetPoller.models.storage_state import StorageState


class TVOTargetHandler(BaseTargetHandler):
    """
    TVO-specific implementation of target handler.
    
    NOTE: This is a stub implementation. TVO support is not yet implemented.
    """
    
    def __init__(self, target_cr: Dict, k8s_client, logger_instance):
        """Initialize TVO handler"""
        super().__init__(target_cr, k8s_client, logger_instance)
        self.backup_type = 'TVO'
        self.logger.warning("TVO handler is not fully implemented")
    
    def detect_backup_type(self) -> str:
        """
        Detect if this is a TVO backup target.
        
        NOTE: Not yet implemented.
        
        Returns:
            'UNKNOWN' - TVO detection not implemented
        """
        self.logger.warning("TVO detection is not yet implemented")
        return 'UNKNOWN'
    
    def populate_storage_state(self) -> StorageState:
        """
        Populate storage state with all backups from TVO target.
        
        NOTE: Not yet implemented.
        
        Returns:
            Empty StorageState
        """
        self.logger.warning("TVO storage state population is not yet implemented")
        return StorageState()
    
    def refresh_storage_state(self):
        """
        Refresh storage state with latest data.
        
        NOTE: Not yet implemented.
        """
        self.logger.warning("TVO storage state refresh is not yet implemented")
        self.storage_state = StorageState()
    
    def _read_scan_config(self, backupplan_uid: str, backup_uid: str):
        """
        Read scan config from TVO-specific location.
        
        NOTE: Not yet implemented.
        """
        self.logger.warning("TVO scan config reading is not yet implemented")
        return None


