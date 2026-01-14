"""
Queue workers for async processing of cleanup and creation tasks.

Uses Python's queue.Queue and threading for parallel processing.
"""

import threading
import queue
import time
from typing import Optional

# Add parent directory to path for imports
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from mount_utility import logger

logging = logger.logger


class CleanupWorker(threading.Thread):
    """
    Worker thread that processes ScanInstance cleanup requests.
    
    Consumes CleanupMessage objects from the cleanup queue and deletes
    the corresponding ScanInstance CRs.
    """
    
    def __init__(self, worker_id: int, cleanup_queue: queue.Queue, k8s_client, stop_event: threading.Event):
        """
        Initialize cleanup worker.
        
        Args:
            worker_id: Unique ID for this worker
            cleanup_queue: Queue containing CleanupMessage objects
            k8s_client: Kubernetes client for deleting ScanInstances
            stop_event: Event to signal worker to stop
        """
        super().__init__(name=f"CleanupWorker-{worker_id}", daemon=True)
        self.worker_id = worker_id
        self.cleanup_queue = cleanup_queue
        self.k8s_client = k8s_client
        self.stop_event = stop_event
        self.processed_count = 0
        self.error_count = 0
        
    def run(self):
        """Main worker loop"""
        logging.info(f"CleanupWorker-{self.worker_id} started")
        
        while not self.stop_event.is_set():
            try:
                # Wait for message with timeout to check stop_event periodically
                try:
                    message = self.cleanup_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Process the cleanup message
                self._process_cleanup(message)
                
                # Mark task as done
                self.cleanup_queue.task_done()
                
            except Exception as e:
                logging.error(f"CleanupWorker-{self.worker_id} error: {str(e)}", exc_info=True)
                self.error_count += 1
        
        logging.info(
            f"CleanupWorker-{self.worker_id} stopped. "
            f"Processed: {self.processed_count}, Errors: {self.error_count}"
        )
    
    def _process_cleanup(self, message):
        """Process a single cleanup message"""
        try:
            logging.info(
                f"[Worker-{self.worker_id}] Deleting ScanInstance: {message.scaninstance_name}"
            )
            
            # Delete the ScanInstance CR
            success = self.k8s_client.delete_scaninstance(message.scaninstance_name)
            
            if success:
                self.processed_count += 1
                logging.info(
                    f"[Worker-{self.worker_id}] ✓ Deleted ScanInstance: {message.scaninstance_name}"
                )
            else:
                self.error_count += 1
                logging.warning(
                    f"[Worker-{self.worker_id}] ✗ Failed to delete ScanInstance: {message.scaninstance_name}"
                )
                
        except Exception as e:
            self.error_count += 1
            logging.error(
                f"[Worker-{self.worker_id}] Error deleting {message.scaninstance_name}: {str(e)}",
                exc_info=True
            )


class CreationWorker(threading.Thread):
    """
    Worker thread that processes ScanInstance creation requests.
    
    Consumes CreationMessage objects from the creation queue and creates
    the corresponding ScanInstance CRs.
    """
    
    def __init__(self, worker_id: int, creation_queue: queue.Queue, k8s_client, target_cr: dict, stop_event: threading.Event):
        """
        Initialize creation worker.
        
        Args:
            worker_id: Unique ID for this worker
            creation_queue: Queue containing CreationMessage objects
            k8s_client: Kubernetes client for creating ScanInstances
            target_cr: Target CR dict for reference in ScanInstance spec
            stop_event: Event to signal worker to stop
        """
        super().__init__(name=f"CreationWorker-{worker_id}", daemon=True)
        self.worker_id = worker_id
        self.creation_queue = creation_queue
        self.k8s_client = k8s_client
        self.target_cr = target_cr
        self.stop_event = stop_event
        self.processed_count = 0
        self.error_count = 0
        
    def run(self):
        """Main worker loop"""
        logging.info(f"CreationWorker-{self.worker_id} started")
        
        while not self.stop_event.is_set():
            try:
                # Wait for message with timeout to check stop_event periodically
                try:
                    message = self.creation_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Process the creation message
                self._process_creation(message)
                
                # Mark task as done
                self.creation_queue.task_done()
                
            except Exception as e:
                logging.error(f"CreationWorker-{self.worker_id} error: {str(e)}", exc_info=True)
                self.error_count += 1
        
        logging.info(
            f"CreationWorker-{self.worker_id} stopped. "
            f"Processed: {self.processed_count}, Errors: {self.error_count}"
        )
    
    def _process_creation(self, message):
        """Process a single creation message"""
        try:
            logging.info(
                f"[Worker-{self.worker_id}] Creating ScanInstance for backup: {message.backup_uid}"
            )
            
            # Create the ScanInstance CR
            scaninstance_name = self.k8s_client.create_scaninstance(
                backupplan_uid=message.backupplan_uid,
                backup_uid=message.backup_uid,
                backup_path=message.backup_path,
                target_ref=self.target_cr
            )
            
            if scaninstance_name:
                self.processed_count += 1
                logging.info(
                    f"[Worker-{self.worker_id}] ✓ Created ScanInstance: {scaninstance_name} "
                    f"for backup {message.backup_uid}"
                )
            else:
                self.error_count += 1
                logging.warning(
                    f"[Worker-{self.worker_id}] ✗ Failed to create ScanInstance for backup: {message.backup_uid}"
                )
                
        except Exception as e:
            self.error_count += 1
            logging.error(
                f"[Worker-{self.worker_id}] Error creating ScanInstance for {message.backup_uid}: {str(e)}",
                exc_info=True
            )


class WorkerPool:
    """
    Manages a pool of worker threads for processing queues.
    """
    
    def __init__(self, num_workers: int = 3):
        """
        Initialize worker pool.
        
        Args:
            num_workers: Maximum number of worker threads (default: 3)
        """
        self.num_workers = num_workers
        self.cleanup_queue = queue.Queue()
        self.creation_queue = queue.Queue()
        self.cleanup_workers = []
        self.creation_workers = []
        self.stop_event = threading.Event()
        
    def start_cleanup_workers(self, k8s_client):
        """Start cleanup worker threads"""
        logging.info(f"Starting {self.num_workers} cleanup workers...")
        
        for i in range(self.num_workers):
            worker = CleanupWorker(
                worker_id=i+1,
                cleanup_queue=self.cleanup_queue,
                k8s_client=k8s_client,
                stop_event=self.stop_event
            )
            worker.start()
            self.cleanup_workers.append(worker)
        
        logging.info(f"✓ Started {len(self.cleanup_workers)} cleanup workers")
    
    def start_creation_workers(self, k8s_client, target_cr: dict):
        """Start creation worker threads"""
        logging.info(f"Starting {self.num_workers} creation workers...")
        
        for i in range(self.num_workers):
            worker = CreationWorker(
                worker_id=i+1,
                creation_queue=self.creation_queue,
                k8s_client=k8s_client,
                target_cr=target_cr,
                stop_event=self.stop_event
            )
            worker.start()
            self.creation_workers.append(worker)
        
        logging.info(f"✓ Started {len(self.creation_workers)} creation workers")
    
    def start_all_workers(self, k8s_client, target_cr: dict):
        """Start both cleanup and creation workers"""
        self.start_cleanup_workers(k8s_client)
        self.start_creation_workers(k8s_client, target_cr)
    
    def wait_for_cleanup_completion(self, timeout: Optional[int] = None):
        """Wait for all cleanup tasks to complete"""
        logging.info("Waiting for cleanup queue to finish...")
        self.cleanup_queue.join()
        logging.info("✓ Cleanup queue processing complete")
    
    def wait_for_creation_completion(self, timeout: Optional[int] = None):
        """Wait for all creation tasks to complete"""
        logging.info("Waiting for creation queue to finish...")
        self.creation_queue.join()
        logging.info("✓ Creation queue processing complete")
    
    def wait_for_all_completion(self, timeout: Optional[int] = None):
        """Wait for both queues to complete"""
        self.wait_for_cleanup_completion(timeout)
        self.wait_for_creation_completion(timeout)
    
    def stop_all_workers(self):
        """Stop all worker threads"""
        logging.info("Stopping all workers...")
        self.stop_event.set()
        
        # Wait for workers to finish current tasks
        for worker in self.cleanup_workers + self.creation_workers:
            worker.join(timeout=5.0)
        
        logging.info("✓ All workers stopped")
    
    def get_stats(self) -> dict:
        """Get statistics from all workers"""
        cleanup_processed = sum(w.processed_count for w in self.cleanup_workers)
        cleanup_errors = sum(w.error_count for w in self.cleanup_workers)
        creation_processed = sum(w.processed_count for w in self.creation_workers)
        creation_errors = sum(w.error_count for w in self.creation_workers)
        
        return {
            'cleanup': {
                'processed': cleanup_processed,
                'errors': cleanup_errors,
                'queue_size': self.cleanup_queue.qsize()
            },
            'creation': {
                'processed': creation_processed,
                'errors': creation_errors,
                'queue_size': self.creation_queue.qsize()
            }
        }


