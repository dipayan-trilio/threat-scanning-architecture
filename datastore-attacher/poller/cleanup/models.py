"""
Data models for backup discovery and filtering.
"""

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime
from enum import Enum


class BackupMetadataType(Enum):
    """Types of backup metadata files"""
    BACKUP = "backup"
    CLUSTER_BACKUP = "cluster-backup"
    SNAPSHOT = "snapshot"
    CLUSTER_SNAPSHOT = "cluster-snapshot"
    
    @property
    def filename(self) -> str:
        """Get the JSON filename for this metadata type"""
        return f"{self.value}.json"


@dataclass
class BackupInfo:
    """Information about a discovered backup"""
    backupplan_uid: str
    backup_uid: str
    metadata_type: BackupMetadataType
    last_modified: datetime
    metadata_file_path: str  # Full path or S3 key
    
    def __repr__(self) -> str:
        return (
            f"BackupInfo(backupplan={self.backupplan_uid}, "
            f"backup={self.backup_uid}, type={self.metadata_type.value})"
        )


@dataclass
class DiscoveredBackups:
    """Collection of discovered backups grouped by backupplan"""
    backups_by_plan: Dict[str, List[BackupInfo]] = field(default_factory=dict)
    
    @property
    def total_backups(self) -> int:
        """Total number of backups across all backupplans"""
        return sum(len(backups) for backups in self.backups_by_plan.values())
    
    @property
    def total_backupplans(self) -> int:
        """Total number of backupplans with backups"""
        return len(self.backups_by_plan)
    
    def add_backup(self, backup_info: BackupInfo):
        """Add a backup to the collection"""
        if backup_info.backupplan_uid not in self.backups_by_plan:
            self.backups_by_plan[backup_info.backupplan_uid] = []
        self.backups_by_plan[backup_info.backupplan_uid].append(backup_info)
    
    def get_backups_for_plan(self, backupplan_uid: str) -> List[BackupInfo]:
        """Get all backups for a specific backupplan"""
        return self.backups_by_plan.get(backupplan_uid, [])
    
    def __repr__(self) -> str:
        return (
            f"DiscoveredBackups(backupplans={self.total_backupplans}, "
            f"backups={self.total_backups})"
        )


