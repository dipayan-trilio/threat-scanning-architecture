"""
Threat Scanning Poller

A Kubernetes CronJob that performs:
1. Cleanup of stale ScanInstance CRs
2. Discovery of new backups for scanning
3. Monitoring and metrics updates
"""

__version__ = '1.0.0'
