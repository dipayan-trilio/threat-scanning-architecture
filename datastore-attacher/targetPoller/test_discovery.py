#!/usr/bin/env python3
"""
Test script for targetPoller backup discovery.

Prints all detected backups for each backupplan with their status and timestamps.
Does NOT create any ScanInstances - dry-run mode only.

Usage:
    export TARGET_NAME=my-backup-target
    python3 test_discovery.py
"""

import os
import sys
import json
import logging as python_logging
from datetime import datetime
from typing import Dict, Optional

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mount_utility import logger
from mount_utility import constants

from targetPoller.k8s.client import K8sClient
from targetPoller.handlers.factory import HandlerFactory
from targetPoller.models.storage_state import BackupObject

logging = logger.logger

# Suppress boto3/botocore/urllib3 debug logs
python_logging.getLogger('boto3').setLevel(python_logging.WARNING)
python_logging.getLogger('botocore').setLevel(python_logging.WARNING)
python_logging.getLogger('urllib3').setLevel(python_logging.WARNING)
python_logging.getLogger('kubernetes').setLevel(python_logging.INFO)

# Mount path constant
TRILIODATA_MOUNT_PATH = '/triliodata'


def read_backup_metadata(backup: BackupObject) -> Optional[Dict]:
    """
    Read metadata from backup JSON file.
    
    Args:
        backup: BackupObject instance
        
    Returns:
        Parsed JSON metadata or None if read fails
    """
    try:
        backup_dir = os.path.join(
            TRILIODATA_MOUNT_PATH,
            os.path.dirname(backup.json_path)
        )
        
        # Try exact match first (NFS format)
        exact_filename = backup.type.json_filename
        exact_path = os.path.join(backup_dir, exact_filename)
        
        if os.path.exists(exact_path):
            with open(exact_path, 'r') as f:
                return json.load(f)
        else:
            # Try manifest format (S3 s3fuse format)
            if not os.path.exists(backup_dir):
                logging.warning(f"Backup directory does not exist: {backup_dir}")
                return None
                
            for filename in os.listdir(backup_dir):
                if filename.startswith(exact_filename + '.manifest.'):
                    manifest_path = os.path.join(backup_dir, filename)
                    with open(manifest_path, 'r') as f:
                        return json.load(f)
        
        logging.warning(f"Metadata file not found for backup: {backup.backup_uid}")
        return None
        
    except Exception as e:
        logging.error(f"Failed to read metadata for {backup.backup_uid}: {str(e)}")
        return None


def read_backupplan_metadata(backupplan_uid: str, backup_uid: str) -> Optional[Dict]:
    """
    Read backupplan.json metadata.
    
    Args:
        backupplan_uid: BackupPlan UID
        backup_uid: Backup UID (to locate backupplan.json)
        
    Returns:
        Parsed backupplan.json or None if read fails
    """
    try:
        backupplan_dir = os.path.join(
            TRILIODATA_MOUNT_PATH,
            backupplan_uid,
            backup_uid
        )
        
        # Try exact match first (NFS format)
        exact_path = os.path.join(backupplan_dir, 'backupplan.json')
        
        if os.path.exists(exact_path):
            with open(exact_path, 'r') as f:
                return json.load(f)
        else:
            # Try manifest format (S3 s3fuse format)
            if not os.path.exists(backupplan_dir):
                return None
                
            for filename in os.listdir(backupplan_dir):
                if filename.startswith('backupplan.json.manifest.'):
                    manifest_path = os.path.join(backupplan_dir, filename)
                    with open(manifest_path, 'r') as f:
                        return json.load(f)
        
        return None
        
    except Exception as e:
        logging.debug(f"Failed to read backupplan.json for {backupplan_uid}: {str(e)}")
        return None


def format_timestamp(ts) -> str:
    """Format timestamp for display"""
    if isinstance(ts, datetime):
        return ts.strftime('%Y-%m-%d %H:%M:%S UTC')
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        except:
            return ts
    else:
        return str(ts)


def print_section_header(title: str):
    """Print a formatted section header"""
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)
    print()


def test_discovery():
    """Main test function"""
    print_section_header("TARGET POLLER - BACKUP DISCOVERY TEST")
    
    # Get environment variables
    target_name = os.environ.get('TARGET_NAME')
    target_namespace = os.environ.get('TARGET_NAMESPACE', 'trilio-system')
    
    if not target_name:
        logging.error("TARGET_NAME environment variable is required")
        print("\nUsage:")
        print("  export TARGET_NAME=my-backup-target")
        print("  python3 test_discovery.py")
        sys.exit(1)
    
    print(f"Target: {target_name}")
    print(f"Namespace: {target_namespace}")
    print()
    
    try:
        # Mount the target first
        logging.info(f"Mounting target: {target_name}")
        current_dir = os.path.dirname(os.path.abspath(__file__))
        mount_script = os.path.abspath(os.path.join(
            current_dir,
            '../mount_utility/mount_by_target_crd/mount_datastores.py'
        ))
        
        mount_cmd = [
            'python3',
            mount_script,
            f'--target-name={target_name}',
            '--group=threatscanning.trilio.io'
        ]
        
        try:
            import subprocess
            result = subprocess.run(
                mount_cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            logging.info(f"✓ Target mounted successfully")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to mount target: {e.stderr}")
            sys.exit(1)
        except subprocess.TimeoutExpired:
            logging.error("Mount command timed out")
            sys.exit(1)
        
        # Initialize Kubernetes client
        logging.info("Initializing Kubernetes client...")
        k8s_client = K8sClient()
        
        # Get BackupTarget
        logging.info(f"Getting BackupTarget: {target_name}")
        target_cr = k8s_client.get_target(target_name)
        
        if not target_cr:
            logging.error(f"BackupTarget '{target_name}' not found")
            sys.exit(1)
        
        # Create handler using factory
        logging.info("Creating handler and detecting backup type...")
        handler = HandlerFactory.create_handler(
            target_cr=target_cr,
            k8s_client=k8s_client,
            logger_instance=logging
        )
        
        print_section_header(f"BACKUP TYPE: {handler.backup_type}")
        
        # Populate storage state
        logging.info("Populating storage state...")
        storage_state = handler.populate_storage_state()
        
        print(f"✓ Storage state populated successfully")
        print(f"  - BackupPlans found: {storage_state.total_backupplans}")
        print(f"  - Total backups: {storage_state.total_backups}")
        
        if storage_state.total_backupplans == 0:
            print("\nNo backupplans found in target. Exiting.")
            sys.exit(0)
        
        # Process each backupplan
        print_section_header("BACKUP DETAILS BY BACKUPPLAN")
        
        backupplan_uids = storage_state.get_all_backupplan_uids()
        
        for idx, backupplan_uid in enumerate(backupplan_uids, 1):
            print(f"\n{'─' * 80}")
            print(f"[{idx}/{len(backupplan_uids)}] BackupPlan: {backupplan_uid}")
            print(f"{'─' * 80}")
            
            # Get all backups sorted by timestamp (latest first)
            backups = storage_state.get_backups(backupplan_uid)
            sorted_backups = sorted(
                backups,
                key=lambda b: b.last_updated_timestamp,
                reverse=True
            )
            
            print(f"\nTotal backups: {len(sorted_backups)}")
            
            # Get latest backup for backupplan config
            latest_backup = sorted_backups[0] if sorted_backups else None
            scan_config = None
            
            if latest_backup:
                backupplan_metadata = read_backupplan_metadata(
                    backupplan_uid,
                    latest_backup.backup_uid
                )
                
                if backupplan_metadata:
                    scan_config_dict = backupplan_metadata.get('spec', {}).get('scanConfig')
                    if scan_config_dict:
                        scan_enabled = scan_config_dict.get('enabled', False)
                        scan_old_backups = scan_config_dict.get('scanOldBackups', False)
                        print(f"\nScan Config:")
                        print(f"  - Enabled: {scan_enabled}")
                        print(f"  - Scan Old Backups: {scan_old_backups}")
                    else:
                        print(f"\nScan Config: Not configured")
                else:
                    print(f"\nScan Config: Could not read backupplan.json")
            
            print(f"\n{'─' * 80}")
            print(f"{'Backup UID':<40} {'Type':<20} {'Status':<12} {'Timestamp':<20}")
            print(f"{'─' * 80}")
            
            # Print each backup
            for backup in sorted_backups:
                # Read backup metadata
                metadata = read_backup_metadata(backup)
                
                if metadata:
                    status = metadata.get('status', {}).get('status', 'Unknown')
                    
                    # Try completion timestamp first, then creation timestamp
                    completion_ts = metadata.get('status', {}).get('completionTimestamp')
                    creation_ts = metadata.get('metadata', {}).get('creationTimestamp')
                    
                    timestamp = completion_ts or creation_ts or 'Unknown'
                    timestamp_str = format_timestamp(timestamp)
                else:
                    status = 'ERROR'
                    timestamp_str = format_timestamp(backup.last_updated_timestamp)
                
                # Truncate backup_uid if too long
                backup_uid_display = backup.backup_uid[:37] + '...' if len(backup.backup_uid) > 40 else backup.backup_uid
                
                # Color code status
                status_display = status
                if status.lower() == 'available':
                    status_display = f"✓ {status}"
                elif status.lower() in ['failed', 'error']:
                    status_display = f"✗ {status}"
                else:
                    status_display = f"⋯ {status}"
                
                print(f"{backup_uid_display:<40} {backup.type.value:<20} {status_display:<12} {timestamp_str:<20}")
        
        # Summary
        print_section_header("SUMMARY")
        
        total_backups = storage_state.total_backups
        available_count = 0
        failed_count = 0
        other_count = 0
        
        for backupplan_uid in backupplan_uids:
            for backup in storage_state.get_backups(backupplan_uid):
                metadata = read_backup_metadata(backup)
                if metadata:
                    status = metadata.get('status', {}).get('status', '').lower()
                    if status == 'available':
                        available_count += 1
                    elif status in ['failed', 'error']:
                        failed_count += 1
                    else:
                        other_count += 1
        
        print(f"BackupPlans: {storage_state.total_backupplans}")
        print(f"Total Backups: {total_backups}")
        print(f"  - Available: {available_count}")
        print(f"  - Failed: {failed_count}")
        print(f"  - Other: {other_count}")
        print()
        print("✓ Discovery test completed successfully")
        print("=" * 80)
        print()
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
        sys.exit(130)
        
    except Exception as e:
        logging.error(f"Test failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    test_discovery()

