# Prescan Error Annotation Flow Diagram

## Complete Implementation Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         USER CREATES SCANINSTANCE                            │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CONTROLLER CREATES PRESCAN JOB                            │
│                                                                              │
│  Job Spec:                                                                   │
│    env:                                                                      │
│    - name: JOB_NAME                                                          │
│      valueFrom:                                                              │
│        fieldRef:                                                             │
│          fieldPath: metadata.labels['job-name']                              │
│    - name: JOB_NAMESPACE                                                     │
│      valueFrom:                                                              │
│        fieldRef:                                                             │
│          fieldPath: metadata.namespace                                       │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PRESCAN JOB STARTS (Python)                           │
│                                                                              │
│  1. Read JOB_NAME and JOB_NAMESPACE from environment                         │
│  2. Validate backup path                                                     │
│  3. Detect backup type                                                       │
│  4. Extract metadata & detect VMs                                            │
│  5. Update ScanInstance status                                               │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    ▼                         ▼
        ┌───────────────────┐     ┌──────────────────────┐
        │   SUCCESS PATH    │     │    FAILURE PATH      │
        └─────────┬─────────┘     └──────────┬───────────┘
                  │                           │
                  ▼                           ▼
    ┌──────────────────────┐    ┌────────────────────────────────────────┐
    │ Job Completes        │    │ Exception Caught                        │
    │ exit(0)              │    │                                         │
    │                      │    │ try:                                    │
    │ Annotation:          │    │     validate_backup_path(path)          │
    │   (none for success) │    │ except FileNotFoundError as e:          │
    └──────────┬───────────┘    │     error_msg = get_path_validation_... │
               │                │     update_job_error_annotation(...)    │
               │                │     exit(1)                             │
               │                └─────────────┬──────────────────────────┘
               │                              │
               │                              ▼
               │                ┌─────────────────────────────────────────┐
               │                │ Job Annotation Set                      │
               │                │                                         │
               │                │ annotations:                            │
               │                │   threatscanning.trilio.io/prescan-     │
               │                │     error: "Backup path is inaccessible:│
               │                │     Backup path does not exist:         │
               │                │     /triliodata/plan1/backup123"        │
               │                │                                         │
               │                │ status:                                 │
               │                │   failed: 1                             │
               │                └─────────────┬──────────────────────────┘
               │                              │
               └──────────────┬───────────────┘
                              │
                              ▼
               ┌───────────────────────────────────────────┐
               │   JOB STATUS CHANGE TRIGGERS CONTROLLER   │
               └───────────────┬───────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   CONTROLLER RECONCILIATION                                  │
│                                                                              │
│  jobStatus := GetJobStatus(preScanJob)                                      │
│                                                                              │
│  switch jobStatus {                                                          │
│    case Completed:                                                           │
│      ✓ Update condition: PreScan/Completed                                  │
│      ✓ Generate event: PreScanCompleted                                     │
│                                                                              │
│    case Failed:                                                              │
│      ✓ Read annotation: preScanJob.Annotations[PrescanErrorAnnotation]      │
│      ✓ Update condition: PreScan/Failed with error reason                   │
│      ✓ Generate event: PreScanFailed with error message                     │
│      ✓ Update overall status: ScanInstance.Status = Failed                  │
│  }                                                                           │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SCANINSTANCE STATUS UPDATED                            │
│                                                                              │
│  status:                                                                     │
│    status: Failed                                                            │
│    type: TVK                                                                 │
│    scanLocations: []                                                         │
│    condition:                                                                │
│    - phase: PreScan                                                          │
│      status: Failed                                                          │
│      reason: "Backup path is inaccessible: Backup path does not exist:      │
│                /triliodata/plan1/backup123"                                  │
│      timestamp: "2026-02-16T12:00:00Z"                                       │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       KUBERNETES EVENT GENERATED                             │
│                                                                              │
│  Type:    Warning                                                            │
│  Reason:  PreScanFailed                                                      │
│  Message: Pre-scan failed for ScanInstance test-scan: Backup path is        │
│           inaccessible: Backup path does not exist: /triliodata/plan1/...   │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          USER SEES ERROR                                     │
│                                                                              │
│  $ kubectl describe scaninstance test-scan                                  │
│  Events:                                                                     │
│    Type     Reason          Message                                          │
│    ----     ------          -------                                          │
│    Warning  PreScanFailed   Pre-scan failed for ScanInstance test-scan:     │
│                             Backup path is inaccessible: Backup path does   │
│                             not exist: /triliodata/plan1/backup123          │
│                                                                              │
│  $ kubectl get scaninstance test-scan -o jsonpath='{.status.condition...}'  │
│  Backup path is inaccessible: Backup path does not exist: /triliodata/...   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Interactions

```
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│   Prescan    │          │     Job      │          │  Controller  │
│     Job      │          │  Annotation  │          │              │
│   (Python)   │          │  (K8s API)   │          │    (Go)      │
└──────┬───────┘          └──────┬───────┘          └──────┬───────┘
       │                         │                         │
       │ 1. Validate path        │                         │
       │    (fails)               │                         │
       │                         │                         │
       │ 2. Format error         │                         │
       │    message              │                         │
       │                         │                         │
       │ 3. Update annotation───>│                         │
       │    (K8s API call)       │                         │
       │                         │                         │
       │ 4. Exit with code 1     │                         │
       │                         │                         │
       │                         │ 5. Job status changed   │
       │                         │    (triggers watch)────>│
       │                         │                         │
       │                         │ 6. Read annotation<─────│
       │                         │                         │
       │                         │                         │ 7. Update
       │                         │                         │    ScanInstance
       │                         │                         │
       │                         │                         │ 8. Generate
       │                         │                         │    Event
       │                         │                         │
       └─────────────────────────┴─────────────────────────┘
```

## Error Message Examples

### Path Not Found
```
Backup path is inaccessible: Backup path does not exist: /triliodata/35a9f73b-e134-4afa-a896-53e4b10ca70f/1bbba2bd-a28c-4691-a588-284ac26f97f9
```

### Path Not a Directory
```
Backup path is inaccessible: Backup path is not a directory: /triliodata/plan1/backup.json
```

### Permission Denied
```
Backup path is inaccessible: Backup path is not readable: /triliodata/restricted-backup
```

### Generic Error (Fallback)
```
Prescan validation failed: tvk-meta.json not found at /triliodata/plan1/backup123/tvk-meta.json
```

## Key Features

✅ **Detailed Error Messages**: Exact path and error type
✅ **Persistent**: Survives pod deletion
✅ **Event Generation**: Visible in kubectl describe
✅ **Idempotent**: No duplicate conditions/events
✅ **Backward Compatible**: Falls back to default message
✅ **Size-Limited**: 256KB truncation prevents issues
✅ **User-Friendly**: No need to check pod logs
✅ **Actionable**: Error messages guide troubleshooting

## Monitoring & Observability

### For Operators
```bash
# Quick check if any prescan failures
kubectl get scaninstance -o json | jq '.items[] | select(.status.status=="Failed") | {name: .metadata.name, reason: .status.condition[] | select(.phase=="PreScan").reason}'

# Check events across all ScanInstances
kubectl get events --field-selector reason=PreScanFailed --sort-by='.lastTimestamp'
```

### For Developers
```bash
# Check job annotations for debugging
kubectl get jobs -n threat-scanning-system -o json | jq '.items[] | select(.metadata.annotations["threatscanning.trilio.io/prescan-error"] != null) | {name: .metadata.name, error: .metadata.annotations["threatscanning.trilio.io/prescan-error"]}'
```

---

**Implementation Status**: ✅ **COMPLETE AND READY FOR TESTING**
