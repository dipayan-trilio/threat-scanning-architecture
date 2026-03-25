#!/usr/bin/env python3
"""
Integration tests for targetPoller cleanup using envtest-style approach.

This test suite starts real Kubernetes API server and etcd BINARIES directly,
exactly like controller-runtime's envtest (NO kind, NO Docker required).

Approach:
1. Download kube-apiserver and etcd binaries (via setup-envtest)
2. Start etcd process
3. Start kube-apiserver process pointing to etcd
4. Install threat-scanning CRDs
5. Create real Target and ScanInstance CRs
6. Run poller cleanup
7. Verify ScanInstances are actually deleted via K8s API
8. Stop processes and cleanup

This provides:
- Real K8s API behavior (not mocked)
- Real CR lifecycle (create, list, delete)
- Real API errors (404, 403, etc.)
- No Docker/kind needed (just binaries)
- Same approach as Go controller tests
"""

import unittest
import subprocess
import time
import tempfile
import os
import yaml
import sys
import signal
import json
from pathlib import Path

# pytest markers
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from targetPoller.k8s.client import K8sClient
from targetPoller.handlers.base_handler import BaseTargetHandler
from targetPoller.models.storage_state import StorageState, BackupObject, BackupType
from datetime import datetime


class EnvTestSetup:
    """
    Manages envtest-style test environment.
    
    Starts kube-apiserver and etcd binaries directly (like Go envtest).
    NO Docker, NO kind required - just the binaries.
    """
    
    def __init__(self):
        self.etcd_process = None
        self.apiserver_process = None
        self.kubeconfig_path = None
        self.etcd_data_dir = None
        self.etcd_port = 2379
        self.etcd_peer_port = 2380
        self.apiserver_port = 8080
        self.apiserver_secure_port = 6443
        self.binaries_dir = None
        self.running = False
    
    def _find_envtest_binaries(self) -> str:
        """
        Find kubebuilder-envtest binaries.
        
        Looks in:
        1. KUBEBUILDER_ASSETS env var
        2. ~/.local/share/kubebuilder-envtest/
        3. /usr/local/kubebuilder/bin/
        
        Returns path to directory containing kube-apiserver and etcd binaries.
        """
        
        # Check KUBEBUILDER_ASSETS
        if 'KUBEBUILDER_ASSETS' in os.environ:
            path = Path(os.environ['KUBEBUILDER_ASSETS'])
            if path.exists() and (path / 'kube-apiserver').exists():
                return str(path)
        
        # Check ~/.local/share/kubebuilder-envtest/
        home = Path.home()
        envtest_dir = home / '.local' / 'share' / 'kubebuilder-envtest' / 'k8s'
        if envtest_dir.exists():
            # Find latest version
            versions = sorted(envtest_dir.glob('*'))
            if versions:
                latest = versions[-1]
                for platform in latest.glob('*'):
                    if (platform / 'kube-apiserver').exists():
                        return str(platform)
        
        # Check /usr/local/kubebuilder/bin/
        kubebuilder_bin = Path('/usr/local/kubebuilder/bin')
        if kubebuilder_bin.exists() and (kubebuilder_bin / 'kube-apiserver').exists():
            return str(kubebuilder_bin)
        
        return None
    
    def _download_binaries(self):
        """Download envtest binaries using setup-envtest"""
        print("Downloading envtest binaries (first time setup)...")
        print("  This may take a minute...")
        
        # Try to install setup-envtest if not present
        try:
            result = subprocess.run(
                ['setup-envtest', 'use', '--bin-dir', os.path.expanduser('~/.local/share/kubebuilder-envtest')],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"setup-envtest failed: {result.stderr}")
            
            # Parse output to find binary path
            for line in result.stdout.split('\n'):
                if 'KUBEBUILDER_ASSETS' in line or '/bin' in line:
                    print(f"  {line}")
            
            # Try to find binaries again
            self.binaries_dir = self._find_envtest_binaries()
            
            if self.binaries_dir:
                print(f"  ✓ Binaries ready at {self.binaries_dir}")
            else:
                raise RuntimeError("Failed to locate binaries after setup-envtest")
        
        except FileNotFoundError:
            raise RuntimeError(
                "setup-envtest not found. Install with:\n"
                "  go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest\n"
                "  OR set KUBEBUILDER_ASSETS to path containing kube-apiserver and etcd binaries"
            )
    
    def setup(self):
        """Set up test environment"""
        print(f"\n{'='*60}")
        print("Setting up envtest environment (API server + etcd binaries)...")
        print(f"{'='*60}\n")
        
        # Find or download binaries
        self.binaries_dir = self._find_envtest_binaries()
        if not self.binaries_dir:
            self._download_binaries()
        else:
            print(f"Using binaries from: {self.binaries_dir}")
        
        # Create temp directory for etcd data
        self.etcd_data_dir = tempfile.mkdtemp(prefix='envtest-etcd-')
        
        # Start etcd
        self._start_etcd()
        
        # Start API server
        self._start_apiserver()
        
        # Wait for API server to be ready
        self._wait_for_apiserver()
        
        # Install CRDs
        self._install_crds()
        
        self.running = True
        
        print(f"\n{'='*60}")
        print("✓ Environment ready (API server + etcd running)")
        print(f"{'='*60}\n")
    
    def teardown(self):
        """Tear down test environment"""
        if self.running:
            print(f"\n{'='*60}")
            print("Tearing down envtest environment...")
            print(f"{'='*60}\n")
            
            self._stop_processes()
            self._cleanup_dirs()
            
            print("✓ Environment cleaned up\n")
            
            self.running = False
    
    def _start_etcd(self):
        """Start etcd process"""
        print("Starting etcd...")
        
        etcd_bin = Path(self.binaries_dir) / 'etcd'
        if not etcd_bin.exists():
            raise RuntimeError(f"etcd binary not found at {etcd_bin}")
        
        # Start etcd in standalone mode (no clustering)
        self.etcd_process = subprocess.Popen(
            [
                str(etcd_bin),
                f'--data-dir={self.etcd_data_dir}',
                f'--listen-client-urls=http://127.0.0.1:{self.etcd_port}',
                f'--advertise-client-urls=http://127.0.0.1:{self.etcd_port}',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # Create new process group
        )
        
        # Wait for etcd to be ready
        time.sleep(2)
        
        poll_result = self.etcd_process.poll()
        
        if poll_result is not None:
            _, stderr_bytes = self.etcd_process.communicate()
            stderr_output = stderr_bytes.decode() if stderr_bytes else ""
            raise RuntimeError(f"etcd failed to start: {stderr_output}")
        
        print(f"  ✓ etcd started (PID: {self.etcd_process.pid}, port: {self.etcd_port})")
        
        # Test etcd connectivity
        print("  Testing etcd connectivity...")
        try:
            import requests
            response = requests.get(f'http://127.0.0.1:{self.etcd_port}/version', timeout=2)
            print(f"  ✓ etcd responding: {response.status_code}")
        except Exception as e:
            print(f"  ⚠ etcd health check failed (will retry): {e}")
    
    def _start_apiserver(self):
        """Start kube-apiserver process"""
        print("Starting kube-apiserver...")
        
        apiserver_bin = Path(self.binaries_dir) / 'kube-apiserver'
        if not apiserver_bin.exists():
            raise RuntimeError(f"kube-apiserver binary not found at {apiserver_bin}")
        
        # Create temp dir for certs
        cert_dir = tempfile.mkdtemp(prefix='envtest-certs-')
        self.cert_dir = cert_dir
        
        # Generate client certificates for authentication
        print("  Generating certificates...")
        
        # 1. Create CA key and cert
        ca_key = os.path.join(cert_dir, 'ca.key')
        ca_crt = os.path.join(cert_dir, 'ca.crt')
        subprocess.run(
            ['openssl', 'genrsa', '-out', ca_key, '2048'],
            capture_output=True, check=True
        )
        subprocess.run(
            ['openssl', 'req', '-x509', '-new', '-nodes', '-key', ca_key,
             '-subj', '/CN=kubernetes-ca', '-days', '365', '-out', ca_crt],
            capture_output=True, check=True
        )
        
        # 2. Create API server key and cert with SANs for 127.0.0.1
        apiserver_key = os.path.join(cert_dir, 'apiserver.key')
        apiserver_crt = os.path.join(cert_dir, 'apiserver.crt')
        apiserver_csr = os.path.join(cert_dir, 'apiserver.csr')
        
        # Create OpenSSL config for SANs
        openssl_cnf = os.path.join(cert_dir, 'openssl.cnf')
        with open(openssl_cnf, 'w') as f:
            f.write("""[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[req_distinguished_name]
[v3_req]
subjectAltName = @alt_names
[alt_names]
DNS.1 = kubernetes
DNS.2 = kubernetes.default
DNS.3 = kubernetes.default.svc
DNS.4 = kubernetes.default.svc.cluster.local
DNS.5 = localhost
IP.1 = 127.0.0.1
IP.2 = 10.0.0.1
""")
        
        subprocess.run(
            ['openssl', 'genrsa', '-out', apiserver_key, '2048'],
            capture_output=True, check=True
        )
        subprocess.run(
            ['openssl', 'req', '-new', '-key', apiserver_key,
             '-subj', '/CN=kube-apiserver', '-out', apiserver_csr,
             '-config', openssl_cnf],
            capture_output=True, check=True
        )
        subprocess.run(
            ['openssl', 'x509', '-req', '-in', apiserver_csr, '-CA', ca_crt,
             '-CAkey', ca_key, '-CAcreateserial', '-out', apiserver_crt,
             '-days', '365', '-extensions', 'v3_req', '-extfile', openssl_cnf],
            capture_output=True, check=True
        )
        
        # 3. Create client key and cert
        client_key = os.path.join(cert_dir, 'client.key')
        client_crt = os.path.join(cert_dir, 'client.crt')
        client_csr = os.path.join(cert_dir, 'client.csr')
        
        subprocess.run(
            ['openssl', 'genrsa', '-out', client_key, '2048'],
            capture_output=True, check=True
        )
        subprocess.run(
            ['openssl', 'req', '-new', '-key', client_key,
             '-subj', '/CN=client/O=system:masters', '-out', client_csr],
            capture_output=True, check=True
        )
        subprocess.run(
            ['openssl', 'x509', '-req', '-in', client_csr, '-CA', ca_crt,
             '-CAkey', ca_key, '-CAcreateserial', '-out', client_crt, '-days', '365'],
            capture_output=True, check=True
        )
        
        # 4. Create service account key file (required)
        sa_key_file = os.path.join(cert_dir, 'sa.key')
        subprocess.run(
            ['openssl', 'genrsa', '-out', sa_key_file, '2048'],
            capture_output=True, check=True
        )
        
        # Store paths for kubeconfig
        self.client_cert = client_crt
        self.client_key = client_key
        self.ca_cert = ca_crt
        
        # Build API server command
        apiserver_cmd = [
            str(apiserver_bin),
            f'--etcd-servers=http://127.0.0.1:{self.etcd_port}',
            '--cert-dir=' + cert_dir,
            f'--tls-cert-file={apiserver_crt}',  # Use our generated cert with SANs
            f'--tls-private-key-file={apiserver_key}',
            '--service-cluster-ip-range=10.0.0.0/24',
            f'--secure-port={self.apiserver_secure_port}',
            '--authorization-mode=AlwaysAllow',  # Allow all requests for testing
            f'--client-ca-file={ca_crt}',  # Trust our CA for client certs
            '--disable-admission-plugins=ServiceAccount',
            f'--service-account-key-file={sa_key_file}',
            f'--service-account-signing-key-file={sa_key_file}',
            '--service-account-issuer=https://kubernetes.default.svc',
        ]
        
        print(f"  Command: {' '.join(apiserver_cmd[:3])}...")
        print(f"  Ports: etcd={self.etcd_port}, apiserver-secure={self.apiserver_secure_port}")
        
        # Start API server
        self.apiserver_process = subprocess.Popen(
            apiserver_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        
        # Don't wait too long - we'll check readiness separately
        time.sleep(1)
        
        if self.apiserver_process.poll() is not None:
            _, stderr = self.apiserver_process.communicate()
            print(f"  ✗ API server exited immediately!")
            print(f"  stderr output:\n{stderr.decode()}")
            raise RuntimeError(f"kube-apiserver failed to start: {stderr.decode()}")
        
        print(f"  ✓ kube-apiserver process started (PID: {self.apiserver_process.pid}, port: {self.apiserver_secure_port})")
        
        # Create kubeconfig
        self._create_kubeconfig()
        print(f"  ✓ kubeconfig created at {self.kubeconfig_path}")
    
    def _wait_for_apiserver(self):
        """Wait for API server to be ready"""
        print("Waiting for API server to be ready...")
        
        # First check if API server process is still running
        poll_result = self.apiserver_process.poll()
        if poll_result is not None:
            print(f"  ✗ API server process exited with code {poll_result}")
            # Try to get stderr output
            try:
                stderr_output = self.apiserver_process.stderr.read().decode()
                print(f"  API server stderr:\n{stderr_output[:1000]}")
            except:
                pass
            raise RuntimeError(f"API server process died with exit code {poll_result}")
        
        print(f"  API server process running (PID: {self.apiserver_process.pid})")
        print(f"  Kubeconfig: {self.kubeconfig_path}")
        print(f"  Server URL: https://127.0.0.1:{self.apiserver_secure_port}")
        
        max_attempts = 30
        for i in range(max_attempts):
            try:
                result = subprocess.run(
                    ['kubectl', '--kubeconfig', self.kubeconfig_path, 'get', '--raw', '/healthz'],
                    capture_output=True,
                    timeout=2
                )
                
                print(f"  Attempt {i+1}/{max_attempts}: kubectl returned code {result.returncode}")
                if result.stdout:
                    print(f"    stdout: {result.stdout.decode()[:100]}")
                if result.stderr:
                    print(f"    stderr: {result.stderr.decode()[:200]}")
                
                if result.returncode == 0 and b'ok' in result.stdout:
                    print(f"  ✓ API server ready (attempt {i+1}/{max_attempts})")
                    return
            except subprocess.TimeoutExpired:
                print(f"  Attempt {i+1}/{max_attempts}: kubectl timeout")
                pass
            except Exception as e:
                print(f"  Attempt {i+1}/{max_attempts}: kubectl error: {e}")
                pass
            
            time.sleep(1)
        
        # Final check - is API server still running?
        poll_result = self.apiserver_process.poll()
        if poll_result is not None:
            print(f"  ✗ API server process exited during wait (code {poll_result})")
        else:
            print(f"  ✗ API server process still running but not responding")
        
        raise RuntimeError("API server failed to become ready")
    
    def _create_kubeconfig(self):
        """Create kubeconfig for test cluster"""
        kubeconfig = {
            'apiVersion': 'v1',
            'kind': 'Config',
            'clusters': [{
                'cluster': {
                    'server': f'https://127.0.0.1:{self.apiserver_secure_port}',
                    'certificate-authority': self.ca_cert,  # Use our CA cert
                },
                'name': 'envtest'
            }],
            'contexts': [{
                'context': {
                    'cluster': 'envtest',
                    'user': 'envtest'
                },
                'name': 'envtest'
            }],
            'current-context': 'envtest',
            'users': [{
                'name': 'envtest',
                'user': {
                    'client-certificate': self.client_cert,  # Client cert for auth
                    'client-key': self.client_key,  # Client key for auth
                }
            }]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as f:
            yaml.dump(kubeconfig, f)
            self.kubeconfig_path = f.name
        
        # Set KUBECONFIG
        os.environ['KUBECONFIG'] = self.kubeconfig_path
        print(f"  ✓ KUBECONFIG created at {self.kubeconfig_path}")
    
    def _stop_processes(self):
        """Stop etcd and API server processes"""
        print("Stopping processes...")
        
        for process, name in [
            (self.apiserver_process, 'kube-apiserver'),
            (self.etcd_process, 'etcd')
        ]:
            if process and process.poll() is None:
                try:
                    # Kill process group
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    process.wait(timeout=5)
                    print(f"  ✓ Stopped {name}")
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    print(f"  ✓ Killed {name}")
                except ProcessLookupError:
                    print(f"  ℹ {name} already stopped")
    
    def _cleanup_dirs(self):
        """Clean up temporary directories"""
        # Clean up kubeconfig
        if self.kubeconfig_path and os.path.exists(self.kubeconfig_path):
            os.remove(self.kubeconfig_path)
        
        # Clean up etcd data dir
        if self.etcd_data_dir and os.path.exists(self.etcd_data_dir):
            import shutil
            shutil.rmtree(self.etcd_data_dir, ignore_errors=True)
    
    def _install_crds(self):
        """Install threat-scanning CRDs"""
        print("Installing CRDs...")
        
        # Find CRD directory
        project_root = Path(__file__).parent.parent.parent.parent
        crd_dir = project_root / 'config' / 'crd' / 'bases'
        
        if not crd_dir.exists():
            raise RuntimeError(f"CRD directory not found: {crd_dir}")
        
        # Apply CRDs
        crd_files = list(crd_dir.glob('*.yaml'))
        
        for crd_file in crd_files:
            result = subprocess.run(
                ['kubectl', '--kubeconfig', self.kubeconfig_path, 'apply', '-f', str(crd_file)],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Failed to apply CRD {crd_file.name}: {result.stderr}")
            
            print(f"  ✓ Applied {crd_file.name}")
        
        # Wait for CRDs to be ready
        time.sleep(2)
        print(f"  ✓ All CRDs installed")


class TestCleanupWithEnvTest(unittest.TestCase):
    """
    Integration tests for cleanup using real K8s API server.
    
    Tests actual CR creation, deletion, and K8s API interactions.
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        cls.env = EnvTestSetup()
        cls.env.setup()
        
        # Create K8s client
        cls.k8s_client = K8sClient()
    
    @classmethod
    def tearDownClass(cls):
        """Tear down test environment"""
        cls.env.teardown()
    
    def setUp(self):
        """Set up for each test"""
        # Create test namespace if needed
        self.test_namespace = 'default'
    
    def tearDown(self):
        """Clean up after each test"""
        # Clean up all test ScanInstances
        try:
            scaninstances = self.k8s_client.list_scan_instances()
            for si in scaninstances:
                self.k8s_client.delete_scan_instance(si['metadata']['name'])
        except Exception:
            pass
    
    def test_create_and_delete_scaninstance(self):
        """Test creating and deleting a ScanInstance via real K8s API"""
        # Arrange
        target_cr = self._create_test_target()
        
        # Act - Create ScanInstance
        si_name = self.k8s_client.create_scaninstance(
            backupplan_uid='test-plan-123',
            backup_uid='test-backup-456',
            backup_path='test-plan-123/test-backup-456',
            target_ref=target_cr
        )
        
        # Assert - ScanInstance created
        self.assertIsNotNone(si_name)
        
        # Verify it exists
        si = self.k8s_client.get_scan_instance(si_name)
        self.assertIsNotNone(si)
        self.assertEqual(si['metadata']['name'], si_name)
        
        # Act - Delete ScanInstance
        deleted = self.k8s_client.delete_scan_instance(si_name)
        
        # Assert - Deletion successful
        self.assertTrue(deleted)
        
        # Verify it's gone
        time.sleep(0.5)  # Give K8s time to process
        si = self.k8s_client.get_scan_instance(si_name)
        self.assertIsNone(si)
    
    def test_delete_nonexistent_scaninstance(self):
        """Test deleting non-existent ScanInstance returns success (404 → True)"""
        # Act
        deleted = self.k8s_client.delete_scan_instance('nonexistent-si')
        
        # Assert - Should return True (already deleted)
        self.assertTrue(deleted)
    
    def test_list_scaninstances_with_label_selector(self):
        """Test listing ScanInstances with label selector"""
        # Arrange - Create ScanInstances with different labels
        target_cr = self._create_test_target()
        
        si_1 = self.k8s_client.create_scaninstance(
            backupplan_uid='plan-1',
            backup_uid='backup-1',
            backup_path='plan-1/backup-1',
            target_ref=target_cr
        )
        
        # Patch to add labels
        self.k8s_client.patch_scan_instance(
            si_1,
            labels={
                'trilio.io/backup-target': 'target-1',
                'trilio.io/backupplan': 'plan-1',
                'trilio.io/backup': 'backup-1'
            }
        )
        
        time.sleep(0.2)  # Let K8s process the patch
        
        # Act - List with label selector
        scaninstances = self.k8s_client.list_scan_instances(
            label_selector='trilio.io/backup-target=target-1'
        )
        
        # Assert
        self.assertEqual(len(scaninstances), 1)
        self.assertEqual(scaninstances[0]['metadata']['name'], si_1)
    
    def test_cleanup_stale_scaninstance_real_k8s(self):
        """
        Integration test: Create ScanInstance, then run cleanup with empty storage state.
        
        This tests the full cleanup flow with real K8s API:
        1. Create ScanInstance via K8s API
        2. Run cleanup with empty storage state (simulates backup deleted)
        3. Verify ScanInstance is deleted via K8s API
        """
        # Arrange
        target_cr = self._create_test_target()
        
        # Create ScanInstance
        si_name = self.k8s_client.create_scaninstance(
            backupplan_uid='plan-123',
            backup_uid='backup-456',
            backup_path='plan-123/backup-456',
            target_ref=target_cr
        )
        
        # Add labels (simulate prescan completion)
        self.k8s_client.patch_scan_instance(
            si_name,
            labels={
                'trilio.io/backup-target': 'test-target',
                'trilio.io/backupplan': 'plan-123',
                'trilio.io/backup': 'backup-456'
            }
        )
        
        time.sleep(0.5)
        
        # Verify ScanInstance exists
        si = self.k8s_client.get_scan_instance(si_name)
        self.assertIsNotNone(si)
        
        # Create handler with empty storage state
        handler = MockHandlerForEnvTest(
            target_cr=target_cr,
            k8s_client=self.k8s_client,
            logger_instance=self._get_logger()
        )
        
        # Empty storage state (simulates backup deleted from storage)
        handler.storage_state = StorageState()
        
        # Act - Run cleanup
        handler.perform_cleanup()
        
        # Give workers time to process
        time.sleep(1.0)
        
        # Assert - ScanInstance should be deleted
        si = self.k8s_client.get_scan_instance(si_name)
        self.assertIsNone(si, "ScanInstance should be deleted but still exists")
    
    def test_cleanup_preserves_valid_scaninstances(self):
        """Test cleanup doesn't delete valid ScanInstances (backup exists)"""
        # Arrange
        target_cr = self._create_test_target()
        
        # Create ScanInstance
        si_name = self.k8s_client.create_scaninstance(
            backupplan_uid='plan-123',
            backup_uid='backup-456',
            backup_path='plan-123/backup-456',
            target_ref=target_cr
        )
        
        # Add labels
        self.k8s_client.patch_scan_instance(
            si_name,
            labels={
                'trilio.io/backup-target': 'test-target',
                'trilio.io/backupplan': 'plan-123',
                'trilio.io/backup': 'backup-456'
            }
        )
        
        time.sleep(0.5)
        
        # Create handler with storage state containing the backup
        handler = MockHandlerForEnvTest(
            target_cr=target_cr,
            k8s_client=self.k8s_client,
            logger_instance=self._get_logger()
        )
        
        # Add backup to storage state (backup exists)
        handler.storage_state.add_backup(
            'plan-123',
            BackupObject(
                backup_uid='backup-456',
                json_path='plan-123/backup-456/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act - Run cleanup
        handler.perform_cleanup()
        
        time.sleep(1.0)
        
        # Assert - ScanInstance should still exist
        si = self.k8s_client.get_scan_instance(si_name)
        self.assertIsNotNone(si, "Valid ScanInstance should not be deleted")
    
    def test_cleanup_mixed_valid_and_stale(self):
        """Test cleanup with mixed valid and stale ScanInstances"""
        # Arrange
        target_cr = self._create_test_target()
        
        # Create 3 ScanInstances
        si_valid = self.k8s_client.create_scaninstance(
            backupplan_uid='plan-1',
            backup_uid='backup-valid',
            backup_path='plan-1/backup-valid',
            target_ref=target_cr
        )
        
        si_stale_1 = self.k8s_client.create_scaninstance(
            backupplan_uid='plan-1',
            backup_uid='backup-deleted-1',
            backup_path='plan-1/backup-deleted-1',
            target_ref=target_cr
        )
        
        si_stale_2 = self.k8s_client.create_scaninstance(
            backupplan_uid='plan-deleted',
            backup_uid='backup-2',
            backup_path='plan-deleted/backup-2',
            target_ref=target_cr
        )
        
        # Add labels to all
        for si_name, plan_uid, backup_uid in [
            (si_valid, 'plan-1', 'backup-valid'),
            (si_stale_1, 'plan-1', 'backup-deleted-1'),
            (si_stale_2, 'plan-deleted', 'backup-2')
        ]:
            self.k8s_client.patch_scan_instance(
                si_name,
                labels={
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': plan_uid,
                    'trilio.io/backup': backup_uid
                }
            )
        
        time.sleep(0.5)
        
        # Create handler with storage state containing only valid backup
        handler = MockHandlerForEnvTest(
            target_cr=target_cr,
            k8s_client=self.k8s_client,
            logger_instance=self._get_logger()
        )
        
        handler.storage_state.add_backup(
            'plan-1',
            BackupObject(
                backup_uid='backup-valid',
                json_path='plan-1/backup-valid/backup.json',
                last_updated_timestamp=datetime.now(),
                type=BackupType.BACKUP
            )
        )
        
        # Act - Run cleanup
        handler.perform_cleanup()
        
        time.sleep(1.5)
        
        # Assert
        # Valid ScanInstance should exist
        si = self.k8s_client.get_scan_instance(si_valid)
        self.assertIsNotNone(si, "Valid ScanInstance should not be deleted")
        
        # Stale ScanInstances should be deleted
        si = self.k8s_client.get_scan_instance(si_stale_1)
        self.assertIsNone(si, "Stale ScanInstance 1 should be deleted")
        
        si = self.k8s_client.get_scan_instance(si_stale_2)
        self.assertIsNone(si, "Stale ScanInstance 2 should be deleted")
    
    def _create_test_target(self):
        """Create a minimal test target CR"""
        return {
            'apiVersion': 'threatscanning.trilio.io/v1',
            'kind': 'Target',
            'metadata': {
                'name': 'test-target',
                'uid': 'test-target-uid-123',
                'resourceVersion': '1'
            },
            'spec': {
                'type': 'ObjectStore',
                'objectStoreCredentials': {
                    'url': 'http://minio.default.svc.cluster.local:9000',
                    'bucketName': 'test-bucket',
                    'region': 'us-east-1',
                    'credentialSecret': {
                        'name': 'test-secret',
                        'namespace': 'default'
                    },
                    'skipCertVerification': True
                },
                'vendor': 'Other'
            }
        }
    
    def _get_logger(self):
        """Get logger for handler"""
        import logging
        return logging.getLogger('test')


class MockHandlerForEnvTest(BaseTargetHandler):
    """Mock handler for envtest - only implements required abstract methods"""
    
    def populate_storage_state(self):
        return StorageState()
    
    def refresh_storage_state(self):
        pass
    
    def _read_scan_config(self, backupplan_uid, backup):
        return None

# Mark all tests in this class as integration tests
if HAS_PYTEST:
    TestCleanupWithEnvTest = pytest.mark.integration(pytest.mark.envtest(TestCleanupWithEnvTest))


class TestEnvTestFramework(unittest.TestCase):
    """Test the envtest framework itself"""
    
    def test_binaries_available(self):
        """Test envtest binaries can be found"""
        env = EnvTestSetup()
        binaries_dir = env._find_envtest_binaries()
        
        if binaries_dir:
            print(f"  ✓ Found binaries at {binaries_dir}")
        else:
            print("  ℹ Binaries not found - will download on first run")
            print("  Run: go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest")
            print("  Then: setup-envtest use")
    
    def test_kubectl_available(self):
        """Test kubectl is available"""
        result = subprocess.run(
            ['kubectl', 'version', '--client'],
            capture_output=True,
            timeout=5
        )
        self.assertEqual(result.returncode, 0, "kubectl should be installed")


if __name__ == '__main__':
    # Check prerequisites
    print("\nChecking prerequisites...")
    
    # Check kubectl
    try:
        result = subprocess.run(['kubectl', 'version', '--client'], capture_output=True, timeout=5)
        if result.returncode != 0:
            print("ERROR: kubectl not found. Please install kubectl.")
            sys.exit(1)
        print("  ✓ kubectl found")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("ERROR: kubectl not found. Please install kubectl.")
        sys.exit(1)
    
    # Check for binaries
    env_check = EnvTestSetup()
    binaries_dir = env_check._find_envtest_binaries()
    
    if not binaries_dir:
        print("\n⚠ WARNING: envtest binaries not found")
        print("\nTo download binaries:")
        print("  1. Install setup-envtest:")
        print("     go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest")
        print("  2. Download binaries:")
        print("     setup-envtest use")
        print("\nOR set KUBEBUILDER_ASSETS to path with kube-apiserver and etcd binaries\n")
        sys.exit(1)
    else:
        print(f"  ✓ envtest binaries found at {binaries_dir}")
    
    print("\n✓ All prerequisites met\n")
    unittest.main(verbosity=2)
