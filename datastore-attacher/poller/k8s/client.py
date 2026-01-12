"""
Kubernetes API client for ScanInstance and Target CR operations.
"""

import os
import sys
from typing import List, Dict, Optional

# Add parent directory to path to import mount_utility
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from mount_utility import constants
from mount_utility import logger

logging = logger.logger


class K8sClient:
    """
    Kubernetes API client with support for both custom objects and core resources.
    Handles ScanInstance CRs, Target CRs, Secrets, and ConfigMaps.
    """
    
    def __init__(self):
        """Initialize Kubernetes client."""
        # Load in-cluster config (running in pod) or kubeconfig (local dev)
        try:
            if constants.VM_MOUNT in os.environ:
                config.load_kube_config()
                logging.info("Loaded kubeconfig for local development")
            else:
                config.load_incluster_config()
                logging.info("Loaded in-cluster Kubernetes config")
        except config.ConfigException as e:
            logging.error(f"Failed to load Kubernetes config: {str(e)}")
            raise
        
        # API clients
        self.custom_api = client.CustomObjectsApi()
        self.core_v1_api = client.CoreV1Api()
        self.batch_v1_api = client.BatchV1Api()
        
        # Custom resource details
        self.group = constants.TVK_CRD_GROUP
        self.version = constants.TVK_CRD_VERSION
        self.scaninstance_plural = 'scaninstances'
        self.target_plural = constants.TARGET_CRD_PLURAL
        
        logging.info(
            f"Initialized K8s client for group {self.group}/{self.version}"
        )
    
    # ============= ScanInstance Operations =============
    
    def list_scan_instances(self, label_selector: Optional[str] = None) -> List[Dict]:
        """
        List ScanInstance CRs with optional label selector.
        
        Args:
            label_selector: K8s label selector (e.g., "target-uid=abc-123")
            
        Returns:
            List of ScanInstance CR dictionaries
            
        Example:
            # List all ScanInstances for a target
            scan_instances = client.list_scan_instances(
                label_selector="target-uid=abc-123"
            )
            
            # List all ScanInstances for a backupplan
            scan_instances = client.list_scan_instances(
                label_selector="backupplan-uid=xyz-789"
            )
        """
        try:
            result = self.custom_api.list_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.scaninstance_plural,
                label_selector=label_selector
            )
            items = result.get('items', [])
            logging.debug(
                f"Listed {len(items)} ScanInstances "
                f"(label_selector: {label_selector or 'none'})"
            )
            return items
            
        except ApiException as e:
            if e.status == 404:
                # CRD might not exist yet
                logging.warning("ScanInstance CRD not found (404)")
                return []
            logging.error(f"Failed to list ScanInstances: {e.reason}")
            raise
    
    def delete_scan_instance(self, name: str) -> bool:
        """
        Delete ScanInstance CR by name.
        
        Args:
            name: Name of the ScanInstance CR
            
        Returns:
            True if deleted successfully or already deleted, False otherwise
        """
        try:
            self.custom_api.delete_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.scaninstance_plural,
                name=name
            )
            logging.debug(f"Deleted ScanInstance: {name}")
            return True
            
        except ApiException as e:
            if e.status == 404:
                # Already deleted
                logging.debug(f"ScanInstance {name} already deleted (404)")
                return True
            logging.error(f"Failed to delete ScanInstance {name}: {e.reason}")
            return False
    
    # ============= Target Operations =============
    
    def get_target(self, name: str) -> Optional[Dict]:
        """
        Get Target CR by name.
        
        Args:
            name: Name of the Target CR
            
        Returns:
            Target CR dictionary or None if not found
        """
        try:
            target = self.custom_api.get_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.target_plural,
                name=name
            )
            logging.debug(f"Retrieved Target: {name}")
            return target
            
        except ApiException as e:
            if e.status == 404:
                logging.warning(f"Target {name} not found (404)")
                return None
            logging.error(f"Failed to get Target {name}: {e.reason}")
            raise
    
    def list_targets(self, label_selector: Optional[str] = None) -> List[Dict]:
        """
        List Target CRs with optional label selector.
        
        Args:
            label_selector: K8s label selector
            
        Returns:
            List of Target CR dictionaries
            
        Example:
            # List all reporting targets
            targets = client.list_targets(
                label_selector="trilio.io/reporting-target=true"
            )
        """
        try:
            result = self.custom_api.list_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.target_plural,
                label_selector=label_selector
            )
            items = result.get('items', [])
            logging.debug(
                f"Listed {len(items)} Targets "
                f"(label_selector: {label_selector or 'none'})"
            )
            return items
            
        except ApiException as e:
            if e.status == 404:
                logging.warning("Target CRD not found (404)")
                return []
            logging.error(f"Failed to list Targets: {e.reason}")
            raise
    
    # ============= CronJob Operations =============
    
    def get_cronjob(self, name: str, namespace: str = 'default') -> Optional[Dict]:
        """
        Get CronJob by name.
        
        Args:
            name: Name of the CronJob
            namespace: Namespace of the CronJob (default: 'default')
            
        Returns:
            CronJob dictionary or None if not found
        """
        try:
            cronjob = self.batch_v1_api.read_namespaced_cron_job(
                name=name,
                namespace=namespace
            )
            # Convert to dict
            cronjob_dict = cronjob.to_dict()
            logging.debug(f"Retrieved CronJob: {name} in namespace {namespace}")
            return cronjob_dict
            
        except ApiException as e:
            if e.status == 404:
                logging.warning(f"CronJob {name} not found in namespace {namespace} (404)")
                return None
            logging.error(f"Failed to get CronJob {name}: {e.reason}")
            raise

