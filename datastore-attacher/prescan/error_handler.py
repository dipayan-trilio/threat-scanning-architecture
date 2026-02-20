"""
Error handling utilities for prescan job.
"""

import os
import logging
from kubernetes import client, config

# Annotation constants
PRESCAN_ERROR_ANNOTATION = "threatscanning.trilio.io/prescan-error"
MAX_ERROR_SIZE = 128 * 1024  # 128KB max (Kubernetes annotation size limit)


def truncate_error_string(err_str: str, max_size: int = MAX_ERROR_SIZE) -> str:
    """
    Truncate error string to max annotation size.
    
    Args:
        err_str: Error string to truncate
        max_size: Maximum size in bytes (default: 128KB)
        
    Returns:
        Truncated error string with suffix if needed
    """
    if len(err_str) <= max_size:
        return err_str
    
    suffix = f"\n\n... [truncated, original size: {len(err_str)} bytes]"
    return err_str[:max_size - len(suffix)] + suffix


def update_job_error_annotation(job_name: str, job_namespace: str, error_msg: str) -> bool:
    """
    Update job annotation with error message.
    
    Automatically truncates error to fit within Kubernetes annotation size limit.
    
    Args:
        job_name: Name of the job
        job_namespace: Namespace of the job
        error_msg: Error message to store (will be truncated if too large)
        
    Returns:
        True if update succeeded, False otherwise
    """
    try:
        # Load in-cluster config
        config.load_incluster_config()
        batch_api = client.BatchV1Api()
        
        # Get the job
        job = batch_api.read_namespaced_job(job_name, job_namespace)
        
        # Ensure annotations dict exists
        if job.metadata.annotations is None:
            job.metadata.annotations = {}
        
        # Truncate error message to fit annotation size limit
        truncated_error = truncate_error_string(error_msg)
        job.metadata.annotations[PRESCAN_ERROR_ANNOTATION] = truncated_error
        
        # Update the job
        batch_api.patch_namespaced_job(
            name=job_name,
            namespace=job_namespace,
            body=job
        )
        
        logging.info(f"✓ Updated job {job_name} with error annotation ({len(truncated_error)} bytes)")
        return True
        
    except Exception as e:
        logging.error(f"Failed to update job annotation: {e}")
        return False
