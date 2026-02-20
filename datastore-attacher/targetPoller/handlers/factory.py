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
from shared.backup_detection import detect_backup_type
from mount_utility.mount_by_target_crd import triliodata_crd_parser


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
        
        Uses shared backup detection logic to determine type.
        
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
        
        # Parse target to get metadata
        parsed_target = triliodata_crd_parser.parse_cr_response(target_cr)
        target_type = parsed_target.get('storageType', '').lower()
        
        # Use shared detection logic
        backup_type, _ = detect_backup_type(parsed_target, target_type, logger_instance)
        
        if backup_type == 'TVK':
            logger_instance.info("Using TVK handler")
            handler = TVKTargetHandler(target_cr, k8s_client, logger_instance)
            handler.backup_type_detected = True  # Mark as already detected
            return handler
        elif backup_type == 'TVO':
            logger_instance.info("Using TVO handler")
            handler = TVOTargetHandler(target_cr, k8s_client, logger_instance)
            handler.backup_type_detected = True  # Mark as already detected
            return handler
        else:
            # Unknown backup type
            raise RuntimeError(
                f"Could not determine backup type for target {target_cr['metadata']['name']}. "
                f"Supported types: TVK, TVO"
            )


