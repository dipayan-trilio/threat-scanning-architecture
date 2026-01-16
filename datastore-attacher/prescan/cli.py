#!/usr/bin/env python3
"""
Prescan CLI for threat scanning service.

Validates backup path, detects backup type, checks for VM workloads,
and updates ScanInstance CR with appropriate labels and annotations.

Note: Target mounting is handled by the controller before running this CLI.
"""

import argparse
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mount_utility import logger
from shared.backup_detection import detect_backup_type
from shared.backup_detection.tvk_detector import TVKBackupDetector
from shared.backup_detection.tvo_detector import TVOBackupDetector
from shared.k8s.client import K8sClient
from prescan.validator import validate_backup_path

logging = logger.logger

TRILIODATA_MOUNT_PATH = '/triliodata'


def main():
    """Main prescan CLI entry point."""
    parser = argparse.ArgumentParser(description='Prescan validation for threat scanning')
    parser.add_argument('--target-name', required=True, help='Name of the Target CR')
    parser.add_argument('--backup-path', required=True, help='Relative path to backup directory')
    parser.add_argument('--backup-uid', required=True, help='Backup UID')
    parser.add_argument('--scaninstance-name', required=True, help='Name of ScanInstance CR')
    
    args = parser.parse_args()
    
    try:
        # Initialize K8s client
        k8s_client = K8sClient()
        
        # Step 1: Validate backup path exists (target already mounted by controller)
        full_backup_path = os.path.join(TRILIODATA_MOUNT_PATH, args.backup_path)
        logging.info(f"Validating backup path: {full_backup_path}")
        validate_backup_path(full_backup_path)
        logging.info(f"✓ Backup path exists")
        
        # Step 2: Get target CR for metadata
        logging.info(f"Fetching target CR: {args.target_name}")
        target_cr = k8s_client.get_target(args.target_name)
        
        if not target_cr:
            raise RuntimeError(f"Target {args.target_name} not found")
        
        # Step 3: Detect backup type (TVK/TVO)
        from mount_utility.mount_by_target_crd import triliodata_crd_parser
        parsed_target = triliodata_crd_parser.parse_cr_response(target_cr)
        target_type = parsed_target.get('storageType', '').lower()
        
        backup_type, detector = detect_backup_type(
            parsed_target, target_type, logging, TRILIODATA_MOUNT_PATH
        )
        
        if backup_type == 'UNKNOWN':
            raise RuntimeError("Could not determine backup type (TVK/TVO)")
        
        # Step 4: Use detector to detect VM workload
        # Polymorphism: detector is already type-specific (TVK or TVO)
        is_vm_workload = detector.detect_vm_workload(full_backup_path)
        logging.info(f"✓ VM workload detection: {is_vm_workload}")
        
        # Step 5: Extract metadata (for both VM and non-VM workloads)
        logging.info("Extracting metadata from backup...")
        metadata = detector.extract_metadata(full_backup_path, args.backup_uid)
        instance_id = metadata['instance_id']
        backupplan_uid = metadata['backupplan_uid']
        backup_uid = metadata['backup_uid']
        
        logging.info(
            f"✓ Extracted metadata: instance_id={instance_id}, "
            f"backupplan_uid={backupplan_uid}, backup_uid={backup_uid}"
        )
        
        # Step 6: Update ScanInstance CR with labels, annotations, and status
        # Use target name instead of UID in labels
        labels = {
            'trilio.io/instance-id': instance_id,
            'trilio.io/backup-target': args.target_name,
            'trilio.io/backupplan': backupplan_uid,
            'trilio.io/backup': backup_uid
        }
        
        annotations = {
            'trilio.io/vm-workload': str(is_vm_workload).lower()
        }
        
        status = {
            'type': backup_type
        }
        
        workload_type = "VM workload" if is_vm_workload else "non-VM workload"
        logging.info(f"Updating ScanInstance {args.scaninstance_name} ({workload_type})...")
        success = k8s_client.patch_scan_instance(
            args.scaninstance_name,
            labels=labels,
            annotations=annotations,
            status=status
        )
        
        if not success:
            raise RuntimeError("Failed to update ScanInstance CR")
        
        logging.info(f"✓ Successfully updated ScanInstance {args.scaninstance_name}")
        logging.info(f"✓ Prescan validation completed successfully ({workload_type})")
        
        sys.exit(0)
        
    except Exception as e:
        logging.error(f"Prescan validation failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

