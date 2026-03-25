"""
Handler factory for creating type-specific backup handlers.
"""

import os
import sys
from typing import Dict

# Add parent directory to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from .base_handler import BaseTargetHandler
from .tvk_handler import TVKTargetHandler
from .tvo_handler import TVOTargetHandler


class HandlerFactory:
    """
    Factory for creating backup type-specific handlers.
    
    Creates appropriate handler based on backup type provided via command-line argument.
    """
    
    @staticmethod
    def create_handler(
        target_cr: Dict,
        k8s_client,
        logger_instance,
        target_type: str
    ) -> BaseTargetHandler:
        """
        Create handler based on target type from command-line argument.
        
        Args:
            target_cr: Target CR dictionary
            k8s_client: Kubernetes client instance
            logger_instance: Logger instance
            target_type: Target type ('TVK' or 'TVO') from --target-type flag
            
        Returns:
            Handler instance (TVKTargetHandler or TVOTargetHandler)
            
        Raises:
            RuntimeError: If target type is not supported
        """
        logger_instance.info(f"Creating handler for target type: {target_type}")
        
        if target_type == 'TVK':
            logger_instance.info("Using TVK handler")
            handler = TVKTargetHandler(target_cr, k8s_client, logger_instance)
            handler.backup_type_detected = True  # Mark as already known
            return handler
        elif target_type == 'TVO':
            logger_instance.info("Using TVO handler")
            handler = TVOTargetHandler(target_cr, k8s_client, logger_instance)
            handler.backup_type_detected = True  # Mark as already known
            return handler
        else:
            # Unknown target type
            raise RuntimeError(
                f"Unsupported target type: {target_type}. "
                f"Supported types: TVK, TVO"
            )


