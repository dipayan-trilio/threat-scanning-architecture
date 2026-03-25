# TargetPoller Unit Tests

Comprehensive unit test suite for the targetPoller component, focusing on cleanup functionality.

## Overview

The test suite covers:
- **Cleanup logic**: Stale ScanInstance detection and removal
- **Worker threads**: Concurrent queue processing
- **Storage state**: In-memory backup representation
- **Edge cases**: Error handling, malformed data, race conditions

## Test Structure

```
datastore-attacher/
├── targetPoller/
│   └── tests/
│       ├── __init__.py
│       ├── test_cleanup.py           # Cleanup phase logic tests
│       ├── test_cleanup_workers.py   # Worker thread tests
│       └── test_storage_state.py     # StorageState model tests
├── pytest.ini                        # Pytest configuration
├── run_tests.sh                      # Test runner (pytest)
└── run_unittest.py                   # Test runner (unittest, no deps)
```

## Running Tests

### Option 1: Using pytest (Recommended)

```bash
# Install pytest if not already installed
pip install pytest pytest-timeout pytest-cov

# Run all unit tests
./run_tests.sh

# Run specific test category
./run_tests.sh cleanup
./run_tests.sh workers
./run_tests.sh storage

# Run specific test file
./run_tests.sh test_cleanup.py

# Run with coverage
pytest targetPoller/tests/ --cov=targetPoller --cov-report=html
```

### Option 2: Using unittest (No dependencies)

```bash
# Run all tests
python3 run_unittest.py

# Run specific test module
python3 run_unittest.py test_cleanup

# Run specific test class
python3 run_unittest.py targetPoller.tests.test_cleanup.TestCleanupBasicLogic
```

## Test Categories

### 1. Cleanup Phase Tests (`test_cleanup.py`)

Tests the core cleanup logic that identifies and removes stale ScanInstances.

**Test Classes:**
- `TestCleanupBasicLogic`: Basic cleanup control flow
- `TestCleanupMapBuilding`: ScanInstance map construction
- `TestCleanupStaleDetection`: Stale detection algorithm
- `TestCleanupQueueMessages`: Queue message creation
- `TestCleanupCompletion`: Cleanup completion logic
- `TestCleanupEdgeCases`: Edge cases and error handling
- `TestCleanupLabelHandling`: Label extraction and validation
- `TestCleanupWithDifferentBackupTypes`: Different backup types
- `TestCleanupMapRemoval`: Map cleanup after processing
- `TestCleanupScenarios`: End-to-end scenarios

**Key Scenarios Tested:**
- ✓ No ScanInstances exist
- ✓ All ScanInstances are valid
- ✓ Backup deleted (stale ScanInstance)
- ✓ Entire backupplan deleted (multiple stale ScanInstances)
- ✓ Mixed valid and stale ScanInstances
- ✓ ScanInstances without labels (prescan not completed)
- ✓ Large number of ScanInstances (1000+)
- ✓ Different backup types (backup, cluster-backup, snapshot, cluster-snapshot)

### 2. Worker Thread Tests (`test_cleanup_workers.py`)

Tests the worker thread behavior and concurrent queue processing.

**Test Classes:**
- `TestCleanupWorker`: Individual worker behavior
- `TestWorkerPoolCleanup`: Worker pool operations
- `TestCleanupWorkerConcurrency`: Concurrent processing
- `TestCleanupWorkerErrorHandling`: Error handling
- `TestCleanupScenarios`: Complex end-to-end scenarios

**Key Scenarios Tested:**
- ✓ Worker initialization
- ✓ Process single/multiple messages
- ✓ Success/failure handling
- ✓ Exception handling without crash
- ✓ Concurrent processing with multiple workers
- ✓ Queue.join() blocking behavior
- ✓ Stop event handling
- ✓ Statistics tracking

### 3. Storage State Tests (`test_storage_state.py`)

Tests the StorageState model and query operations.

**Test Classes:**
- `TestStorageStateBasics`: Basic operations
- `TestStorageStateQueries`: Query methods
- `TestBackupObject`: BackupObject model
- `TestBackupType`: BackupType enum
- `TestCleanupMessage`: CleanupMessage model
- `TestCreationMessage`: CreationMessage model
- `TestScanConfig`: ScanConfig parsing
- `TestStorageStateComplexOperations`: Complex queries
- `TestStorageStateWithDifferentBackupTypes`: Type handling
- `TestStorageStateEdgeCases`: Edge cases

**Key Scenarios Tested:**
- ✓ Add/query backups and backupplans
- ✓ Multiple backups per plan
- ✓ Multiple backupplans
- ✓ Different backup types
- ✓ Edge cases (empty UIDs, duplicates, long strings)

## Test Design Principles

### Mocking Strategy

All unit tests use mocks to avoid external dependencies:
- **K8s API**: Mocked with `unittest.mock.Mock()`
- **File system**: Not accessed (storage state pre-populated)
- **Network**: Not accessed (S3/NFS operations mocked)
- **Threading**: Real threads used to test concurrency

### What's Mocked
```python
mock_k8s_client = Mock()
mock_k8s_client.list_scan_instances.return_value = [...]
mock_k8s_client.delete_scaninstance.return_value = True

mock_storage_state = StorageState()
mock_storage_state.add_backup('plan-1', backup_obj)

mock_worker_pool = Mock(spec=WorkerPool)
mock_worker_pool.cleanup_queue = Mock()
```

### What's Real
- `StorageState` objects (in-memory data structures)
- `BackupObject` instances
- `CleanupMessage` instances
- Thread primitives (threading.Event, queue.Queue)
- Worker threads (to test real concurrency)

## Test Coverage

Current test coverage focuses on **cleanup functionality**:

| Component | Coverage | Tests |
|-----------|----------|-------|
| Cleanup logic | ~95% | 25+ test methods |
| Worker threads | ~90% | 15+ test methods |
| Storage state | ~95% | 20+ test methods |
| Queue processing | ~85% | 10+ test methods |

## Adding New Tests

### Template for Cleanup Test

```python
def test_your_scenario_name(self):
    """Test description"""
    # Arrange
    scaninstances = [
        {
            'metadata': {
                'name': 'test-si',
                'labels': {
                    'trilio.io/backup-target': 'test-target',
                    'trilio.io/backupplan': 'plan-123',
                    'trilio.io/backup': 'backup-456'
                }
            }
        }
    ]
    self.mock_k8s_client.list_scan_instances.return_value = scaninstances
    
    # Set up storage state
    self.handler.storage_state = StorageState()
    # ... add backups as needed
    
    # Act
    self.handler.perform_cleanup()
    
    # Assert
    self.handler.worker_pool.cleanup_queue.put.assert_called_once()
    # ... additional assertions
```

## Running Integration Tests

Integration tests require real Kubernetes cluster (TODO):

```bash
# Set up test cluster
kind create cluster --name test-cluster

# Install CRDs
kubectl apply -f config/crd/

# Run integration tests
pytest targetPoller/tests/ -m integration
```

## Troubleshooting

### Test Hangs
- Worker threads may not stop properly
- Set shorter timeouts in tearDown()
- Ensure stop_event is set

### Import Errors
- Check PYTHONPATH includes parent directories
- Verify sys.path.insert(0, ...) in test files

### Mock Not Working
- Verify mock paths match actual import paths
- Use `spec=` parameter for better mock validation
- Check if patching is at correct location

## Next Steps

1. ✅ **Cleanup unit tests** (COMPLETED)
2. ⏭️ Discovery phase tests
3. ⏭️ TVK handler-specific tests
4. ⏭️ Integration tests with real K8s
5. ⏭️ E2E tests with full stack

## Contributing

When adding tests:
1. Follow existing test structure and naming
2. Use descriptive test names (test_what_when_expected)
3. Include docstrings for complex scenarios
4. Mock external dependencies
5. Test both success and failure paths
6. Add edge cases and boundary conditions
