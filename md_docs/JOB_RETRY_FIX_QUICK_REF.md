# Job Retry Fix - Quick Reference

## Issue
Scan jobs were failing immediately after the first pod failure, despite being configured with `BackoffLimit: 3`.

## Root Cause
`GetJobStatus()` was checking `job.Status.Failed > 0` instead of the `JobFailed` condition, causing premature failure detection.

## Fix
Modified `pkg/helpers/job_helper.go::GetJobStatus()` to:
- Prioritize Kubernetes `JobFailed` condition (authoritative source)
- Treat failed pod attempts without `JobFailed` condition as `InProgress` (job is retrying)

## Impact
- **Scan Jobs** (`BackoffLimit: 3`): Now retry up to 3 times before marking ScanInstance as `Failed`
- **Validation/Poller Jobs** (`BackoffLimit: 0`): No behavior change (still fail immediately)

## Testing
```bash
./verify_job_retry_fix.sh
```

## Documentation
See [md_docs/JOB_RETRY_FIX.md](md_docs/JOB_RETRY_FIX.md) for detailed explanation.
