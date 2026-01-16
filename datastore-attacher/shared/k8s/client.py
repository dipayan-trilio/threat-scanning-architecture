"""
Base Kubernetes client for threat scanning service.

Provides common K8s operations for ScanInstance and Target CRs.
"""

from typing import Dict, List, Optional
from kubernetes import client, config
from kubernetes.client.rest import ApiException


class K8sClient:
    """
    Base Kubernetes client for threat scanning CRDs.
    
    Handles:
    - Target CR operations
    - ScanInstance CR operations (list, get, delete, patch)
    """
    
    def __init__(
        self,
        group: str = 'threatscanning.trilio.io',
        version: str = 'v1',
        target_plural: str = 'targets',
        scaninstance_plural: str = 'scaninstances'
    ):
        """
        Initialize K8s client.
        
        Args:
            group: CRD API group
            version: CRD API version
            target_plural: Plural name for Target CRD
            scaninstance_plural: Plural name for ScanInstance CRD
        """
        # Load kubeconfig
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        
        self.custom_api = client.CustomObjectsApi()
        self.core_api = client.CoreV1Api()
        
        self.group = group
        self.version = version
        self.target_plural = target_plural
        self.scaninstance_plural = scaninstance_plural
    
    # ============= Target Operations =============
    
    def get_target(self, name: str) -> Optional[Dict]:
        """
        Get Target CR by name.
        
        Args:
            name: Name of the Target CR
            
        Returns:
            Target CR dict or None if not found
        """
        try:
            return self.custom_api.get_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.target_plural,
                name=name
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise
    
    def list_targets(self, label_selector: Optional[str] = None) -> List[Dict]:
        """
        List all Target CRs.
        
        Args:
            label_selector: Optional label selector (e.g., "trilio.io/reporting-target=true")
            
        Returns:
            List of Target CR dicts
        """
        try:
            result = self.custom_api.list_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.target_plural,
                label_selector=label_selector
            )
            return result.get('items', [])
        except ApiException:
            return []
    
    # ============= ScanInstance Operations =============
    
    def get_scan_instance(self, name: str) -> Optional[Dict]:
        """
        Get ScanInstance CR by name.
        
        Args:
            name: Name of the ScanInstance CR
            
        Returns:
            ScanInstance CR dict or None if not found
        """
        try:
            return self.custom_api.get_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.scaninstance_plural,
                name=name
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise
    
    def list_scan_instances(self, label_selector: Optional[str] = None) -> List[Dict]:
        """
        List ScanInstance CRs.
        
        Args:
            label_selector: Optional label selector
            
        Returns:
            List of ScanInstance CR dicts
        """
        try:
            result = self.custom_api.list_cluster_custom_object(
                group=self.group,
                version=self.version,
                plural=self.scaninstance_plural,
                label_selector=label_selector
            )
            return result.get('items', [])
        except ApiException:
            return []
    
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
            return True
        except ApiException as e:
            if e.status == 404:
                # Already deleted
                return True
            return False
    
    def patch_scan_instance(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None,
        status: Optional[Dict] = None
    ) -> bool:
        """
        Patch ScanInstance CR with labels, annotations, or status.
        
        Args:
            name: Name of the ScanInstance CR
            labels: Labels to add/update
            annotations: Annotations to add/update
            status: Status fields to update
            
        Returns:
            True if patched successfully, False otherwise
        """
        try:
            patch_body = {}
            
            # Build patch for metadata
            if labels or annotations:
                patch_body['metadata'] = {}
                if labels:
                    patch_body['metadata']['labels'] = labels
                if annotations:
                    patch_body['metadata']['annotations'] = annotations
            
            # Patch metadata if needed
            if patch_body:
                self.custom_api.patch_cluster_custom_object(
                    group=self.group,
                    version=self.version,
                    plural=self.scaninstance_plural,
                    name=name,
                    body=patch_body
                )
            
            # Patch status separately if needed
            if status:
                self.custom_api.patch_cluster_custom_object_status(
                    group=self.group,
                    version=self.version,
                    plural=self.scaninstance_plural,
                    name=name,
                    body={'status': status}
                )
            
            return True
            
        except ApiException as e:
            print(f"Failed to patch ScanInstance {name}: {e.reason}")
            return False

