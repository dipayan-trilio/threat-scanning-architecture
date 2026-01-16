"""
TVO (TrilioVault for OpenStack) handler for targetPoller.

Stub implementation - TVO support will be added later.
"""

import os
import sys
from typing import Dict

# Add parent directory to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from .base_handler import BaseTargetHandler
from targetPoller.models.storage_state import StorageState
from shared.backup_detection import TVOBackupDetector


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
        # Initialize shared detector
        self.detector = TVOBackupDetector(self.parsed_target, self.target_type, self.logger)
    
    def detect_backup_type(self) -> str:
        """
        Detect if this is a TVO backup target.
        
        Uses shared TVOBackupDetector for detection logic.
        
        NOTE: Not yet implemented.
        
        Returns:
            'UNKNOWN' - TVO detection not implemented
        """
        self.logger.warning("TVO detection is not yet implemented")
        # Use shared detector
        return self.detector.detect()
    
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
    
    def _read_scan_config(self, backupplan_uid: str, backup):
        """
        Read scan config from TVO-specific location.
        
        NOTE: Not yet implemented.
        """
        self.logger.warning("TVO scan config reading is not yet implemented")
        return None


