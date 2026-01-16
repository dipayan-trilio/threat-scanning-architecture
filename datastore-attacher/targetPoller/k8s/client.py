"""
Extended Kubernetes client for targetPoller.

Extends the shared K8s client with additional methods for ScanInstance creation.
"""

import uuid
import sys
import os
from typing import Dict, Optional

# Add parent directory to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Import shared K8s client
from shared.k8s.client import K8sClient as SharedK8sClient
from kubernetes.client.rest import ApiException

from mount_utility import logger

logging = logger.logger


class K8sClient(SharedK8sClient):
    """
    Extended K8s client with ScanInstance creation support.
    
    Extends the shared K8sClient with targetPoller-specific methods.
    """
    
    def create_scaninstance(
        self,
        backupplan_uid: str,
        backup_uid: str,
        backup_path: str,
        target_ref: Dict
    ) -> Optional[str]:
        """
        Create a ScanInstance CR.
        
        Args:
            backupplan_uid: BackupPlan UID
            backup_uid: Backup UID
            backup_path: Path to backup directory
            target_ref: Target CR reference dict
            
        Returns:
            Name of created ScanInstance or None on failure
            
        Example:
            scaninstance_name = client.create_scaninstance(
                backupplan_uid="abc-123",
                backup_uid="xyz-789",
                backup_path="/path/to/backup",
                target_ref={
                    'apiVersion': 'threatscanning.trilio.io/v1',
                    'kind': 'Target',
                    'name': 'backup-target',
                    'uid': '...',
                    'resourceVersion': '...'
                }
            )
        """
        # Generate unique name for ScanInstance
        scaninstance_name = str(uuid.uuid4())
        
        # Construct ScanInstance CR
        scaninstance_cr = {
            'apiVersion': f'{self.group}/{self.version}',
            'kind': 'ScanInstance',
            'metadata': {
                'name': scaninstance_name,
                'labels': {
                    # Only set backup-target label for filtering
                    # Prescan validation will enrich with all other labels:
                    #   - trilio.io/backupplan (parsed from backup path)
                    #   - trilio.io/backup (parsed from backup path)
                    #   - trilio.io/instance-id (from tvk-meta.json)
                    'trilio.io/backup-target': target_ref.get('name', '')
                }
            },
            'spec': {
                'backupTarget': {
                    'apiVersion': target_ref.get('apiVersion', f'{self.group}/{self.version}'),
                    'kind': target_ref.get('kind', 'Target'),
                    'name': target_ref.get('metadata', {}).get('name', ''),
                    'uid': target_ref.get('metadata', {}).get('uid', ''),
                    'resourceVersion': target_ref.get('metadata', {}).get('resourceVersion', '')
                },
                'backupRef': {
                    'uid': backup_uid,
                    'path': backup_path
                }
            }
        }
        
        try:
            result = self.custom_api.create_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.scaninstance_plural,
                body=scaninstance_cr
            )
            
            logging.info(
                f"Created ScanInstance: {scaninstance_name} "
                f"(backupplan: {backupplan_uid}, backup: {backup_uid})"
            )
            return scaninstance_name
            
        except ApiException as e:
            logging.error(
                f"Failed to create ScanInstance for backup {backup_uid}: {e.reason}",
                exc_info=True
            )
            return None
        except Exception as e:
            logging.error(
                f"Unexpected error creating ScanInstance for backup {backup_uid}: {str(e)}",
                exc_info=True
            )
            return None
    
    def delete_scaninstance(self, name: str) -> bool:
        """
        Delete ScanInstance CR by name.
        
        This is an alias to maintain compatibility with worker expectations.
        Calls the base class delete_scan_instance method.
        
        Args:
            name: Name of the ScanInstance CR
            
        Returns:
            True if deleted successfully or already deleted, False otherwise
        """
        return self.delete_scan_instance(name)


