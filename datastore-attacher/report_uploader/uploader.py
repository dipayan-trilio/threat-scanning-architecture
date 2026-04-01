"""
S3 Uploader for Reporting Targets

Handles uploading files from local directory to S3 using credentials
extracted from reporting target CRs.
"""

import os
from typing import Dict, Optional
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class ReportUploader:
    """
    Handles uploading files to S3 reporting targets.
    
    Uses credentials from Target CR to initialize boto3 S3 client
    and uploads files from local directory to S3.
    """
    
    def __init__(self, parsed_target: Dict, logger):
        """
        Initialize ReportUploader with target credentials.
        
        Args:
            parsed_target: Parsed target CR (from triliodata_crd_parser.parse_cr_response)
            logger: Logger instance
        """
        self.parsed_target = parsed_target
        self.logger = logger
        self.s3_client = None
    
    def _initialize_s3_client(self) -> None:
        """Initialize boto3 S3 client using target credentials."""
        metadata = self.parsed_target.get('metaData', {})
        
        # Build S3 config
        s3_config = Config(
            region_name=metadata.get('regionName', ''),
            signature_version='s3v4',
            max_pool_connections=100
        )
        
        # Check SSL verification
        verify_ssl = not metadata.get('skipCertVerification', False)
        
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            endpoint_url=metadata.get('s3EndpointUrl'),
            aws_access_key_id=metadata.get('accessKeyID'),
            aws_secret_access_key=metadata.get('accessKey'),
            config=s3_config,
            verify=verify_ssl
        )
        
        self.logger.info("✓ S3 client initialized successfully")
    
    def _get_bucket_name(self) -> str:
        """Get S3 bucket name from parsed target."""
        return self.parsed_target['metaData']['s3Bucket']
    
    def upload_files(self, upload_directory: str, object_prefix: str) -> bool:
        """
        Upload all files from directory to S3 under object prefix.
        
        Args:
            upload_directory: Local directory containing files to upload
            object_prefix: S3 object prefix where files will be uploaded
            
        Returns:
            True if all files uploaded successfully, False otherwise
            
        Raises:
            ValueError: If upload_directory doesn't exist or is not a directory
            RuntimeError: If S3 operations fail
        """
        # Validate upload directory
        upload_path = Path(upload_directory)
        if not upload_path.exists():
            raise ValueError(f"Upload directory does not exist: {upload_directory}")
        if not upload_path.is_dir():
            raise ValueError(f"Upload path is not a directory: {upload_directory}")
        
        # Initialize S3 client if not already done
        if self.s3_client is None:
            self._initialize_s3_client()
        
        bucket_name = self._get_bucket_name()
        
        # Ensure object prefix ends without trailing slash for consistency
        # We'll add it when constructing full keys
        object_prefix = object_prefix.rstrip('/')
        
        # Get all files recursively
        all_files = []
        for root, dirs, files in os.walk(upload_directory):
            for file in files:
                file_path = Path(root) / file
                all_files.append(file_path)
        
        if not all_files:
            self.logger.warning(f"No files found in directory: {upload_directory}")
            return True  # No files to upload is not an error
        
        self.logger.info(f"Found {len(all_files)} file(s) to upload")
        
        # Upload each file
        upload_count = 0
        failed_uploads = []
        
        for file_path in all_files:
            # Calculate relative path from upload_directory
            try:
                relative_path = file_path.relative_to(upload_path)
            except ValueError:
                self.logger.error(f"Failed to calculate relative path for: {file_path}")
                failed_uploads.append(str(file_path))
                continue
            
            # Construct S3 object key: object_prefix/relative/path/to/file.ext
            # Use forward slashes for S3 keys regardless of OS
            s3_key = f"{object_prefix}/{relative_path.as_posix()}"
            
            # Upload file
            try:
                self.logger.info(f"Uploading: {relative_path} → s3://{bucket_name}/{s3_key}")
                
                self.s3_client.upload_file(
                    str(file_path),
                    bucket_name,
                    s3_key
                )
                
                upload_count += 1
                self.logger.info(f"✓ Uploaded successfully")
                
            except ClientError as e:
                error_msg = f"Failed to upload {file_path}: {str(e)}"
                self.logger.error(error_msg)
                failed_uploads.append(str(file_path))
            except Exception as e:
                error_msg = f"Unexpected error uploading {file_path}: {str(e)}"
                self.logger.error(error_msg)
                failed_uploads.append(str(file_path))
        
        # Summary
        self.logger.info(
            f"Upload summary: {upload_count}/{len(all_files)} files uploaded successfully"
        )
        
        if failed_uploads:
            self.logger.error(f"Failed uploads ({len(failed_uploads)}):")
            for failed_file in failed_uploads:
                self.logger.error(f"  - {failed_file}")
            return False
        
        return True
    
    def verify_bucket_access(self) -> bool:
        """
        Verify that we can access the S3 bucket.
        
        Returns:
            True if bucket is accessible, False otherwise
        """
        # Initialize S3 client if not already done
        if self.s3_client is None:
            self._initialize_s3_client()
        
        bucket_name = self._get_bucket_name()
        
        try:
            # Try to list objects (limit to 1 for efficiency)
            self.s3_client.list_objects_v2(
                Bucket=bucket_name,
                MaxKeys=1
            )
            self.logger.info(f"✓ Verified access to bucket: {bucket_name}")
            return True
            
        except ClientError as e:
            self.logger.error(f"Failed to access bucket {bucket_name}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error verifying bucket access: {str(e)}")
            return False
