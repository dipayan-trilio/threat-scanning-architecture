"""
Backup path validation utilities.
"""

import os


def validate_backup_path(backup_path: str):
    """
    Validate that backup path exists and is accessible.
    
    Args:
        backup_path: Full path to backup directory
        
    Raises:
        FileNotFoundError: If path doesn't exist
        NotADirectoryError: If path is not a directory
        PermissionError: If path is not accessible
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup path does not exist: {backup_path}")
    
    if not os.path.isdir(backup_path):
        raise NotADirectoryError(f"Backup path is not a directory: {backup_path}")
    
    if not os.access(backup_path, os.R_OK):
        raise PermissionError(f"Backup path is not readable: {backup_path}")

