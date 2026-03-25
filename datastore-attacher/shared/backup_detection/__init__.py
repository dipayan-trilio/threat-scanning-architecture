"""
Backup type detection utilities.

Provides detector classes for extracting metadata from different backup types (TVK, TVO).
Backup type is now specified via command-line argument instead of auto-detection.
"""

from .base_detector import BaseBackupDetector
from .tvk_detector import TVKBackupDetector
from .tvo_detector import TVOBackupDetector

__all__ = [
    'BaseBackupDetector',
    'TVKBackupDetector',
    'TVOBackupDetector',
]

