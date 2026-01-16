"""
TVK backup type detector.
"""

import os
import re
import subprocess
import json
import tempfile
from typing import Optional, Dict

from .base_detector import BaseBackupDetector
from mount_utility import constants


class TVKBackupDetector(BaseBackupDetector):
    """
    Detector for TrilioVault for Kubernetes backups.
    
    Looks for tvk-meta.json (NFS) or tvk-meta.json.manifest.<hex> (S3).
    """
    
    def detect(self, mount_path: Optional[str] = None) -> str:
        """
        Detect if this is a TVK backup target.
        
        Args:
            mount_path: Path where target is mounted (required for NFS)
            
        Returns:
            'TVK' if TVK markers found, 'UNKNOWN' otherwise
        """
        self.logger.info("Scanning for TVK backup markers...")
        
        try:
            if self.target_type == constants.OBJECT_STORE:
                return self._detect_tvk_s3()
            else:
                if not mount_path:
                    raise ValueError("mount_path required for NFS detection")
                return self._detect_tvk_nfs(mount_path)
        except Exception as e:
            self.logger.error(f"Error during TVK detection: {str(e)}", exc_info=True)
            return 'UNKNOWN'
    
    def _detect_tvk_s3(self) -> str:
        """Detect TVK on S3 target."""
        bucket_name = self._get_s3_bucket_name()
        s3_client = self._create_s3_client()
        
        # Pattern for TVK metadata files
        tvk_meta_pattern = re.compile(r'^.+/tvk-meta\.json\.manifest\.[0-9a-f]{8}$')
        
        self.logger.info(f"Scanning S3 bucket '{bucket_name}' for backup markers...")
        
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            
            checked_count = 0
            for page in paginator.paginate(Bucket=bucket_name, Prefix=''):
                for obj in page.get('Contents', []):
                    obj_key = obj['Key']
                    checked_count += 1
                    
                    # Skip data segments directory
                    if obj_key.startswith('80bc80ff-0c51-4534-86a2-ec5e719643c2/'):
                        continue
                    
                    # Check for TVK marker
                    if tvk_meta_pattern.match(obj_key):
                        self.logger.info(f"✓ Found TVK marker: {obj_key}")
                        return 'TVK'
                    
                    # Check first 100 objects only
                    if checked_count > 100:
                        break
                
                if checked_count > 100:
                    break
            
            self.logger.info("No TVK markers found in S3 bucket")
            return 'UNKNOWN'
            
        except Exception as e:
            self.logger.error(f"Error scanning S3 for backup markers: {str(e)}")
            return 'UNKNOWN'
    
    def _detect_tvk_nfs(self, mount_path: str) -> str:
        """Detect TVK on NFS target."""
        self.logger.info(f"Scanning NFS mount '{mount_path}' for backup markers...")
        
        try:
            # Find backup directories (2 levels deep: backupplan-uid/backup-uid)
            result = subprocess.run(
                ['find', mount_path, '-mindepth', '2', '-maxdepth', '2', '-type', 'd'],
                capture_output=True,
                text=True,
                check=True,
                timeout=60
            )
            
            backup_dirs = [d for d in result.stdout.strip().split('\n') if d]
            
            # Check first few backup directories for tvk-meta.json
            for backup_dir in backup_dirs[:5]:
                tvk_meta_path = os.path.join(backup_dir, 'tvk-meta.json')
                if os.path.exists(tvk_meta_path):
                    self.logger.info(f"✓ Found TVK marker: {tvk_meta_path}")
                    return 'TVK'
            
            self.logger.info("No TVK markers found in NFS mount")
            return 'UNKNOWN'
            
        except Exception as e:
            self.logger.error(f"Error scanning NFS for backup markers: {str(e)}")
            return 'UNKNOWN'
    
    def detect_vm_workload(self, backup_path: str) -> bool:
        """
        Detect if TVK backup contains VM workload.
        
        Mounts metadata-snapshot.qcow2 and checks for KubeVirt resources.
        
        Args:
            backup_path: Full path to backup directory
            
        Returns:
            True if VM workload detected, False otherwise
        """
        metadata_qcow2 = os.path.join(backup_path, 'metadata-snapshot.qcow2')
        
        if not os.path.exists(metadata_qcow2):
            # No metadata snapshot, not a VM workload
            self.logger.info("No metadata-snapshot.qcow2 found, not a VM workload")
            return False
        
        # Create temporary mount point
        with tempfile.TemporaryDirectory() as mount_dir:
            nbd_device = None
            
            try:
                # Allocate NBD device
                nbd_device = self._allocate_nbd_device()
                if not nbd_device:
                    self.logger.warning("No free NBD device available, cannot detect VM workload")
                    return False
                
                # Connect qcow2 to NBD (10 minute timeout)
                subprocess.run(
                    ['sudo', 'qemu-nbd', '-c', nbd_device, '-r', metadata_qcow2],
                    check=True,
                    timeout=600,
                    capture_output=True
                )
                
                # Wait for device to be ready
                subprocess.run(
                    ['sudo', 'partprobe', nbd_device],
                    check=True,
                    timeout=30,
                    capture_output=True
                )
                
                # Give kernel time to detect partitions
                import time
                time.sleep(2)
                
                # Try to mount - first try partition 1, then raw device
                mount_device = None
                partition_device = f"{nbd_device}p1"
                
                # Check if partition exists
                if os.path.exists(partition_device):
                    mount_device = partition_device
                    self.logger.info(f"Using partition device: {partition_device}")
                else:
                    mount_device = nbd_device
                    self.logger.info(f"Using raw device: {nbd_device}")
                
                # Mount the device (10 minute timeout)
                subprocess.run(
                    ['sudo', 'mount', '-o', 'ro', mount_device, mount_dir],
                    check=True,
                    timeout=600,
                    capture_output=True
                )
                
                # Read metadata.json from custom/metadata-snapshot/metadata.json
                # This is where TVK stores the kubernetes resource metadata
                metadata_json_path = os.path.join(mount_dir, 'custom', 'metadata-snapshot', 'metadata.json')
                
                if not os.path.exists(metadata_json_path):
                    self.logger.warning(f"metadata.json not found at: {metadata_json_path}")
                    return False
                
                self.logger.info(f"Found metadata.json at: {metadata_json_path}")
                
                with open(metadata_json_path, 'r') as f:
                    metadata = json.load(f)
                
                # Check for KubeVirt VM resources
                is_vm = self._check_vm_resources_in_metadata(metadata)
                
                return is_vm
                
            except subprocess.CalledProcessError as e:
                # If mounting fails, assume not a VM workload
                self.logger.warning(
                    f"Failed to mount metadata snapshot: {e.stderr if e.stderr else str(e)}"
                )
                return False
            except Exception as e:
                self.logger.warning(f"Error detecting VM workload: {str(e)}")
                return False
            finally:
                # Cleanup: unmount and disconnect NBD
                if mount_dir:
                    subprocess.run(
                        ['sudo', 'umount', mount_dir],
                        check=False,
                        capture_output=True
                    )
                
                if nbd_device:
                    subprocess.run(
                        ['sudo', 'qemu-nbd', '-d', nbd_device],
                        check=False,
                        capture_output=True
                    )
    
    def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
        """
        Extract metadata from TVK backup.
        
        Reads tvk-meta.json and parses backup path structure.
        
        Args:
            backup_path: Full path to backup directory
            backup_uid: Backup UID from path
            
        Returns:
            Dict with instance_id, backupplan_uid, backup_uid
        """
        # Read tvk-meta.json
        tvk_meta_path = os.path.join(backup_path, 'tvk-meta.json')
        
        if not os.path.exists(tvk_meta_path):
            raise RuntimeError(f"tvk-meta.json not found at {tvk_meta_path}")
        
        try:
            with open(tvk_meta_path, 'r') as f:
                tvk_meta = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in tvk-meta.json: {str(e)}")
        
        # Extract instance UID from tvkInstanceUID field
        instance_id = tvk_meta.get('tvkInstanceUID')
        if not instance_id:
            raise RuntimeError("tvkInstanceUID not found in tvk-meta.json")
        
        self.logger.info(f"Extracted TVK instance UID: {instance_id}")
        
        # Parse backupplan_uid from path
        # Path structure: /triliodata/backupplan-uid/backup-uid/
        # We need to extract the parent directory names
        path_parts = backup_path.rstrip('/').split('/')
        
        # Get last two parts: backupplan-uid and backup-uid
        if len(path_parts) < 2:
            raise RuntimeError(f"Invalid backup path structure: {backup_path}")
        
        extracted_backup_uid = path_parts[-1]
        backupplan_uid = path_parts[-2]
        
        # Validate backup UID matches
        if extracted_backup_uid != backup_uid:
            self.logger.warning(
                f"Backup UID mismatch: path has {extracted_backup_uid}, "
                f"expected {backup_uid}"
            )
        
        return {
            'instance_id': instance_id,
            'backupplan_uid': backupplan_uid,
            'backup_uid': extracted_backup_uid
        }
    
    def _check_vm_resources_in_metadata(self, metadata_json: list) -> bool:
        """
        Check if metadata.json contains KubeVirt VM-related resources.
        
        Looks for: VirtualMachine, VirtualMachineInstance, DataVolume, VirtualMachinePool
        
        TVK metadata.json structure:
        [
          {
            "groupVersionKind": {
              "group": "kubevirt.io",
              "version": "v1",
              "kind": "VirtualMachine"
            },
            "metadata": [...],
            "names": [...],
            "namespace": "..."
          },
          ...
        ]
        
        Args:
            metadata_json: Parsed metadata.json (array of resource groups)
            
        Returns:
            True if VM workload detected, False otherwise
        """
        vm_kinds = {
            'VirtualMachine',
            'VirtualMachineInstance',
            'DataVolume',
            'VirtualMachinePool'
        }
        
        # metadata.json is an array of resource groups
        if not isinstance(metadata_json, list):
            self.logger.warning(f"Unexpected metadata.json format: expected list, got {type(metadata_json)}")
            return False
        
        # Check each resource group for VM kinds
        for resource_group in metadata_json:
            gvk = resource_group.get('groupVersionKind', {})
            kind = gvk.get('kind', '')
            group = gvk.get('group', '')
            
            # Check if this is a KubeVirt VM resource
            if kind in vm_kinds and group == 'kubevirt.io':
                self.logger.info(f"Found VM resource: {group}/{kind}")
                return True
        
        self.logger.info("No VM resources found in metadata")
        return False
    
    def _allocate_nbd_device(self) -> Optional[str]:
        """
        Find and allocate a free NBD device.
        
        Returns:
            Path to free NBD device (e.g., '/dev/nbd0') or None
        """
        for i in range(16):  # Check nbd0 through nbd15
            device = f'/dev/nbd{i}'
            
            # Check if device exists
            if not os.path.exists(device):
                continue
            
            # Check if device is in use
            pid_file = f'/sys/block/nbd{i}/pid'
            if os.path.exists(pid_file):
                continue
            
            # Check lock file
            lock_file = f'/var/lock/qemu-nbd-nbd{i}'
            if os.path.exists(lock_file):
                continue
            
            return device
        
        return None

