#!/usr/bin/env python3
"""
Threat Scanning Poller - Main Entry Point

This poller runs as a Kubernetes CronJob and performs the following operations:
1. Cleanup: Remove stale ScanInstance CRs for deleted backups/backupplans
2. Discovery: (TODO) Discover new backups and create ScanInstance CRs
3. Monitoring: (TODO) Update metrics and status

Environment Variables:
    BACKUP_TARGET_NAME: Name of the BackupTarget CR to process (required)
    CRONJOB_NAME: Name of the CronJob (passed by controller) (required)
    CRONJOB_NAMESPACE: Namespace of the CronJob (default: default)
    DISCOVERY_LOOKBACK_HOURS: Hours to look back for new backups if no CronJob history (default: 6)
    LOG_LEVEL: Logging level (DEBUG, INFO, WARN, ERROR)
"""

import os
import sys
import logging as python_logging

# Add parent directory to path to import mount_utility
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mount_utility import logger
from mount_utility.mount_by_target_crd import triliodata_crd_parser
from mount_utility import constants

from k8s.client import K8sClient
from cleanup.detector import BackupTypeDetector
from cleanup.factory import BackupTargetHandlerFactory

logging = logger.logger

# Suppress boto3/botocore/urllib3 debug logs
python_logging.getLogger('boto3').setLevel(python_logging.WARNING)
python_logging.getLogger('botocore').setLevel(python_logging.WARNING)
python_logging.getLogger('urllib3').setLevel(python_logging.WARNING)

# Suppress kubernetes client debug logs - only show INFO and above
python_logging.getLogger('kubernetes').setLevel(python_logging.INFO)


def print_banner():
    """Print startup banner."""
    logging.info("Starting Threat Scanning Poller")


def check_reporting_target(k8s_client: K8sClient) -> bool:
    """
    Check if ReportingTarget is available.
    
    Args:
        k8s_client: Kubernetes client instance
        
    Returns:
        True if reporting target is available, False otherwise
    """
    logging.info("Checking ReportingTarget availability...")
    
    try:
        # Get all targets
        all_targets = k8s_client.list_targets()
        
        # Find reporting target (annotation: trilio.io/reporting-target=true)
        reporting_target = None
        for target in all_targets:
            annotations = target.get('metadata', {}).get('annotations', {})
            if annotations.get('trilio.io/reporting-target') == 'true':
                reporting_target = target
                break
        
        if not reporting_target:
            logging.error("ReportingTarget not found")
            return False
        
        # Check if available
        target_name = reporting_target['metadata']['name']
        target_status = reporting_target.get('status', {}).get('status', '')
        
        if target_status != 'Available':
            logging.error(
                f"ReportingTarget '{target_name}' is not available "
                f"(status: {target_status})"
            )
            return False
        
        logging.info(f"✓ ReportingTarget '{target_name}' is available")
        return True
        
    except Exception as e:
        logging.error(f"Failed to check ReportingTarget: {str(e)}")
        return False


def get_backup_target(k8s_client: K8sClient, target_name: str):
    """
    Get BackupTarget CR.
    
    Note: This poller is only created/run when the BackupTarget is in 'Available' state,
    so we assume the target is available and don't need to check status.
    
    Args:
        k8s_client: Kubernetes client instance
        target_name: Name of the target
        
    Returns:
        Target CR dictionary or None
    """
    logging.info(f"Fetching BackupTarget '{target_name}'...")
    
    try:
        # Use existing function to get Target CR
        backup_target = triliodata_crd_parser.get_ds_from_target_crds(
            target_crd_name=target_name,
            target_crd_namespace=None,  # Cluster-scoped
            target_cred_hash=None,
            group=constants.TVK_CRD_GROUP,
            version=constants.TVK_CRD_VERSION
        )
        
        if not backup_target:
            logging.error(f"Target '{target_name}' not found")
            return None
        
        logging.info(f"✓ BackupTarget '{target_name}' fetched successfully")
        return backup_target
        
    except Exception as e:
        logging.error(f"Failed to get BackupTarget: {str(e)}")
        return None


def run_cleanup_phase(k8s_client: K8sClient, backup_target: dict):
    """
    Run cleanup phase to remove stale ScanInstance CRs.
    
    Flow:
    1. Detect backup type by examining backup directory structure
    2. Create appropriate handler based on detected type
    3. Perform cleanup
    
    Args:
        k8s_client: Kubernetes client instance
        backup_target: BackupTarget CR dictionary
        
    Returns:
        Tuple of (success: bool, handler: BaseBackupTargetHandler)
    """
    try:
        # Detect backup type by examining backup directory
        logging.info("Starting cleanup phase")
        logging.info("Detecting backup type from target structure...")
        detector = BackupTypeDetector(backup_target, logging)
        backup_type = detector.detect()
        
        if backup_type == 'UNKNOWN':
            logging.warning("Could not detect backup type, defaulting to TVK")
            backup_type = 'TVK'
        
        logging.info(f"Detected backup type: {backup_type}")
        
        # Step 2: Create appropriate handler based on detected type
        handler = BackupTargetHandlerFactory.create_handler(
            backup_target, k8s_client, logging, backup_type
        )
        
        # Perform cleanup
        result = handler.perform_cleanup()
        
        # Log results
        if result.success:
            logging.info(f"Cleanup completed successfully - Backup type: {backup_type}, "
                        f"Backupplans: {result.backupplan_count}, "
                        f"Total backups: {result.total_backups_found}, "
                        f"Deleted: {result.deleted_count}")
            if result.failed_deletions:
                logging.warning(f"Failed to delete {len(result.failed_deletions)} ScanInstances: {', '.join(result.failed_deletions)}")
        else:
            logging.error(f"Cleanup failed: {result.error}")
        
        return result.success, handler
        
    except Exception as e:
        logging.error(f"Cleanup phase failed with exception: {str(e)}", exc_info=True)
        return False, None


def run_discovery_phase(
    k8s_client: K8sClient, 
    backup_target: dict, 
    handler,
    cronjob_name: str
) -> bool:
    """
    Run discovery phase to find new backups and create ScanInstance CRs.
    
    Flow:
    1. Get last successful run time from CronJob status
    2. For S3: Use S3 API to detect backupplans with new backups
       For NFS: Mount first, then use find to detect new backups
    3. Mount target to /triliodata (for S3, only if new backups found)
    4. For each backupplan with new backups:
       a. Get latest backup UID
       b. Create ScanInstance CR (TODO)
    5. Cleanup (unmount /triliodata)
    
    Args:
        k8s_client: Kubernetes client instance
        backup_target: BackupTarget CR dictionary
        handler: Handler instance (reused from cleanup phase)
        cronjob_name: Name of the CronJob (passed by controller)
        
    Returns:
        True if discovery succeeded, False otherwise
    """
    try:
        # Perform discovery using handler
        logging.info("Starting discovery phase")
        result = handler.perform_discovery(cronjob_name)
        
        # Log results
        if result.success:
            logging.info(f"Discovery completed successfully - New backups: {result.new_backups_found}, "
                        f"Backupplans processed: {len(result.backupplans_processed)}, "
                        f"ScanInstances created: {result.scan_instances_created}")
            if result.failed_creations:
                logging.warning(f"Failed to create {len(result.failed_creations)} ScanInstances: {', '.join(result.failed_creations)}")
        else:
            logging.error(f"Discovery failed: {result.error}")
        
        return result.success
        
    except Exception as e:
        logging.error(f"Discovery phase failed with exception: {str(e)}", exc_info=True)
        return False


def main():
    """Main entry point for poller."""
    print_banner()
    
    # Get environment variables
    target_name = os.getenv('BACKUP_TARGET_NAME')
    if not target_name:
        logging.error("BACKUP_TARGET_NAME environment variable not set")
        logging.error("Please set BACKUP_TARGET_NAME to the name of the BackupTarget CR")
        sys.exit(1)
    
    cronjob_name = os.getenv('CRONJOB_NAME')
    if not cronjob_name:
        logging.error("CRONJOB_NAME environment variable not set")
        logging.error("Please set CRONJOB_NAME to the name of the CronJob")
        sys.exit(1)
    
    cronjob_namespace = os.getenv('CRONJOB_NAMESPACE', 'default')
    
    logging.info(f"Target: {target_name}")
    logging.info(f"CronJob: {cronjob_name} (namespace: {cronjob_namespace})")
    
    # Initialize K8s client
    try:
        k8s_client = K8sClient()
    except Exception as e:
        logging.error(f"Failed to initialize Kubernetes client: {str(e)}")
        sys.exit(1)
    
    # Step 1: Check ReportingTarget availability
    if not check_reporting_target(k8s_client):
        logging.error("ReportingTarget check failed, exiting")
        sys.exit(1)
    
    # Step 2: Get BackupTarget CR
    backup_target = get_backup_target(k8s_client, target_name)
    if not backup_target:
        logging.error("Failed to get BackupTarget, exiting")
        sys.exit(1)
    
    # Step 3: Run cleanup phase
    cleanup_success, handler = run_cleanup_phase(k8s_client, backup_target)
    
    # Step 4: Run discovery phase (reuse handler from cleanup)
    discovery_success = run_discovery_phase(k8s_client, backup_target, handler, cronjob_name)
    
    # Final summary
    if cleanup_success and discovery_success:
        logging.info("Poller completed successfully")
    else:
        phases_failed = []
        if not cleanup_success:
            phases_failed.append("cleanup")
        if not discovery_success:
            phases_failed.append("discovery")
        logging.error(f"Poller failed - Failed phases: {', '.join(phases_failed)}")
    
    # Exit with appropriate code
    if cleanup_success and discovery_success:
        logging.info("Poller completed successfully")
        sys.exit(0)
    else:
        logging.error("Poller completed with errors")
        sys.exit(1)


if __name__ == '__main__':
    main()

