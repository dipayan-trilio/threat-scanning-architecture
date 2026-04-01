#!/usr/bin/env python3
"""
Report Uploader CLI for threat scanning service.

Uploads files from a local directory to S3 reporting targets.
Validates that target is a reporting target, extracts credentials,
and uploads all files from the specified directory to S3.
"""

import argparse
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mount_utility import logger
from mount_utility import constants
from mount_utility.mount_by_target_crd import triliodata_crd_parser
from report_uploader.uploader import ReportUploader

logging = logger.logger


def validate_reporting_target(target_cr: dict, target_name: str) -> None:
    """
    Validate that target is a reporting target.
    
    Reporting targets are identified by the annotation:
    metadata.annotations['trilio.io/reporting-target'] = 'true'
    
    Args:
        target_cr: Target CR dictionary
        target_name: Name of the target (for error messages)
        
    Raises:
        ValueError: If target is not a reporting target
        RuntimeError: If annotations are missing
    """
    # Check for reporting target annotation
    annotations = target_cr.get('metadata', {}).get('annotations', {})
    
    if not annotations:
        raise RuntimeError(
            f"Target {target_name} does not have any annotations. "
            f"Cannot determine if this is a reporting target. "
            f"Reporting targets should have annotation 'trilio.io/reporting-target=true'"
        )
    
    is_reporting = annotations.get('trilio.io/reporting-target', '').lower()
    
    if is_reporting != 'true':
        found_value = is_reporting if is_reporting else '(not set)'
        raise ValueError(
            f"Target {target_name} is not a reporting target. "
            f"Expected annotation 'trilio.io/reporting-target=true', "
            f"found 'trilio.io/reporting-target={found_value}'"
        )
    
    logging.info(f"✓ Verified target {target_name} is a reporting target")


def validate_object_store_target(target_cr: dict, target_name: str) -> None:
    """
    Validate that target is an object store (S3) target.
    
    Args:
        target_cr: Target CR dictionary
        target_name: Name of the target (for error messages)
        
    Raises:
        ValueError: If target is not an object store
    """
    storage_type = target_cr.get('spec', {}).get('type', '').lower()
    
    if storage_type != constants.OBJECT_STORE:
        raise ValueError(
            f"Target {target_name} is not an object store target. "
            f"Found type='{storage_type}', expected '{constants.OBJECT_STORE}'. "
            f"Only object store (S3) targets are supported for report uploading."
        )
    
    logging.info(f"✓ Verified target {target_name} is an object store")


def main():
    """Main report uploader CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Upload files to S3 reporting target',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload dashboard reports to reporting target
  report-uploader --target-name reporting-prod \\
                  --upload-directory /tmp/reports \\
                  --object-prefix dashboard-reports/2026-03
  
  # Upload scan results to reporting target
  report-uploader --target-name reporting-s3 \\
                  --upload-directory /opt/scan-results \\
                  --object-prefix scan-results/instance-123
"""
    )
    
    parser.add_argument(
        '--target-name',
        required=True,
        help='Name of the reporting Target CR'
    )
    parser.add_argument(
        '--upload-directory',
        required=True,
        help='Local directory containing files to upload'
    )
    parser.add_argument(
        '--object-prefix',
        required=True,
        help='S3 object prefix where files will be uploaded (e.g., reports/2026-03)'
    )
    
    args = parser.parse_args()
    
    try:
        logging.info("=" * 60)
        logging.info("Report Uploader - Starting")
        logging.info("=" * 60)
        logging.info(f"Target: {args.target_name}")
        logging.info(f"Upload directory: {args.upload_directory}")
        logging.info(f"Object prefix: {args.object_prefix}")
        logging.info("")
        
        # Step 1: Validate upload directory exists
        if not os.path.exists(args.upload_directory):
            raise ValueError(f"Upload directory does not exist: {args.upload_directory}")
        if not os.path.isdir(args.upload_directory):
            raise ValueError(f"Upload path is not a directory: {args.upload_directory}")
        
        logging.info(f"✓ Validated upload directory exists")
        
        # Step 2: Fetch target CR
        logging.info(f"Fetching target CR: {args.target_name}")
        
        target_cr = triliodata_crd_parser.get_ds_from_target_crds(
            target_crd_name=args.target_name,
            target_crd_namespace=None,  # Targets are cluster-scoped
            target_cred_hash=None,
            group=constants.TVK_CRD_GROUP,
            version=constants.TVK_CRD_VERSION
        )
        
        if not target_cr:
            raise RuntimeError(f"Target {args.target_name} not found")
        
        logging.info(f"✓ Retrieved target CR")
        
        # Step 3: Validate target is a reporting target
        logging.info(f"Validating target type...")
        validate_reporting_target(target_cr, args.target_name)
        
        # Step 4: Validate target is object store (S3)
        logging.info(f"Validating storage type...")
        validate_object_store_target(target_cr, args.target_name)
        
        # Step 5: Parse target CR to extract credentials
        logging.info(f"Extracting credentials from target...")
        parsed_target = triliodata_crd_parser.parse_cr_response(target_cr)
        
        # Verify we got the required metadata
        if 'metaData' not in parsed_target:
            raise RuntimeError(f"Failed to extract metadata from target {args.target_name}")
        
        metadata = parsed_target['metaData']
        required_fields = ['accessKeyID', 'accessKey', 's3Bucket']
        missing_fields = [f for f in required_fields if f not in metadata]
        
        if missing_fields:
            raise RuntimeError(
                f"Target {args.target_name} is missing required S3 credentials: "
                f"{', '.join(missing_fields)}"
            )
        
        bucket_name = metadata['s3Bucket']
        logging.info(f"✓ Extracted credentials (bucket: {bucket_name})")
        
        # Step 6: Initialize uploader and verify bucket access
        logging.info("Initializing S3 uploader...")
        uploader = ReportUploader(parsed_target, logging)
        
        logging.info("Verifying S3 bucket access...")
        if not uploader.verify_bucket_access():
            raise RuntimeError(f"Failed to access S3 bucket: {bucket_name}")
        
        # Step 7: Upload files
        logging.info("")
        logging.info("Starting file upload...")
        logging.info("-" * 60)
        
        success = uploader.upload_files(
            upload_directory=args.upload_directory,
            object_prefix=args.object_prefix
        )
        
        if not success:
            raise RuntimeError("File upload failed - see errors above")
        
        logging.info("-" * 60)
        logging.info("")
        logging.info("=" * 60)
        logging.info("✓ Report upload completed successfully")
        logging.info("=" * 60)
        
        sys.exit(0)
        
    except ValueError as e:
        # User input validation errors
        logging.error(f"Validation error: {str(e)}")
        sys.exit(1)
        
    except Exception as e:
        # All other errors
        import traceback
        
        error_msg = f"Report upload failed: {str(e)}"
        error_details = traceback.format_exc()
        
        logging.error("")
        logging.error("=" * 60)
        logging.error(error_msg)
        logging.error("=" * 60)
        logging.error(f"Full traceback:\n{error_details}")
        
        sys.exit(1)


if __name__ == '__main__':
    main()
