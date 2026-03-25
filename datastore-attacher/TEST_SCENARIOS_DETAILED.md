# Test Scenarios - Detailed Breakdown

## Quick Reference: Which File Contains What?

### Need to Test: Core Cleanup Algorithm?
→ **`test_cleanup.py`** (Mock-Based)

### Need to Test: Worker Threads & Concurrency?
→ **`test_cleanup_workers.py`** (Mock-Based)

### Need to Test: Data Models?
→ **`test_storage_state.py`** (Mock-Based)

### Need to Test: Real K8s API Integration?
→ **`test_cleanup_envtest.py`** (EnvTest - Real API)

### Need Examples/Templates?
→ **`test_patterns.py`** (Examples)

---

## Detailed Scenario Mapping

### 🎯 Cleanup Algorithm Scenarios

| Scenario | Mock Test | EnvTest | File(s) |
|----------|-----------|---------|---------|
| **No ScanInstances exist** | ✓ | - | `test_cleanup.py::test_cleanup_with_no_scaninstances` |
| **All ScanInstances are valid** | ✓ | ✓ | `test_cleanup.py::test_cleanup_with_all_valid_scaninstances`<br>`test_cleanup_envtest.py::test_cleanup_preserves_valid_scaninstances` |
| **Single stale backup** | ✓ | ✓ | `test_cleanup.py::test_cleanup_with_stale_backup`<br>`test_cleanup_envtest.py::test_cleanup_stale_scaninstance_real_k8s` |
| **Stale backupplan** | ✓ | - | `test_cleanup.py::test_cleanup_with_stale_backupplan` |
| **Mixed valid and stale** | ✓ | ✓ | `test_cleanup.py::test_detect_stale_when_backup_deleted`<br>`test_cleanup_envtest.py::test_cleanup_mixed_valid_and_stale` |
| **Skip ScanInstances without labels** | ✓ | - | `test_cleanup.py::test_cleanup_skips_scaninstances_without_labels` |

---

### 🗺️ Map Building Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Single plan, single backup** | `test_cleanup.py` | `test_map_single_backupplan_single_backup` |
| **Multiple ScanInstances → same backup** | `test_cleanup.py` | `test_map_multiple_scaninstances_same_backup` |
| **Multiple backupplans** | `test_cleanup.py` | `test_map_multiple_backupplans` |
| **Complex nested hierarchy** | `test_cleanup.py` | `test_map_complex_hierarchy` |

---

### 🔍 Stale Detection Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Backup deleted** | `test_cleanup.py` | `test_detect_stale_when_backup_deleted` |
| **Backupplan deleted** | `test_cleanup.py` | `test_detect_stale_when_backupplan_deleted` |
| **Mixed stale/valid** | `test_cleanup.py` | `test_mixed_scenario_some_stale_some_valid` |

---

### 📨 Queue & Message Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Cleanup message structure** | `test_cleanup.py` | `test_cleanup_message_structure` |
| **Multiple messages for same plan** | `test_cleanup.py` | `test_multiple_cleanup_messages_for_same_plan` |

---

### ⚙️ Worker Thread Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Worker initialization** | `test_cleanup_workers.py` | `test_worker_initialization` |
| **Process single message** | `test_cleanup_workers.py` | `test_worker_processes_single_message` |
| **Process multiple messages** | `test_cleanup_workers.py` | `test_worker_processes_multiple_messages` |
| **Deletion success** | `test_cleanup_workers.py` | `test_worker_handles_deletion_success` |
| **Deletion failure** | `test_cleanup_workers.py` | `test_worker_handles_deletion_failure` |
| **Exception handling** | `test_cleanup_workers.py` | `test_worker_handles_exception_during_processing` |
| **Graceful stop** | `test_cleanup_workers.py` | `test_worker_stops_on_stop_event` |
| **Continue after error** | `test_cleanup_workers.py` | `test_worker_continues_after_single_error` |

---

### 👥 Worker Pool Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Pool initialization** | `test_cleanup_workers.py` | `test_workerpool_initialization` |
| **Start workers** | `test_cleanup_workers.py` | `test_start_cleanup_workers` |
| **Workers process queue** | `test_cleanup_workers.py` | `test_cleanup_workers_process_queue` |
| **Wait for completion** | `test_cleanup_workers.py` | `test_wait_for_cleanup_completion` |
| **Stop all workers** | `test_cleanup_workers.py` | `test_stop_all_workers` |
| **Get statistics** | `test_cleanup_workers.py` | `test_get_stats_*` (3 tests) |

---

### 🔀 Concurrency Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Multiple workers process concurrently** | `test_cleanup_workers.py` | `test_multiple_workers_process_concurrently` |
| **Queue join synchronization** | `test_cleanup_workers.py` | `test_queue_join_waits_for_all_tasks` |

---

### ⚠️ Error Handling Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **K8s API exception** | `test_cleanup_workers.py` | `test_worker_handles_k8s_api_exception` |
| **Continue after exception** | `test_cleanup_workers.py` | `test_worker_continues_after_exception` |
| **Malformed message** | `test_cleanup_workers.py` | `test_worker_handles_malformed_message` |

---

### 🎭 Complex End-to-End Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **All backups deleted** | `test_cleanup_workers.py` | `test_scenario_all_backups_deleted` |
| **Partial backupplan deletion** | `test_cleanup_workers.py` | `test_scenario_partial_backupplan_deleted` |
| **Multiple plans mixed state** | `test_cleanup_workers.py` | `test_scenario_multiple_backupplans_mixed_state` |

---

### 🏷️ Label Handling Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Label extraction** | `test_cleanup_workers.py` | `TestCleanupLabelHandling` (10 tests) |
| **Label selector format** | `test_cleanup.py` | `test_cleanup_label_selector_correct` |
| **Empty label values** | `test_cleanup.py` | `test_cleanup_with_empty_label_values` |

---

### 🔧 Edge Case Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Malformed ScanInstance** | `test_cleanup.py` | `test_cleanup_with_malformed_scaninstance` |
| **Large number (100+) of ScanInstances** | `test_cleanup.py` | `test_cleanup_with_large_number_of_scaninstances` |
| **Empty label values** | `test_cleanup.py` | `test_cleanup_with_empty_label_values` |

---

### 📦 Storage State Model Scenarios

| Scenario | File | Test Method |
|----------|------|-------------|
| **Empty state** | `test_storage_state.py` | `test_empty_storage_state` |
| **Add single backup** | `test_storage_state.py` | `test_add_single_backup` |
| **Multiple backups same plan** | `test_storage_state.py` | `test_add_multiple_backups_same_plan` |
| **Multiple plans** | `test_storage_state.py` | `test_add_backups_multiple_plans` |
| **has_backupplan query** | `test_storage_state.py` | `test_has_backupplan_*` (2 tests) |
| **has_backup query** | `test_storage_state.py` | `test_has_backup_*` (2 tests) |
| **get_backup query** | `test_storage_state.py` | `test_get_backup_*` (2 tests) |
| **get_backups_for_plan** | `test_storage_state.py` | `test_get_backups_*` (2 tests) |
| **get_all_backupplan_uids** | `test_storage_state.py` | `test_get_all_backupplan_uids` |
| **BackupObject model** | `test_storage_state.py` | `TestBackupObject` (3 tests) |
| **BackupType enum** | `test_storage_state.py` | `TestBackupType` (3 tests) |
| **Message models** | `test_storage_state.py` | `TestCleanupMessage`, `TestCreationMessage` (4 tests) |
| **ScanConfig model** | `test_storage_state.py` | `TestScanConfig` (~14 tests) |

---

### ☸️ Kubernetes API Integration Scenarios (EnvTest Only)

| Scenario | File | Test Method |
|----------|------|-------------|
| **Create ScanInstance via K8s API** | `test_cleanup_envtest.py` | `test_create_and_delete_scaninstance` |
| **Delete ScanInstance via K8s API** | `test_cleanup_envtest.py` | `test_create_and_delete_scaninstance` |
| **Delete non-existent ScanInstance** | `test_cleanup_envtest.py` | `test_delete_nonexistent_scaninstance` |
| **List with label selector** | `test_cleanup_envtest.py` | `test_list_scaninstances_with_label_selector` |
| **Real cleanup with real K8s** | `test_cleanup_envtest.py` | `test_cleanup_stale_scaninstance_real_k8s` |
| **Preserve valid ScanInstances** | `test_cleanup_envtest.py` | `test_cleanup_preserves_valid_scaninstances` |
| **Mixed valid/stale with real API** | `test_cleanup_envtest.py` | `test_cleanup_mixed_valid_and_stale` |
| **Binaries available** | `test_cleanup_envtest.py` | `test_binaries_available` |
| **kubectl available** | `test_cleanup_envtest.py` | `test_kubectl_available` |

---

## Test Type Comparison

### Mock-Based Unit Tests (97 tests)

**Files**: `test_cleanup.py`, `test_cleanup_workers.py`, `test_storage_state.py`, `test_patterns.py`

**What They Test**:
- Business logic algorithms
- Data model operations
- Worker thread behavior
- Queue processing logic
- Error handling paths
- Edge cases

**How They Work**:
```python
# Example: Mock K8s client
mock_k8s_client = Mock()
mock_k8s_client.list_scan_instances.return_value = [...]

# Test the handler
handler.perform_cleanup()

# Verify behavior
mock_k8s_client.list_scan_instances.assert_called_once()
```

**Pros**:
- ⚡ Very fast (milliseconds per test)
- 🎯 Isolated and focused
- 💯 Easy to test edge cases
- 🚀 No dependencies

**Cons**:
- ⚠️ Doesn't catch real K8s API issues
- ⚠️ Mock assumptions might be wrong
- ⚠️ No CRD validation

---

### EnvTest Integration Tests (8 tests)

**Files**: `test_cleanup_envtest.py`

**What They Test**:
- Real K8s API behavior
- CR lifecycle (create, list, delete)
- CRD schema validation
- API error responses (404, 403, etc.)
- Real label selector behavior
- Actual cleanup with real API

**How They Work**:
```python
# 1. Start real etcd process
subprocess.Popen(['/path/to/etcd', '--data-dir=/tmp/...', ...])

# 2. Start real kube-apiserver process
subprocess.Popen(['/path/to/kube-apiserver', '--etcd-servers=...', ...])

# 3. Install real CRDs
kubectl apply -f config/crd/bases/...

# 4. Create real ScanInstance CR
k8s_client.create_scan_instance(...)

# 5. Run cleanup
handler.perform_cleanup()

# 6. Verify via real API
result = k8s_client.get_scan_instance(name)
# Expect: 404 Not Found
```

**Pros**:
- ✅ Tests real K8s behavior
- ✅ Catches CRD issues
- ✅ Real API responses
- ✅ No Docker needed
- ✅ Same as Go controller tests

**Cons**:
- 🐌 Slower (2-3 seconds per test)
- 🔧 Requires binary setup
- ⚠️ More complex infrastructure

---

## Component Coverage

### 1. BaseTargetHandler.perform_cleanup()
**Tested In**: 
- `test_cleanup.py` (20 mock tests) - Algorithm logic
- `test_cleanup_envtest.py` (6 envtest tests) - Real K8s integration

**Scenarios Covered**:
- Empty ScanInstance list
- All valid ScanInstances
- All stale ScanInstances
- Mixed valid/stale
- Stale backup detection
- Stale backupplan detection
- Map building (backup → scaninstance)
- Queue message creation
- Label selector usage

---

### 2. CleanupWorker & WorkerPool
**Tested In**: `test_cleanup_workers.py` (34 mock tests)

**Scenarios Covered**:
- Worker thread lifecycle
- Single/multiple message processing
- Concurrent processing (multiple workers)
- Deletion success/failure
- Exception handling
- Graceful shutdown
- Queue synchronization
- Statistics collection
- Label extraction
- Error recovery

---

### 3. StorageState Model
**Tested In**: `test_storage_state.py` (37 mock tests)

**Scenarios Covered**:
- State initialization
- Adding backups (single, multiple, multiple plans)
- Query operations:
  - `has_backup(uid)`
  - `has_backupplan(uid)`
  - `get_backup(plan, uid)`
  - `get_backups_for_plan(uid)`
  - `get_all_backupplan_uids()`
- BackupObject model
- BackupType enum
- CleanupMessage model
- CreationMessage model
- ScanConfig model

---

### 4. K8sClient (via Real K8s API)
**Tested In**: `test_cleanup_envtest.py` (8 envtest tests)

**Scenarios Covered**:
- `create_scan_instance()` - Create real CR
- `delete_scan_instance()` - Delete real CR
- `get_scan_instance()` - Get by name (including 404 handling)
- `list_scan_instances()` - List with label selectors
- Real API errors and responses
- CRD validation

---

## Running Specific Test Scenarios

### Scenario: Test Stale Detection
```bash
# Mock-based (fast)
pytest targetPoller/tests/test_cleanup.py::TestCleanupStaleDetection -v

# With real K8s
pytest targetPoller/tests/test_cleanup_envtest.py::TestCleanupWithEnvTest::test_cleanup_stale_scaninstance_real_k8s -v
```

### Scenario: Test Worker Threads
```bash
pytest targetPoller/tests/test_cleanup_workers.py::TestCleanupWorker -v
```

### Scenario: Test Concurrent Processing
```bash
pytest targetPoller/tests/test_cleanup_workers.py::TestCleanupWorkerConcurrency -v
```

### Scenario: Test Storage State Operations
```bash
pytest targetPoller/tests/test_storage_state.py::TestStorageStateQueries -v
```

### Scenario: Test End-to-End Cleanup with Real K8s
```bash
./run_envtest.sh
# or
pytest targetPoller/tests/test_cleanup_envtest.py::TestCleanupWithEnvTest::test_cleanup_stale_scaninstance_real_k8s -v
```

---

## Test Organization by Complexity

### Level 1: Unit Tests (Isolated Components)
- `test_storage_state.py` - Pure data model tests
- Individual worker tests in `test_cleanup_workers.py`

### Level 2: Integration Tests (Multiple Components)
- `test_cleanup.py` - Handler + K8s client (mocked) + StorageState
- Worker pool tests in `test_cleanup_workers.py`

### Level 3: Real Integration Tests (Real K8s)
- `test_cleanup_envtest.py` - Handler + Real K8s API + Real CRDs

---

## Test Execution Strategy

### Development Workflow (Fast Feedback):
```bash
# Run only mock tests (5 seconds)
pytest targetPoller/tests/ -v -m "not envtest"
```

### Pre-Commit Hook (Comprehensive):
```bash
# Run all tests including envtest (25 seconds)
pytest targetPoller/tests/ -v
```

### CI/CD Pipeline:
```bash
# Stage 1: Fast unit tests (parallel, fail fast)
pytest targetPoller/tests/ -v -m unit -x

# Stage 2: Integration tests (if unit tests pass)
pytest targetPoller/tests/ -v -m envtest
```

---

## Missing Test Coverage (Pending)

### 1. Discovery Phase
**Status**: Not implemented  
**Planned File**: `test_discovery.py`

**Scenarios Needed**:
- Backup discovery from storage
- Backup metadata parsing
- StorageState population
- Error handling during discovery

### 2. Handler-Specific Logic
**Status**: Not implemented  
**Planned Files**: 
- `test_tvk_handler.py` (TVK-specific logic)
- `test_tvo_handler.py` (TVO-specific logic)

**Scenarios Needed**:
- TVK backup format parsing
- TVO backup format parsing
- Handler-specific configuration
- Storage type handling

### 3. Prescan Component
**Status**: Not implemented  
**Planned File**: `test_prescan.py`

**Scenarios Needed**:
- Disk mounting logic
- Scan job creation
- Environment variable handling
- Cleanup logic

### 4. Full E2E Tests
**Status**: Not implemented  
**Planned File**: `test_e2e.py`

**Scenarios Needed**:
- Real K8s cluster (kind/minikube)
- Real NFS/S3 storage
- Real backup data
- Complete flow: mount → scan → cleanup

---

## Test Execution Time Breakdown

```
test_cleanup.py (20 tests)              ████░░  ~1.5s
test_cleanup_workers.py (34 tests)      ██████  ~2.5s
test_storage_state.py (37 tests)        ███░░░  ~1.0s
test_patterns.py (6 tests)              █░░░░░  ~0.3s
test_cleanup_envtest.py (8 tests)       ████████████████████  ~20s
──────────────────────────────────────────────────────────────
TOTAL (105 tests)                                      ~25s
```

---

## Test File Sizes

```
test_cleanup.py              1,027 lines
test_cleanup_workers.py      1,091 lines
test_storage_state.py          579 lines
test_cleanup_envtest.py        802 lines
test_patterns.py               396 lines
──────────────────────────────────────
TOTAL                        3,895 lines of test code
```

---

## Conclusion

The Target Poller test suite provides comprehensive coverage of the cleanup phase with:

- **97 fast mock-based unit tests** for rapid development feedback
- **8 envtest integration tests** for real K8s API validation
- **Clear separation** between unit and integration tests
- **Pattern examples** for writing new tests
- **Infrastructure scripts** for easy test execution
- **Same approach as Go controllers** for integration testing

The suite currently covers the **cleanup phase** thoroughly. The **discovery phase**, **handler-specific logic**, and **prescan component** are pending test implementation.
