"""
Factory for creating appropriate backup target handler (TVK/TVO).
"""

from typing import Dict

from .base_handler import BaseBackupTargetHandler
from .tvk_handler import TVKBackupTargetHandler
from .tvo_handler import TVOBackupTargetHandler


class BackupTargetHandlerFactory:
    """
    Factory to create appropriate handler based on detected backup type.
    """
    
    @staticmethod
    def create_handler(
        target_cr: Dict,
        k8s_client,
        logger_instance,
        backup_type: str
    ) -> BaseBackupTargetHandler:
        """
        Create appropriate handler for the detected backup type.
        
        Args:
            target_cr: Target custom resource dictionary
            k8s_client: K8s client for ScanInstance operations
            logger_instance: Logger instance
            backup_type: Detected backup type ('TVK', 'TVO', or 'UNKNOWN')
            
        Returns:
            Appropriate handler instance (TVK or TVO)
            
        Note:
            If backup_type is 'UNKNOWN', defaults to TVK handler.
        """
        backup_type = backup_type.upper()
        
        if backup_type == 'TVK':
            logger_instance.info("Creating TVK handler")
            return TVKBackupTargetHandler(target_cr, k8s_client, logger_instance)
        
        elif backup_type == 'TVO':
            logger_instance.info("Creating TVO handler")
            return TVOBackupTargetHandler(target_cr, k8s_client, logger_instance)
        
        else:
            # Default to TVK if unknown
            logger_instance.warning(
                f"Unknown backup type '{backup_type}', defaulting to TVK handler"
            )
            return TVKBackupTargetHandler(target_cr, k8s_client, logger_instance)

