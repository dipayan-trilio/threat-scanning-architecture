"""
Backup type detection utilities.

Provides detectors for different backup types (TVK, TVO).
"""

from .base_detector import BaseBackupDetector
from .tvk_detector import TVKBackupDetector
from .tvo_detector import TVOBackupDetector

__all__ = [
    'BaseBackupDetector',
    'TVKBackupDetector',
    'TVOBackupDetector',
    'detect_backup_type',
]


def detect_backup_type(parsed_target, target_type, logger, mount_path=None):
    """
    Convenience function to detect backup type.
    
    Tries TVK first, then TVO.
    
    Args:
        parsed_target: Parsed target metadata dict
        target_type: Target type (NFS/ObjectStore)
        logger: Logger instance
        mount_path: Path where target is mounted (for NFS)
        
    Returns:
        Tuple of (backup_type, detector_instance)
        backup_type: 'TVK', 'TVO', or 'UNKNOWN'
        detector_instance: The detector that found the match
        
    Example:
        backup_type, detector = detect_backup_type(
            parsed_target, 'NFS', logger, '/triliodata'
        )
        if backup_type == 'TVK':
            # Use TVK-specific logic
            pass
    """
    logger.info("Detecting backup type...")
    
    # Try TVK
    tvk_detector = TVKBackupDetector(parsed_target, target_type, logger)
    result = tvk_detector.detect(mount_path)
    if result == 'TVK':
        logger.info("✓ Detected TVK backup")
        return 'TVK', tvk_detector
    
    # Try TVO
    tvo_detector = TVOBackupDetector(parsed_target, target_type, logger)
    result = tvo_detector.detect(mount_path)
    if result == 'TVO':
        logger.info("✓ Detected TVO backup")
        return 'TVO', tvo_detector
    
    logger.warning("Could not detect backup type (tried TVK and TVO)")
    return 'UNKNOWN', None

