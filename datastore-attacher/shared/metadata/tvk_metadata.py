"""
TVK metadata parsing utilities.
"""

import os
import json
from typing import Dict, Optional, List


def read_tvk_meta(backup_path: str) -> Optional[Dict]:
    """
    Read tvk-meta.json from backup path.
    
    Args:
        backup_path: Path to backup directory
        
    Returns:
        Parsed tvk-meta.json dict or None if not found
    """
    tvk_meta_path = os.path.join(backup_path, 'tvk-meta.json')
    
    try:
        with open(tvk_meta_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in tvk-meta.json: {str(e)}")


def get_instance_id(tvk_meta: Dict) -> Optional[str]:
    """
    Extract TVK instance ID from tvk-meta.json.
    
    Args:
        tvk_meta: Parsed tvk-meta.json dict
        
    Returns:
        Instance ID or None
    """
    return tvk_meta.get('instanceID')


def read_backupplan_json(backup_path: str, is_cluster: bool = False) -> Optional[Dict]:
    """
    Read backupplan.json or cluster-backupplan.json.
    
    Args:
        backup_path: Path to backup directory
        is_cluster: Whether to read cluster-backupplan.json
        
    Returns:
        Parsed backupplan JSON or None
    """
    filename = 'cluster-backupplan.json' if is_cluster else 'backupplan.json'
    backupplan_path = os.path.join(backup_path, filename)
    
    try:
        with open(backupplan_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {filename}: {str(e)}")


def read_backup_json(backup_path: str, is_cluster: bool = False) -> Optional[Dict]:
    """
    Read backup.json or cluster-backup.json.
    
    Args:
        backup_path: Path to backup directory
        is_cluster: Whether to read cluster-backup.json
        
    Returns:
        Parsed backup JSON or None
    """
    filename = 'cluster-backup.json' if is_cluster else 'backup.json'
    backup_json_path = os.path.join(backup_path, filename)
    
    try:
        with open(backup_json_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {filename}: {str(e)}")


def get_backupplan_uid(backupplan_json: Dict) -> Optional[str]:
    """Extract backupplan UID from backupplan.json."""
    return backupplan_json.get('metadata', {}).get('uid')


def get_backup_uid(backup_json: Dict) -> Optional[str]:
    """Extract backup UID from backup.json."""
    return backup_json.get('metadata', {}).get('uid')


def check_vm_workload_in_metadata(metadata_json: Dict) -> bool:
    """
    Check if metadata.json contains VM-related resources.
    
    Looks for: VirtualMachine, VirtualMachineInstance, DataVolume, VirtualMachinePool
    
    Args:
        metadata_json: Parsed metadata.json dict
        
    Returns:
        True if VM workload detected, False otherwise
    """
    vm_kinds = {'VirtualMachine', 'VirtualMachineInstance', 'DataVolume', 'VirtualMachinePool'}
    
    # Check in resources list
    resources = metadata_json.get('resources', [])
    for resource in resources:
        kind = resource.get('kind', '')
        if kind in vm_kinds:
            return True
    
    return False

