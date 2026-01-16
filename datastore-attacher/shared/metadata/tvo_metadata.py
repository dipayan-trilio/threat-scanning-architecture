"""
TVO metadata parsing utilities.

NOTE: TVO support is not yet implemented.
"""

import os
import json
from typing import Dict, Optional


def read_tvo_meta(backup_path: str) -> Optional[Dict]:
    """
    Read TVO metadata from backup path.
    
    NOTE: Not yet implemented.
    
    Args:
        backup_path: Path to backup directory
        
    Returns:
        None - TVO not implemented
    """
    # TODO: Implement TVO metadata reading
    return None


def get_instance_id(tvo_meta: Dict) -> Optional[str]:
    """
    Extract TVO instance ID from metadata.
    
    NOTE: Not yet implemented.
    
    Args:
        tvo_meta: Parsed TVO metadata dict
        
    Returns:
        None - TVO not implemented
    """
    # TODO: Implement TVO instance ID extraction
    return None

