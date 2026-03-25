#!/usr/bin/env python3
"""
Target Poller - Main Entry Point

Redesigned polling architecture with queue-based worker processing.

Phases:
1. Initialization: Detect type, populate storage state, start workers
2. Cleanup: Remove stale ScanInstances
3. Discovery: Find new backups and create ScanInstances

Arguments:
    --target-name: Name of the BackupTarget CR (required)
    --group: API group (default: threatscanning.trilio.io)
    --version: API version (default: v1)
"""

import os
import sys
import argparse
import logging as python_logging

# Add parent directory to path to import mount_utility
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mount_utility import logger
from mount_utility import constants

from targetPoller.k8s.client import K8sClient
from targetPoller.handlers.factory import HandlerFactory

logging = logger.logger

# Suppress boto3/botocore/urllib3 debug logs
python_logging.getLogger('boto3').setLevel(python_logging.WARNING)
python_logging.getLogger('botocore').setLevel(python_logging.WARNING)
python_logging.getLogger('urllib3').setLevel(python_logging.WARNING)
python_logging.getLogger('kubernetes').setLevel(python_logging.INFO)


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
    
    Args:
        k8s_client: Kubernetes client instance
        target_name: Name of the BackupTarget CR
        
    Returns:
        Target CR dictionary
        
    Raises:
        RuntimeError: If target not found or not available
    """
    logging.info(f"Getting BackupTarget: {target_name}")
    
    target = k8s_client.get_target(target_name)
    
    if not target:
        raise RuntimeError(f"BackupTarget '{target_name}' not found")
    
    logging.info(f"✓ BackupTarget '{target_name}' found")
    return target


def main():
    """Main entry point"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Target Poller for threat scanning')
    parser.add_argument('--target-name', required=True, help='Name of the BackupTarget CR')
    parser.add_argument('--target-type', required=True, choices=['TVK', 'TVO'], help='Backup type (TVK or TVO)')
    parser.add_argument('--group', default='threatscanning.trilio.io', help='API group')
    parser.add_argument('--version', default='v1', help='API version')
    
    args = parser.parse_args()
    
    logging.info("TARGET POLLER - Starting")
    logging.info(f"Target: {args.target_name}")
    logging.info(f"Target Type: {args.target_type}")
    
    try:
        # Initialize Kubernetes client
        logging.info("Initializing Kubernetes client...")
        k8s_client = K8sClient()
        logging.info("✓ Kubernetes client initialized")
        
        # Check ReportingTarget
        if not check_reporting_target(k8s_client):
            logging.error("ReportingTarget check failed, exiting")
            sys.exit(1)
        
        # Get BackupTarget
        backup_target = get_backup_target(k8s_client, args.target_name)
        
        # Create handler using factory with backup type from args
        logging.info("")
        logging.info("Creating handler...")
        handler = HandlerFactory.create_handler(
            target_cr=backup_target,
            k8s_client=k8s_client,
            logger_instance=logging,
            target_type=args.target_type
        )
        logging.info("✓ Handler created")
        
        handler.initialize()
        
        handler.perform_cleanup()
        
        handler.perform_discovery()
        
        handler.shutdown()
        
        logging.info("Target poller completed successfully")
        
        sys.exit(0)
        
    except KeyboardInterrupt:
        logging.info("Received interrupt signal, shutting down...")
        sys.exit(130)
        
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()


