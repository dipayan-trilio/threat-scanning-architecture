#!/usr/bin/env python3
"""
Prescan CLI for threat scanning service.

Validates backup path, extracts metadata, checks for VM workloads,
and updates ScanInstance CR with appropriate labels and annotations.
Backup type is provided via --backup-type argument from the controller.

Note: Target mounting is handled by the controller before running this CLI.
"""

import argparse
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mount_utility import logger
from shared.backup_detection.tvk_detector import TVKBackupDetector
from shared.backup_detection.tvo_detector import TVOBackupDetector
from shared.k8s.client import K8sClient
from prescan.validator import validate_backup_path
from prescan.error_handler import update_job_error_annotation

logging = logger.logger

TRILIODATA_MOUNT_PATH = '/triliodata'


def main():
    """Main prescan CLI entry point."""
    parser = argparse.ArgumentParser(description='Prescan validation for threat scanning')
    parser.add_argument('--target-name', required=True, help='Name of the Target CR')
    parser.add_argument('--backup-path', required=True, help='Relative path to backup directory')
    parser.add_argument('--backup-uid', required=True, help='Backup UID')
    parser.add_argument('--scaninstance-name', required=True, help='Name of ScanInstance CR')
    parser.add_argument('--target-type', required=True, choices=['TVK', 'TVO'], help='Target type (TVK or TVO)')
    
    args = parser.parse_args()
    
    # Get job info from environment for error annotation
    job_name = os.getenv('JOB_NAME')
    job_namespace = os.getenv('JOB_NAMESPACE')
    
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
        
        # Step 3: Get appropriate detector based on target type from args
        target_type = args.target_type
        logging.info(f"Using target type from args: {target_type}")
        
        from mount_utility.mount_by_target_crd import triliodata_crd_parser
        parsed_target = triliodata_crd_parser.parse_cr_response(target_cr)
        storage_type = parsed_target.get('storageType', '').lower()
        
        # Create detector based on target type
        if target_type == 'TVK':
            detector = TVKBackupDetector(parsed_target, storage_type, logging)
        elif target_type == 'TVO':
            detector = TVOBackupDetector(parsed_target, storage_type, logging)
        else:
            raise RuntimeError(f"Unsupported target type: {target_type}")
        
        # Step 4: Extract metadata (includes two-level VM workload detection)
        # This reads tvk-meta.json, backup.json/cluster-backup.json and child backups
        logging.info("Extracting metadata from backup...")
        metadata = detector.extract_metadata(full_backup_path, args.backup_uid)
        instance_id = metadata['instance_id']
        backupplan_uid = metadata['backupplan_uid']
        backup_uid = metadata['backup_uid']
        backup_creation_timestamp = metadata.get('backup_creation_timestamp', '')
        is_vm_workload = metadata['is_vm_workload']
        is_cluster_backup = metadata.get('is_cluster_backup', False)
        scan_locations = metadata.get('scan_locations', [])
        
        # Calculate total VM and PVC counts across all scan locations
        total_vm_count = sum(len(loc['vms']) for loc in scan_locations)
        total_pvc_count = sum(
            sum(len(vm['pvc_paths']) for vm in loc['vms'])
            for loc in scan_locations
        )
        
        logging.info(
            f"✓ Extracted metadata: instance_id={instance_id}, "
            f"backupplan_uid={backupplan_uid}, backup_uid={backup_uid}, "
            f"is_vm_workload={is_vm_workload}, is_cluster_backup={is_cluster_backup}, "
            f"scan_locations_count={len(scan_locations)}, total_vms={total_vm_count}, total_pvcs={total_pvc_count}"
        )
        
        # Step 5: Update ScanInstance CR with labels, annotations, and status
        # Use target name instead of UID in labels
        labels = {
            'trilio.io/instance-id': instance_id,
            'trilio.io/backup-target': args.target_name,
            'trilio.io/backupplan': backupplan_uid,
            'trilio.io/backup': backup_uid
        }
        
        # Annotation: vm-workload based on final scan_locations length
        annotations = {
            'trilio.io/vm-workload': str(is_vm_workload).lower(),
            'trilio.io/cluster-backup': str(is_cluster_backup).lower(),
            'trilio.io/backup-creation-timestamp': backup_creation_timestamp
        }
        
        # Convert scan_locations to camelCase for Kubernetes API
        # Python detector returns snake_case keys, but K8s API expects camelCase
        scan_locations_camel = []
        for loc in scan_locations:
            # Convert VM entries
            vms_camel = []
            for vm in loc['vms']:
                vms_camel.append({
                    'vmName': vm['vm_name'],        # snake_case → camelCase
                    'pvcPaths': vm['pvc_paths']     # snake_case → camelCase (already a list)
                })
            
            scan_locations_camel.append({
                'namespace': loc.get('namespace', ''),
                'backupUID': loc['backup_uid'],     # snake_case → camelCase
                'backupPath': loc['backup_path'],   # snake_case → camelCase
                'vms': vms_camel
            })
        
        # Prepare status update
        status = {
            'type': target_type,
            'scanLocations': scan_locations_camel
        }
        
        workload_type = "VM workload" if is_vm_workload else "non-VM workload"
        backup_structure = "cluster-backup" if is_cluster_backup else "namespace backup"
        
        logging.info(
            f"Updating ScanInstance {args.scaninstance_name} "
            f"({workload_type}, {backup_structure})..."
        )
        
        success = k8s_client.patch_scan_instance(
            args.scaninstance_name,
            labels=labels,
            annotations=annotations,
            status=status
        )
        
        if not success:
            raise RuntimeError("Failed to update ScanInstance CR")
        
        logging.info(f"✓ Successfully updated ScanInstance {args.scaninstance_name}")
        
        # Log details
        if is_vm_workload:
            if is_cluster_backup:
                logging.info(
                    f"✓ Cluster-backup with {len(scan_locations)} child backup(s) containing "
                    f"{total_vm_count} VM(s) and {total_pvc_count} PVC(s)"
                )
            else:
                logging.info(
                    f"✓ Namespace backup with {total_vm_count} VM(s) and {total_pvc_count} PVC(s) to scan"
                )
        else:
            logging.info("✓ No VM workloads to scan")
        
        logging.info(f"✓ Prescan validation completed successfully")
        
        sys.exit(0)
        
    except Exception as e:
        # Catch ALL exceptions and update job annotation before failing
        import traceback
        
        error_msg = f"Prescan validation failed: {str(e)}"
        error_details = traceback.format_exc()
        
        # Log error with full traceback for debugging
        logging.error(error_msg)
        logging.error(f"Full traceback:\n{error_details}")
        
        # Set ONLY the error message in annotation (no traceback)
        # Traceback is in logs for debugging - annotation is for user-facing display
        if job_name and job_namespace:
            update_job_error_annotation(job_name, job_namespace, error_msg)
        else:
            logging.warning(
                f"JOB_NAME or JOB_NAMESPACE not set (JOB_NAME={job_name}, JOB_NAMESPACE={job_namespace}), "
                f"cannot update job annotation"
            )
        
        sys.exit(1)


if __name__ == '__main__':
    main()

