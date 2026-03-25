# Target Poller Test Suite Overview

This document provides a comprehensive overview of all test files, scenarios covered, and testing approaches for the Target Poller component.

## Summary Statistics

- **Total Test Files**: 5
- **Total Test Cases**: 105
- **Mock-Based Unit Tests**: 97 tests (92.4%)
- **EnvTest Integration Tests**: 8 tests (7.6%)

---

## Test Files Overview

### 1. `test_cleanup.py` - Core Cleanup Logic Tests (MOCK-BASED)
**Type**: Unit Tests with Mocks  
**Test Count**: 20 tests  
**Focus**: Core cleanup algorithm and business logic

#### Test Classes:

**TestCleanupBasicLogic** (5 tests)
- `test_cleanup_with_no_scaninstances` - Verify behavior when no ScanInstances exist
- `test_cleanup_with_all_valid_scaninstances` - All ScanInstances have valid backups
- `test_cleanup_with_stale_backup` - Detect stale ScanInstance when backup is deleted
- `test_cleanup_with_stale_backupplan` - Detect stale ScanInstance when backupplan is deleted
- `test_cleanup_skips_scaninstances_without_labels` - Skip ScanInstances without required labels

**TestCleanupMapBuilding** (4 tests)
- `test_map_single_backupplan_single_backup` - Build map for simple hierarchy
- `test_map_multiple_scaninstances_same_backup` - Multiple ScanInstances referencing same backup
- `test_map_multiple_backupplans` - Handle multiple backupplans
- `test_map_complex_hierarchy` - Complex nested structures

**TestCleanupStaleDetection** (3 tests)
- `test_detect_stale_when_backup_deleted` - Stale detection for missing backup
- `test_detect_stale_when_backupplan_deleted` - Stale detection for missing backupplan
- `test_mixed_scenario_some_stale_some_valid` - Mixed valid/stale scenarios

**TestCleanupQueueMessages** (2 tests)
- `test_cleanup_message_structure` - Verify cleanup message format
- `test_multiple_cleanup_messages_for_same_plan` - Multiple messages for same plan

**TestCleanupCompletion** (2 tests)
- `test_wait_called_when_stale_scaninstances_exist` - Wait for completion when work exists
- `test_wait_not_called_when_no_stale_scaninstances` - No wait when no work

**TestCleanupEdgeCases** (4 tests)
- `test_cleanup_with_malformed_scaninstance` - Handle malformed ScanInstance data
- `test_cleanup_with_empty_label_values` - Handle empty label values
- `test_cleanup_with_large_number_of_scaninstances` - Scalability test (100+ ScanInstances)
- `test_cleanup_label_selector_correct` - Verify label selector format

---

### 2. `test_cleanup_workers.py` - Worker Thread Tests (MOCK-BASED)
**Type**: Unit Tests with Mocks  
**Test Count**: 34 tests  
**Focus**: CleanupWorker threads and concurrent processing

#### Test Classes:

**TestCleanupWorker** (8 tests)
- `test_worker_initialization` - Worker initializes with correct attributes
- `test_worker_processes_single_message` - Process single cleanup message
- `test_worker_processes_multiple_messages` - Process multiple messages sequentially
- `test_worker_handles_deletion_success` - Successful ScanInstance deletion
- `test_worker_handles_deletion_failure` - Handle API deletion failures
- `test_worker_handles_exception_during_processing` - Exception handling during processing
- `test_worker_stops_on_stop_event` - Worker stops gracefully on stop signal
- `test_worker_continues_after_single_error` - Worker continues after encountering errors

**TestWorkerPoolCleanup** (8 tests)
- `test_workerpool_initialization` - WorkerPool initializes correctly
- `test_start_cleanup_workers` - Start multiple worker threads
- `test_cleanup_workers_process_queue` - Workers process cleanup queue
- `test_wait_for_cleanup_completion` - Wait for queue to be empty
- `test_stop_all_workers` - Stop all worker threads
- `test_get_stats_empty_queues` - Statistics with empty queues
- `test_get_stats_after_processing` - Statistics after processing work
- `test_get_stats_with_errors` - Statistics including error counts

**TestCleanupWorkerConcurrency** (2 tests)
- `test_multiple_workers_process_concurrently` - Concurrent processing by multiple workers
- `test_queue_join_waits_for_all_tasks` - Queue join synchronization

**TestCleanupWorkerErrorHandling** (3 tests)
- `test_worker_handles_k8s_api_exception` - Handle K8s API exceptions
- `test_worker_continues_after_exception` - Continue processing after exceptions
- `test_worker_handles_malformed_message` - Handle malformed queue messages

**TestCleanupScenarios** (3 tests)
- `test_scenario_all_backups_deleted` - All backups deleted scenario
- `test_scenario_partial_backupplan_deleted` - Partial backupplan deletion
- `test_scenario_multiple_backupplans_mixed_state` - Mixed state across multiple plans

**TestCleanupLabelHandling** (10 tests)
- Tests for correct label extraction and handling from ScanInstances
- Tests for missing/malformed labels
- Tests for label validation

---

### 3. `test_storage_state.py` - StorageState Model Tests (MOCK-BASED)
**Type**: Unit Tests with Mocks  
**Test Count**: 37 tests  
**Focus**: StorageState data model and operations

#### Test Classes:

**TestStorageStateBasics** (4 tests)
- `test_empty_storage_state` - Empty state initialization
- `test_add_single_backup` - Add single backup to state
- `test_add_multiple_backups_same_plan` - Multiple backups under same plan
- `test_add_backups_multiple_plans` - Backups across multiple plans

**TestStorageStateQueries** (9 tests)
- `test_has_backupplan_exists` - Query if backupplan exists
- `test_has_backupplan_not_exists` - Query for non-existent backupplan
- `test_has_backup_exists` - Query if backup exists
- `test_has_backup_not_exists` - Query for non-existent backup
- `test_get_backup_exists` - Get backup by UID
- `test_get_backup_not_exists` - Get non-existent backup
- `test_get_backups_for_plan` - Get all backups for a plan
- `test_get_backups_empty_plan` - Get backups for empty plan
- `test_get_all_backupplan_uids` - Get all backupplan UIDs

**TestBackupObject** (3 tests)
- `test_backup_object_creation` - Create BackupObject instances
- `test_backup_object_with_optional_fields` - Optional field handling
- `test_backup_object_repr` - String representation

**TestBackupType** (3 tests)
- `test_backup_type_values` - BackupType enum values
- `test_backup_type_json_filename` - JSON filename mapping
- `test_backup_type_from_string` - Create from string

**TestCleanupMessage** (2 tests)
- `test_cleanup_message_creation` - CleanupMessage model creation
- `test_cleanup_message_repr` - String representation

**TestCreationMessage** (2 tests)
- `test_creation_message_creation` - CreationMessage model creation
- `test_creation_message_repr` - String representation

**TestScanConfig** (~14 tests)
- Tests for ScanConfig model and operations

---

### 4. `test_cleanup_envtest.py` - Integration Tests (ENVTEST-STYLE)
**Type**: Integration Tests with Real K8s API Server + etcd  
**Test Count**: 8 tests  
**Focus**: Real Kubernetes API behavior and CR lifecycle

#### Approach:
This file uses an **envtest-style approach** (like Go controller-runtime tests):
1. Starts real `kube-apiserver` and `etcd` binaries using `subprocess`
2. Installs actual CRDs from YAML files
3. Creates real Custom Resources (Target, ScanInstance)
4. Tests actual K8s API interactions
5. No Docker/kind required - just binaries

#### Test Classes:

**TestCleanupWithEnvTest** (6 tests)
- `test_create_and_delete_scaninstance` - Create and delete ScanInstance via K8s API
- `test_delete_nonexistent_scaninstance` - Handle deletion of non-existent resource
- `test_list_scaninstances_with_label_selector` - List with label selectors
- `test_cleanup_stale_scaninstance_real_k8s` - End-to-end cleanup with real K8s
- `test_cleanup_preserves_valid_scaninstances` - Valid ScanInstances not deleted
- `test_cleanup_mixed_valid_and_stale` - Mixed scenario with real K8s

**TestEnvTestFramework** (2 tests)
- `test_binaries_available` - Verify kube-apiserver and etcd binaries exist
- `test_kubectl_available` - Verify kubectl is installed

#### Infrastructure:
The `EnvTestSetup` class manages the test environment:
- Binary discovery (KUBEBUILDER_ASSETS, ~/.local/share, /usr/local)
- Binary download via `setup-envtest` if not found
- Process lifecycle (start/stop etcd and kube-apiserver)
- Kubeconfig generation
- CRD installation
- Cleanup and teardown

**Ports Used**:
- etcd client: 2379 (default)
- etcd peer: 2380 (default)
- API server secure: 6443 (default)

---

### 5. `test_patterns.py` - Test Pattern Examples (MOCK-BASED)
**Type**: Example/Documentation Tests  
**Test Count**: 6 tests  
**Focus**: Demonstrate common test patterns

This file provides **template patterns** for writing tests:

**Examples Included**:
- `test_example_stale_detection` - Pattern for testing stale detection
- `test_example_worker_processes_message` - Pattern for worker testing
- `test_example_has_backup_query` - Pattern for storage state queries
- `test_example_worker_handles_exception` - Pattern for error handling
- `test_example_mixed_valid_and_stale` - Pattern for mixed scenarios
- `test_example_partial_failure` - Pattern for partial failure scenarios

---

## Test Type Classification

### Mock-Based Unit Tests (97 tests)
These tests use `unittest.mock` to mock external dependencies:

**Files**:
- `test_cleanup.py` (20 tests)
- `test_cleanup_workers.py` (34 tests)
- `test_storage_state.py` (37 tests)
- `test_patterns.py` (6 tests)

**Characteristics**:
- ✓ Fast execution (milliseconds)
- ✓ No external dependencies
- ✓ Mocked K8s client
- ✓ Mocked worker threads
- ✓ Isolated unit behavior
- ✓ Can run without any K8s cluster

**Pytest Markers**: `@pytest.mark.unit`

---

### EnvTest Integration Tests (8 tests)
These tests use real Kubernetes components:

**Files**:
- `test_cleanup_envtest.py` (8 tests)

**Characteristics**:
- ✓ Real kube-apiserver process
- ✓ Real etcd process
- ✓ Real CRDs installed
- ✓ Real K8s API calls
- ✓ Real CR lifecycle (create, list, delete)
- ✓ No Docker/kind needed
- ✓ Same approach as Go controller tests
- ⚠ Slower execution (seconds)
- ⚠ Requires kube-apiserver and etcd binaries

**Pytest Markers**: `@pytest.mark.integration @pytest.mark.envtest`

**Prerequisites**:
1. Install `setup-envtest`: `go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest`
2. Install `kubectl`
3. Binaries will be auto-downloaded to `~/.local/share/kubebuilder-envtest/`

---

## Scenario Coverage Matrix

| Scenario | Mock Tests | EnvTest | File(s) |
|----------|-----------|---------|---------|
| **Basic Cleanup Flow** |
| No ScanInstances | ✓ | - | test_cleanup.py |
| All valid ScanInstances | ✓ | ✓ | test_cleanup.py, test_cleanup_envtest.py |
| All stale ScanInstances | ✓ | ✓ | test_cleanup.py, test_cleanup_envtest.py |
| Mixed valid/stale | ✓ | ✓ | test_cleanup.py, test_cleanup_envtest.py |
| **Stale Detection** |
| Backup deleted | ✓ | ✓ | test_cleanup.py, test_cleanup_envtest.py |
| Backupplan deleted | ✓ | - | test_cleanup.py |
| Partial backupplan deletion | ✓ | - | test_cleanup_workers.py |
| **Map Building** |
| Single plan/backup | ✓ | - | test_cleanup.py |
| Multiple ScanInstances per backup | ✓ | - | test_cleanup.py |
| Multiple backupplans | ✓ | - | test_cleanup.py |
| Complex hierarchy | ✓ | - | test_cleanup.py |
| **Worker Thread Behavior** |
| Worker initialization | ✓ | - | test_cleanup_workers.py |
| Single message processing | ✓ | - | test_cleanup_workers.py |
| Multiple messages | ✓ | - | test_cleanup_workers.py |
| Concurrent processing | ✓ | - | test_cleanup_workers.py |
| Graceful shutdown | ✓ | - | test_cleanup_workers.py |
| **Error Handling** |
| Deletion failure | ✓ | - | test_cleanup_workers.py |
| API exceptions | ✓ | - | test_cleanup_workers.py |
| Malformed messages | ✓ | - | test_cleanup_workers.py |
| Worker continues after error | ✓ | - | test_cleanup_workers.py |
| **Edge Cases** |
| Malformed ScanInstance | ✓ | - | test_cleanup.py |
| Empty label values | ✓ | - | test_cleanup.py |
| Large number of ScanInstances (100+) | ✓ | - | test_cleanup.py |
| Label selector correctness | ✓ | - | test_cleanup.py |
| Missing labels | ✓ | - | test_cleanup_workers.py |
| **K8s API Operations** |
| Create ScanInstance | - | ✓ | test_cleanup_envtest.py |
| Delete ScanInstance | - | ✓ | test_cleanup_envtest.py |
| List with label selector | - | ✓ | test_cleanup_envtest.py |
| Delete non-existent resource | - | ✓ | test_cleanup_envtest.py |
| **Storage State Model** |
| Empty state | ✓ | - | test_storage_state.py |
| Add/query backups | ✓ | - | test_storage_state.py |
| Multiple plans | ✓ | - | test_storage_state.py |
| Backup queries | ✓ | - | test_storage_state.py |
| Model creation | ✓ | - | test_storage_state.py |

---

## Running Tests

### Run All Tests
```bash
cd datastore-attacher
source .venv/bin/activate
export PYTHONPATH="$(pwd)"

# Run all tests
python3 -m pytest targetPoller/tests/ -v
```

### Run Only Mock-Based Unit Tests (Fast)
```bash
# Run all mock tests (excluding envtest)
python3 -m pytest targetPoller/tests/ -v -m "not envtest"

# Specific files
python3 -m pytest targetPoller/tests/test_cleanup.py -v
python3 -m pytest targetPoller/tests/test_cleanup_workers.py -v
python3 -m pytest targetPoller/tests/test_storage_state.py -v
```

### Run Only EnvTest Integration Tests
```bash
# Using the helper script (recommended)
./run_envtest.sh

# Or directly with pytest
python3 -m pytest targetPoller/tests/test_cleanup_envtest.py -v -m envtest

# Single test
python3 -m pytest targetPoller/tests/test_cleanup_envtest.py::TestCleanupWithEnvTest::test_cleanup_stale_scaninstance_real_k8s -v
```

---

## Test Dependencies

### Mock-Based Tests
```txt
pytest>=7.0.0
```

### EnvTest Integration Tests
**Python Dependencies**:
```txt
pytest>=7.0.0
kubernetes>=28.1.0
PyYAML>=6.0.1
```

**System Dependencies**:
1. **kubectl**: Kubernetes CLI tool
   ```bash
   # Install kubectl
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   chmod +x kubectl
   sudo mv kubectl /usr/local/bin/
   ```

2. **setup-envtest**: Binary downloader tool
   ```bash
   go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest
   ```

3. **kube-apiserver & etcd binaries**: Auto-downloaded by `setup-envtest`
   ```bash
   # Will be downloaded to ~/.local/share/kubebuilder-envtest/
   setup-envtest use --bin-dir ~/.local/share/kubebuilder-envtest
   ```

---

## Test Coverage by Component

### Cleanup Phase Components:

| Component | Mock Tests | EnvTest | Total |
|-----------|-----------|---------|-------|
| `perform_cleanup()` | 20 | 6 | 26 |
| `CleanupWorker` | 34 | - | 34 |
| `StorageState` | 37 | - | 37 |
| `K8s Client` (mocked) | 54 | - | 54 |
| `K8s Client` (real) | - | 8 | 8 |

### Discovery Phase Components:
**Status**: Not yet implemented

**Planned Tests**:
- `test_discovery.py` - Mock-based discovery tests
- Discovery phase envtest tests (can be added to existing envtest file)

---

## Test Execution Time (Estimated)

| Test Type | Count | Avg Time/Test | Total Time |
|-----------|-------|--------------|------------|
| Mock Unit Tests | 97 | ~50ms | ~5 seconds |
| EnvTest Integration | 8 | ~2-3s | ~20 seconds |
| **Total** | **105** | - | **~25 seconds** |

*Note: EnvTest setup (starting binaries) adds ~5-10 seconds one-time overhead*

---

## Files Created/Modified

### Test Files Created:
1. ✓ `targetPoller/tests/test_cleanup.py` - 20 mock-based cleanup logic tests
2. ✓ `targetPoller/tests/test_cleanup_workers.py` - 34 mock-based worker tests
3. ✓ `targetPoller/tests/test_storage_state.py` - 37 mock-based model tests
4. ✓ `targetPoller/tests/test_patterns.py` - 6 example pattern tests
5. ✓ `targetPoller/tests/test_cleanup_envtest.py` - 8 envtest integration tests

### Test Infrastructure Files:
1. ✓ `run_envtest.sh` - Script to run envtest integration tests
2. ✓ `run_unittest.py` - Script to run mock-based unit tests
3. ✓ `pytest.ini` - Pytest configuration with markers
4. ✓ `requirements-test.txt` - Test dependencies
5. ✓ `setup_tests.sh` - Test environment setup script

### Documentation Files:
1. ✓ `targetPoller/tests/README_ENVTEST.md` - EnvTest documentation
2. ✓ `TESTING_GUIDE.md` - Comprehensive testing guide
3. ✓ `POLLER_TEST_OVERVIEW.md` - This file

---

## Key Differences: Mock vs EnvTest

### Mock-Based Unit Tests

**Pros**:
- ⚡ Extremely fast (milliseconds)
- 🎯 Isolated, focused tests
- 🚀 No dependencies or setup needed
- 💯 Easy to test edge cases
- 🔧 Easy to debug

**Cons**:
- ⚠️ Doesn't catch real K8s API behavior issues
- ⚠️ Mock assumptions might not match reality
- ⚠️ Doesn't test actual CR lifecycle

**Use When**:
- Testing business logic
- Testing algorithms
- Testing error handling
- Fast feedback during development
- CI/CD pipelines (fast feedback)

---

### EnvTest Integration Tests

**Pros**:
- ✅ Real K8s API server behavior
- ✅ Real CR create/delete/list operations
- ✅ Real API errors (404, 403, etc.)
- ✅ Catches CRD schema issues
- ✅ No Docker overhead
- ✅ Same approach as Go controllers

**Cons**:
- 🐌 Slower (2-3 seconds per test)
- 🔧 Requires binary setup
- 💾 More complex infrastructure
- ⚠️ Port conflicts possible

**Use When**:
- Testing K8s API integration
- Verifying CR lifecycle
- Testing CRD validation
- Pre-merge validation
- Integration/E2E testing

---

## Test Markers (pytest)

Tests are categorized using pytest markers:

```python
# Mock-based unit tests
@pytest.mark.unit

# EnvTest integration tests
@pytest.mark.integration
@pytest.mark.envtest

# By functionality
@pytest.mark.cleanup
@pytest.mark.discovery
@pytest.mark.workers

# Performance
@pytest.mark.slow
```

**Run by marker**:
```bash
# Only unit tests (fast)
pytest -m unit

# Only integration tests
pytest -m integration

# Only envtest tests
pytest -m envtest

# Exclude slow tests
pytest -m "not slow"
```

---

## Current Status

### ✅ Completed:
- Mock-based cleanup phase tests (97 tests)
- EnvTest integration tests (8 tests)
- Test infrastructure (scripts, configs)
- Documentation

### 🔄 In Progress:
- Fixing etcd startup issues in envtest (port conflicts, flag names)

### 📋 Pending:
- Discovery phase mock tests
- Discovery phase envtest tests
- TVK handler-specific tests
- TVO handler-specific tests
- Prescan component tests
- End-to-end tests (real K8s cluster + real storage)

---

## Quick Reference

| Test Type | File Pattern | Run Command | Speed |
|-----------|-------------|-------------|-------|
| All Tests | `test_*.py` | `pytest targetPoller/tests/` | ~25s |
| Unit (Mock) | `test_cleanup*.py`, `test_storage*.py`, `test_patterns.py` | `pytest -m unit` | ~5s |
| Integration (EnvTest) | `test_cleanup_envtest.py` | `./run_envtest.sh` | ~20s |
| Specific Class | Any | `pytest path::ClassName` | Varies |
| Specific Test | Any | `pytest path::ClassName::test_name` | Varies |

---

## Architecture Alignment

The test suite follows the same patterns as Go controller tests:

| Go Controller Tests | Python Poller Tests | Implementation |
|---------------------|---------------------|----------------|
| `envtest` package | `EnvTestSetup` class | ✓ Implemented |
| `setup-envtest` tool | `setup-envtest` tool | ✓ Same tool |
| Binary management | `_find_envtest_binaries()` | ✓ Implemented |
| Process lifecycle | `subprocess.Popen` | ✓ Implemented |
| Kubeconfig generation | `_create_kubeconfig()` | ✓ Implemented |
| CRD installation | `_install_crds()` | ✓ Implemented |
| Cleanup/teardown | `teardown()` | ✓ Implemented |

---

## Next Steps

1. **Fix current envtest issues** (etcd flag name fixed, testing in progress)
2. **Add discovery phase tests** (similar mock-based approach)
3. **Add handler-specific tests** (TVK, TVO handlers)
4. **Add prescan tests**
5. **Consider full E2E tests** (real K8s cluster + real NFS/S3)

---

## Contact & Support

For questions or issues with tests:
- Check `TESTING_GUIDE.md` for detailed instructions
- Check `targetPoller/tests/README_ENVTEST.md` for envtest specifics
- Check `test_patterns.py` for test template examples
