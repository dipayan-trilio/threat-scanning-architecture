"""
Storage state models for targetPoller.

Defines the in-memory representation of backup target structure.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


class BackupType(Enum):
    """Types of backup metadata"""
    BACKUP = "backup"
    CLUSTER_BACKUP = "cluster-backup"
    SNAPSHOT = "snapshot"
    CLUSTER_SNAPSHOT = "cluster-snapshot"
    
    @property
    def json_filename(self) -> str:
        """Get the JSON filename for this backup type"""
        return f"{self.value}.json"


@dataclass
class BackupObject:
    """
    Represents a single backup in the storage state.
    
    Attributes:
        backup_uid: Unique identifier for the backup
        json_path: Path to backup metadata file (backup.json, cluster-backup.json, etc.)
                   For NFS: backupplan-uid/backup-uid/backup.json
                   For S3: backupplan-uid/backup-uid/backup.json.manifest.<hex>
        last_updated_timestamp: Last modification time of the metadata file
        type: Type of backup (backup, cluster-backup, snapshot, cluster-snapshot)
    """
    backup_uid: str
    json_path: str
    last_updated_timestamp: datetime
    type: BackupType
    
    # Optional cached metadata (populated during discovery)
    status: Optional[str] = None  # "Available", "Failed", etc.
    completion_timestamp: Optional[datetime] = None
    
    def __repr__(self) -> str:
        return (
            f"BackupObject(uid={self.backup_uid}, "
            f"type={self.type.value}, "
            f"status={self.status})"
        )


@dataclass
class StorageState:
    """
    In-memory representation of the backup target structure.
    
    Maps backupplan UIDs to their backups.
    Structure:
        {
            "backupplan-uid-1": [BackupObject1, BackupObject2, ...],
            "backupplan-uid-2": [BackupObject3, BackupObject4, ...],
            ...
        }
    """
    backupplans: Dict[str, List[BackupObject]] = field(default_factory=dict)
    
    def add_backup(self, backupplan_uid: str, backup: BackupObject):
        """Add a backup to the storage state"""
        if backupplan_uid not in self.backupplans:
            self.backupplans[backupplan_uid] = []
        self.backupplans[backupplan_uid].append(backup)
    
    def get_backups(self, backupplan_uid: str) -> List[BackupObject]:
        """Get all backups for a backupplan"""
        return self.backupplans.get(backupplan_uid, [])
    
    def has_backupplan(self, backupplan_uid: str) -> bool:
        """Check if backupplan exists in storage state"""
        return backupplan_uid in self.backupplans
    
    def has_backup(self, backupplan_uid: str, backup_uid: str) -> bool:
        """Check if a specific backup exists"""
        backups = self.get_backups(backupplan_uid)
        return any(b.backup_uid == backup_uid for b in backups)
    
    def get_backup(self, backupplan_uid: str, backup_uid: str) -> Optional[BackupObject]:
        """Get a specific backup object"""
        backups = self.get_backups(backupplan_uid)
        for backup in backups:
            if backup.backup_uid == backup_uid:
                return backup
        return None
    
    @property
    def total_backupplans(self) -> int:
        """Total number of backupplans"""
        return len(self.backupplans)
    
    @property
    def total_backups(self) -> int:
        """Total number of backups across all backupplans"""
        return sum(len(backups) for backups in self.backupplans.values())
    
    def get_all_backupplan_uids(self) -> List[str]:
        """Get list of all backupplan UIDs"""
        return list(self.backupplans.keys())
    
    def __repr__(self) -> str:
        return (
            f"StorageState(backupplans={self.total_backupplans}, "
            f"backups={self.total_backups})"
        )


@dataclass
class CleanupMessage:
    """Message for cleanup queue"""
    scaninstance_name: str
    backupplan_uid: str
    backup_uid: str
    
    def __repr__(self) -> str:
        return f"CleanupMessage(scaninstance={self.scaninstance_name})"


@dataclass
class CreationMessage:
    """Message for creation queue"""
    backupplan_uid: str
    backup_uid: str
    backup_path: str
    backup_type: BackupType
    
    def __repr__(self) -> str:
        return (
            f"CreationMessage(backupplan={self.backupplan_uid}, "
            f"backup={self.backup_uid})"
        )


@dataclass
class ScanConfig:
    """Scan configuration from backupplan.json"""
    enabled: bool = False
    scan_old_backups: bool = False
    
    @classmethod
    def from_dict(cls, config_dict: Optional[Dict]) -> 'ScanConfig':
        """Parse scanConfig from backupplan.json"""
        if not config_dict:
            return cls(enabled=False, scan_old_backups=False)
        
        return cls(
            enabled=config_dict.get('enabled', False),
            scan_old_backups=config_dict.get('scanOldBackups', False)
        )


