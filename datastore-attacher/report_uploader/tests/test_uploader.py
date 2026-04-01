"""
Unit tests for ReportUploader class.

Tests S3 upload functionality with mocked boto3 client.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from botocore.exceptions import ClientError

from report_uploader.uploader import ReportUploader


class TestReportUploader:
    """Test ReportUploader functionality."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create mock logger."""
        logger = MagicMock()
        return logger
    
    @pytest.fixture
    def sample_parsed_target(self):
        """Create sample parsed target with S3 credentials."""
        return {
            'id': 'target-123',
            'storageType': 'ObjectStore',
            'name': 'reporting-target',
            'vendor': 'AWS',
            'metaData': {
                'accessKeyID': 'test-access-key',
                'accessKey': 'test-secret-key',
                's3Bucket': 'test-bucket',
                'regionName': 'us-west-2',
                's3EndpointUrl': 'https://s3.amazonaws.com',
                'skipCertVerification': False
            }
        }
    
    @pytest.fixture
    def uploader(self, sample_parsed_target, mock_logger):
        """Create ReportUploader instance."""
        return ReportUploader(sample_parsed_target, mock_logger)
    
    @pytest.fixture
    def temp_upload_dir(self):
        """Create temporary upload directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create test files
            (tmpdir_path / "file1.txt").write_text("content1")
            (tmpdir_path / "file2.json").write_text('{"key": "value"}')
            
            # Create subdirectory with files
            subdir = tmpdir_path / "subdir"
            subdir.mkdir()
            (subdir / "file3.txt").write_text("content3")
            
            yield str(tmpdir_path)
    
    def test_initialize_s3_client(self, uploader, sample_parsed_target, mock_logger):
        """Test S3 client initialization with correct parameters."""
        with patch('report_uploader.uploader.boto3.client') as mock_boto3_client:
            uploader._initialize_s3_client()
            
            # Verify boto3.client was called with correct parameters
            mock_boto3_client.assert_called_once()
            call_kwargs = mock_boto3_client.call_args[1]
            
            assert call_kwargs['aws_access_key_id'] == 'test-access-key'
            assert call_kwargs['aws_secret_access_key'] == 'test-secret-key'
            assert call_kwargs['endpoint_url'] == 'https://s3.amazonaws.com'
            assert call_kwargs['verify'] is True
            
            # Verify logger was called
            mock_logger.info.assert_called_with("✓ S3 client initialized successfully")
    
    def test_get_bucket_name(self, uploader):
        """Test getting bucket name from parsed target."""
        bucket_name = uploader._get_bucket_name()
        assert bucket_name == 'test-bucket'
    
    def test_upload_files_success(self, uploader, temp_upload_dir, mock_logger):
        """Test successful upload of all files."""
        # Mock S3 client
        mock_s3_client = MagicMock()
        uploader.s3_client = mock_s3_client
        
        # Upload files
        result = uploader.upload_files(temp_upload_dir, 'test-prefix')
        
        assert result is True
        
        # Verify upload_file was called for each file (3 files total)
        assert mock_s3_client.upload_file.call_count == 3
        
        # Verify calls were made with correct parameters
        upload_calls = mock_s3_client.upload_file.call_args_list
        
        # Extract uploaded keys
        uploaded_keys = [call[0][2] for call in upload_calls]  # 3rd argument is s3_key
        
        # Verify expected keys
        assert 'test-prefix/file1.txt' in uploaded_keys
        assert 'test-prefix/file2.json' in uploaded_keys
        assert 'test-prefix/subdir/file3.txt' in uploaded_keys
    
    def test_upload_files_empty_directory(self, uploader, mock_logger):
        """Test uploading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock S3 client
            mock_s3_client = MagicMock()
            uploader.s3_client = mock_s3_client
            
            result = uploader.upload_files(tmpdir, 'test-prefix')
            
            # Should succeed even with no files
            assert result is True
            
            # No uploads should be attempted
            mock_s3_client.upload_file.assert_not_called()
            
            # Warning should be logged
            mock_logger.warning.assert_called_once()
    
    def test_upload_files_nonexistent_directory(self, uploader, mock_logger):
        """Test uploading from non-existent directory."""
        with pytest.raises(ValueError, match="Upload directory does not exist"):
            uploader.upload_files('/nonexistent/path', 'test-prefix')
    
    def test_upload_files_not_a_directory(self, uploader, mock_logger):
        """Test uploading from a file instead of directory."""
        with tempfile.NamedTemporaryFile() as tmpfile:
            with pytest.raises(ValueError, match="Upload path is not a directory"):
                uploader.upload_files(tmpfile.name, 'test-prefix')
    
    def test_upload_files_partial_failure(self, uploader, temp_upload_dir, mock_logger):
        """Test handling of partial upload failures."""
        # Mock S3 client with one failure
        mock_s3_client = MagicMock()
        
        # Make second upload fail
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise ClientError(
                    {'Error': {'Code': 'AccessDenied', 'Message': 'Access Denied'}},
                    'upload_file'
                )
        
        mock_s3_client.upload_file.side_effect = side_effect
        uploader.s3_client = mock_s3_client
        
        # Upload should fail
        result = uploader.upload_files(temp_upload_dir, 'test-prefix')
        
        assert result is False
        
        # All files should be attempted
        assert mock_s3_client.upload_file.call_count == 3
        
        # Error should be logged
        assert any('Failed to upload' in str(call) for call in mock_logger.error.call_args_list)
    
    def test_verify_bucket_access_success(self, uploader, mock_logger):
        """Test successful bucket access verification."""
        # Mock S3 client
        mock_s3_client = MagicMock()
        mock_s3_client.list_objects_v2.return_value = {'Contents': []}
        uploader.s3_client = mock_s3_client
        
        result = uploader.verify_bucket_access()
        
        assert result is True
        
        # Verify list_objects_v2 was called correctly
        mock_s3_client.list_objects_v2.assert_called_once_with(
            Bucket='test-bucket',
            MaxKeys=1
        )
    
    def test_verify_bucket_access_failure(self, uploader, mock_logger):
        """Test bucket access verification failure."""
        # Mock S3 client with access denied error
        mock_s3_client = MagicMock()
        mock_s3_client.list_objects_v2.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'Access Denied'}},
            'list_objects_v2'
        )
        uploader.s3_client = mock_s3_client
        
        result = uploader.verify_bucket_access()
        
        assert result is False
        
        # Error should be logged
        mock_logger.error.assert_called()
    
    def test_object_prefix_normalization(self, uploader, temp_upload_dir, mock_logger):
        """Test that object prefix trailing slashes are handled correctly."""
        # Mock S3 client
        mock_s3_client = MagicMock()
        uploader.s3_client = mock_s3_client
        
        # Upload with trailing slash
        uploader.upload_files(temp_upload_dir, 'test-prefix/')
        
        # Verify keys don't have double slashes
        upload_calls = mock_s3_client.upload_file.call_args_list
        uploaded_keys = [call[0][2] for call in upload_calls]
        
        # No double slashes should exist
        for key in uploaded_keys:
            assert '//' not in key
            assert key.startswith('test-prefix/')
