"""
TVK backup metadata extractor.

Extracts metadata from TrilioVault for Kubernetes backups.
Target type (TVK/TVO) is now specified via command-line argument.
VM workload detection is still performed on a per-backup basis.
"""

import os
import re
import subprocess
import json
from typing import Dict, Optional

from .base_detector import BaseBackupDetector
from mount_utility import constants


class TVKBackupDetector(BaseBackupDetector):
    """
    Metadata extractor for TrilioVault for Kubernetes backups.
    
    Reads tvk-meta.json and backup metadata files to extract backup information.
    Note: Target type detection (TVK vs TVO) has been removed - now specified via CLI argument.
    VM workload detection per backup is still performed.
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
    
    def extract_metadata(self, backup_path: str, backup_uid: str) -> Dict[str, str]:
        """
        Extract metadata from TVK backup with two-level VM detection.
        
        Supports both single namespace backups and cluster-backups.
        Uses two-level detection:
        - Level 1: hasKubevirtResources (quick check)
        - Level 2: Parse dataSnapshots to get VM PVC paths (granular filtering)
        
        Args:
            backup_path: Full path to backup directory
            backup_uid: Backup UID from path
            
        Returns:
            Dict with instance_id, backupplan_uid, backup_uid, is_vm_workload, scan_locations
        """
        # Check if this is a cluster-backup
        cluster_backup_json_path = os.path.join(backup_path, 'cluster-backup.json')
        is_cluster_backup = os.path.exists(cluster_backup_json_path)
        
        if is_cluster_backup:
            self.logger.info("Detected cluster-backup, processing child backups")
            return self._extract_cluster_backup_metadata(backup_path, backup_uid)
        else:
            self.logger.info("Detected single namespace backup")
            return self._extract_namespace_backup_metadata(backup_path, backup_uid)
    
    def _extract_namespace_backup_metadata(self, backup_path: str, backup_uid: str) -> Dict:
        """
        Extract metadata from single namespace backup with two-level VM detection.
        
        Level 1: Check hasKubevirtResources (quick filter)
        Level 2: Parse dataSnapshots to get VM PVC paths
        
        Args:
            backup_path: Full path to backup directory
            backup_uid: Backup UID
            
        Returns:
            Dict with metadata and scan_locations
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
        
        # Extract instance UID
        instance_id = tvk_meta.get('tvkInstanceUID')
        if not instance_id:
            raise RuntimeError("tvkInstanceUID not found in tvk-meta.json")
        
        self.logger.info(f"Extracted TVK instance UID: {instance_id}")
        
        # Read backup.json
        backup_json_path = os.path.join(backup_path, 'backup.json')
        
        if not os.path.exists(backup_json_path):
            raise RuntimeError(f"backup.json not found at {backup_json_path}")
        
        try:
            with open(backup_json_path, 'r') as f:
                backup_json = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in backup.json: {str(e)}")
        
        # Extract backup creation timestamp from metadata
        backup_creation_timestamp = backup_json.get('metadata', {}).get('creationTimestamp', '')
        
        # Parse path structure
        path_parts = backup_path.rstrip('/').split('/')
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
        
        # LEVEL 1: Quick check - does this backup have ANY kubevirt resources?
        has_kubevirt = backup_json.get('status', {}).get('hasKubevirtResources', False)
        
        scan_locations = []
        
        if has_kubevirt:
            # LEVEL 2: Parse dataSnapshots to get VM PVC map (grouped by VM)
            self.logger.info("Backup has kubevirt resources, parsing dataSnapshots for VM PVCs")
            vm_pvc_map = self._extract_vm_pvc_locations(backup_json)
            
            if len(vm_pvc_map) > 0:
                # Convert map to list of VM entries
                vms = []
                for vm_name, pvc_paths in vm_pvc_map.items():
                    vms.append({
                        'vm_name': vm_name,
                        'pvc_paths': pvc_paths
                    })
                
                # Create single ScanLocation entry (namespace is empty for single ns backup)
                relative_backup_path = os.path.join(backupplan_uid, extracted_backup_uid)
                scan_locations.append({
                    'namespace': '',  # Empty for non-cluster backup
                    'backup_uid': extracted_backup_uid,
                    'backup_path': relative_backup_path,
                    'vms': vms
                })
                
                total_pvcs = sum(len(pvc_paths) for pvc_paths in vm_pvc_map.values())
                self.logger.info(
                    f"Added scan location with {len(vm_pvc_map)} VM(s) and {total_pvcs} PVC(s)"
                )
            else:
                self.logger.warning(
                    "hasKubevirtResources is true but no VM PVCs found in dataSnapshots. "
                    "This might indicate VirtualMachine resources without attached disks."
                )
        else:
            self.logger.info(
                "Backup has no kubevirt resources (hasKubevirtResources=false), "
                "skipping dataSnapshots parsing"
            )
        
        # Annotation based on final scan_locations length
        is_vm_workload = len(scan_locations) > 0
        
        # Extract backup plan name from backup.json spec
        backupplan_name = backup_json.get('spec', {}).get('backupPlan', '')
        
        return {
            'instance_id': instance_id,
            'backupplan_uid': backupplan_uid,
            'backupplan_name': backupplan_name,
            'backup_uid': extracted_backup_uid,
            'backup_creation_timestamp': backup_creation_timestamp,
            'is_vm_workload': is_vm_workload,
            'is_cluster_backup': False,
            'scan_locations': scan_locations
        }
    
    def _extract_cluster_backup_metadata(self, backup_path: str, backup_uid: str) -> Dict:
        """
        Extract metadata from cluster-backup with two-level VM detection.
        
        Iterates through all child backups and applies two-level detection to each.
        
        Args:
            backup_path: Full path to cluster-backup directory
            backup_uid: Cluster-backup UID
            
        Returns:
            Dict with metadata and scan_locations for all children with VMs
        """
        # Read cluster-backup.json
        cluster_backup_json_path = os.path.join(backup_path, 'cluster-backup.json')
        
        if not os.path.exists(cluster_backup_json_path):
            raise RuntimeError(f"cluster-backup.json not found at {cluster_backup_json_path}")
        
        try:
            with open(cluster_backup_json_path, 'r') as f:
                cluster_backup_json = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in cluster-backup.json: {str(e)}")
        
        # Extract cluster backup creation timestamp from metadata
        backup_creation_timestamp = cluster_backup_json.get('metadata', {}).get('creationTimestamp', '')
        
        # Read tvk-meta.json
        tvk_meta_path = os.path.join(backup_path, 'tvk-meta.json')
        
        if not os.path.exists(tvk_meta_path):
            raise RuntimeError(f"tvk-meta.json not found at {tvk_meta_path}")
        
        try:
            with open(tvk_meta_path, 'r') as f:
                tvk_meta = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in tvk-meta.json: {str(e)}")
        
        # Extract instance UID
        instance_id = tvk_meta.get('tvkInstanceUID')
        if not instance_id:
            raise RuntimeError("tvkInstanceUID not found in tvk-meta.json")
        
        self.logger.info(f"Extracted TVK instance UID: {instance_id}")
        
        # Parse path structure
        path_parts = backup_path.rstrip('/').split('/')
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
        
        # Get child backup infos
        backup_infos = cluster_backup_json.get('status', {}).get('backupInfos', {})
        
        self.logger.info(f"Cluster-backup has {len(backup_infos)} child backups")
        
        # Iterate through all child backups
        scan_locations = []
        
        for ns_name, info in backup_infos.items():
            child_location = info.get('location')
            if not child_location:
                self.logger.warning(f"Child backup '{ns_name}' has no location, skipping")
                continue
            
            child_backup_path = os.path.join('/triliodata', child_location)
            child_backup_uid = info.get('backup', {}).get('uid')
            
            if not child_backup_uid:
                self.logger.warning(f"Child backup '{ns_name}' has no UID, skipping")
                continue
            
            self.logger.info(f"Processing child backup in namespace '{ns_name}'")
            
            # Read child backup.json
            child_backup_json_path = os.path.join(child_backup_path, 'backup.json')
            
            if not os.path.exists(child_backup_json_path):
                self.logger.warning(f"  backup.json not found for child '{ns_name}', skipping")
                continue
            
            try:
                with open(child_backup_json_path, 'r') as f:
                    child_backup_json = json.load(f)
            except json.JSONDecodeError as e:
                self.logger.warning(f"  Failed to parse backup.json for child '{ns_name}': {str(e)}")
                continue
            except Exception as e:
                self.logger.warning(f"  Error reading backup.json for child '{ns_name}': {str(e)}")
                continue
            
            # LEVEL 1: Quick check for this child backup
            child_has_kubevirt = child_backup_json.get('status', {}).get('hasKubevirtResources', False)
            
            if not child_has_kubevirt:
                self.logger.info(
                    f"  Child backup '{ns_name}' has no kubevirt resources "
                    f"(hasKubevirtResources=false), skipping"
                )
                continue
            
            # LEVEL 2: Parse dataSnapshots for VM PVC map (grouped by VM)
            self.logger.info(
                f"  Child backup '{ns_name}' has kubevirt resources, parsing dataSnapshots"
            )
            
            vm_pvc_map = self._extract_vm_pvc_locations(child_backup_json)
            
            if len(vm_pvc_map) > 0:
                # Convert map to list of VM entries
                vms = []
                for vm_name, pvc_paths in vm_pvc_map.items():
                    vms.append({
                        'vm_name': vm_name,
                        'pvc_paths': pvc_paths
                    })
                
                # Add ScanLocation entry for this child backup
                scan_locations.append({
                    'namespace': ns_name,
                    'backup_uid': child_backup_uid,
                    'backup_path': child_location,
                    'vms': vms
                })
                
                total_pvcs = sum(len(pvc_paths) for pvc_paths in vm_pvc_map.values())
                self.logger.info(
                    f"  Added scan location for namespace '{ns_name}' with {len(vm_pvc_map)} VM(s) and {total_pvcs} PVC(s)"
                )
            else:
                self.logger.warning(
                    f"  Child backup '{ns_name}' has hasKubevirtResources=true "
                    f"but no VM PVCs found in dataSnapshots"
                )
        
        # Final determination: VM workload = true only if scan_locations is not empty
        is_vm_workload = len(scan_locations) > 0
        
        if is_vm_workload:
            self.logger.info(
                f"✓ Cluster-backup has VM workloads: {len(scan_locations)} child backup(s) with VMs"
            )
        else:
            self.logger.info(
                "✓ Cluster-backup has NO VM workloads to scan (all children filtered out)"
            )
        
        # Extract backup plan name from cluster-backup.json spec
        backupplan_name = cluster_backup_json.get('spec', {}).get('clusterBackupPlan', '')
        
        return {
            'instance_id': instance_id,
            'backupplan_uid': backupplan_uid,
            'backupplan_name': backupplan_name,
            'backup_uid': extracted_backup_uid,
            'backup_creation_timestamp': backup_creation_timestamp,
            'is_vm_workload': is_vm_workload,
            'is_cluster_backup': True,
            'scan_locations': scan_locations
        }
    
    def _extract_vm_pvc_locations(self, backup_json: Dict) -> Dict[str, list]:
        """
        Extract VM PVC information from backup.json dataSnapshots, grouped by VM.
        
        LEVEL 2 filtering:
        - Only processes PVCs owned by VirtualMachine resources
        - Filters out container PVCs (owned by StatefulSet, Deployment, etc.)
        - Returns dict mapping VM name to list of PVC paths
        
        For now, includes ALL VM PVCs (boot disk + data disks).
        Future: Will filter to include only boot disks.
        
        Args:
            backup_json: Parsed backup.json dict
            
        Returns:
            Dict mapping VM name to list of PVC paths:
            {
                'vm-test': [
                    'backupplan-uid/backup-uid/custom/data-snapshot/vol-boot',
                    'backupplan-uid/backup-uid/custom/data-snapshot/vol-data-1',
                    'backupplan-uid/backup-uid/custom/data-snapshot/vol-data-2'
                ],
                'vm-prod': [
                    'backupplan-uid/backup-uid/custom/data-snapshot/vol-prod-boot'
                ]
            }
        """
        data_snapshots = (
            backup_json.get('status', {})
            .get('snapshot', {})
            .get('custom', {})
            .get('dataSnapshots', [])
        )
        
        # Dict to group PVCs by VM name
        vm_pvc_map = {}
        
        for ds in data_snapshots:
            pvc_name = ds.get('persistentVolumeClaimName')
            location = ds.get('location')
            
            if not location:
                self.logger.warning(f"    DataSnapshot for PVC '{pvc_name}' has no location, skipping")
                continue
            
            # Check owner
            owner = ds.get('owner')
            
            if not owner:
                self.logger.debug(
                    f"    PVC '{pvc_name}' has no owner (standalone container PVC), skipping"
                )
                continue
            
            # Only process VirtualMachine owners
            owner_gvk = owner.get('groupVersionKind', {})
            owner_kind = owner_gvk.get('kind')
            owner_group = owner_gvk.get('group')
            
            if owner_kind != 'VirtualMachine' or owner_group != 'kubevirt.io':
                self.logger.debug(
                    f"    PVC '{pvc_name}' is owned by {owner_group}/{owner_kind} (not VM), skipping"
                )
                continue
            
            # This is a VM-owned PVC
            vm_name = owner.get('name', '')
            
            if not vm_name:
                self.logger.warning(f"    PVC '{pvc_name}' has VM owner but no name, skipping")
                continue
            
            # Add PVC path to this VM's list
            if vm_name not in vm_pvc_map:
                vm_pvc_map[vm_name] = []
            
            vm_pvc_map[vm_name].append(location)
            self.logger.info(f"    Found VM PVC: vm={vm_name}, pvc={pvc_name}")
        
        # Log summary
        for vm_name, pvc_paths in vm_pvc_map.items():
            self.logger.info(f"    VM '{vm_name}' has {len(pvc_paths)} PVC(s)")
        
        return vm_pvc_map
    
    def detect_vm_workload(self, backup_path: str) -> bool:
        """
        Detect if TVK backup contains VM workload.
        
        Reads backup.json and checks status.hasKubevirtResources field.
        
        Note: This method is kept for backward compatibility, but it's more
        efficient to call extract_metadata() which reads backup.json once.
        
        Args:
            backup_path: Full path to backup directory
            
        Returns:
            True if VM workload detected, False otherwise
        """
        backup_json_path = os.path.join(backup_path, 'backup.json')
        
        if not os.path.exists(backup_json_path):
            self.logger.info("backup.json not found, assuming not a VM workload")
            return False
        
        try:
            with open(backup_json_path, 'r') as f:
                backup_json = json.load(f)
            
            # Check status.hasKubevirtResources field
            has_kubevirt = backup_json.get('status', {}).get('hasKubevirtResources', False)
            
            if has_kubevirt:
                self.logger.info("VM workload detected: status.hasKubevirtResources is true")
            else:
                self.logger.info("Non-VM workload: status.hasKubevirtResources is false or not present")
            
            return has_kubevirt
            
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse backup.json: {str(e)}")
            return False
        except Exception as e:
            self.logger.warning(f"Error reading backup.json: {str(e)}")
            return False

