"""
Handler factory for creating type-specific backup handlers.
"""

from typing import Dict

from .base_handler import BaseTargetHandler
from .tvk_handler import TVKTargetHandler
from .tvo_handler import TVOTargetHandler


class HandlerFactory:
    """
    Factory for creating backup type-specific handlers.
    
    Detects backup type and returns appropriate handler instance.
    """
    
    @staticmethod
    def create_handler(
        target_cr: Dict,
        k8s_client,
        logger_instance
    ) -> BaseTargetHandler:
        """
        Create handler based on backup type detection.
        
        Args:
            target_cr: Target CR dictionary
            k8s_client: Kubernetes client instance
            logger_instance: Logger instance
            
        Returns:
            Handler instance (TVKTargetHandler or TVOTargetHandler)
            
        Raises:
            RuntimeError: If backup type cannot be determined
        """
        logger_instance.info("Creating handler for target...")
        
        # Try TVK first
        tvk_handler = TVKTargetHandler(target_cr, k8s_client, logger_instance)
        backup_type = tvk_handler.detect_backup_type()
        
        if backup_type == 'TVK':
            logger_instance.info("Using TVK handler")
            return tvk_handler
        
        # Try TVO
        tvo_handler = TVOTargetHandler(target_cr, k8s_client, logger_instance)
        backup_type = tvo_handler.detect_backup_type()
        
        if backup_type == 'TVO':
            logger_instance.info("Using TVO handler")
            return tvo_handler
        
        # Unknown backup type
        raise RuntimeError(
            f"Could not determine backup type for target {target_cr['metadata']['name']}. "
            f"Supported types: TVK, TVO"
        )


