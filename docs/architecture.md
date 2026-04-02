# Threat Scanning Architecture - Executive Demo Overview

## System Architecture

![System Architecture](./images/architecture.png)

The architecture consists of:

- **Threat Scanning Controller**: Orchestrates the entire scanning workflow
- **Backup Target**: S3 storage containing VM backups to be scanned
- **Reporting Target**: S3 storage for scan reports and findings
- **Forensic Engine (Scan Job)**: Performs threat analysis on backups
- **Threat DB**: External threat intelligence database (CVE, Malware, IOCs)
- **Redis Cache & Cache DB (Postgres)**: Store scan results and metrics
- **Grafana Dashboard**: Visualizes security insights from the database

## End-to-End Workflow

```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'fontSize':'16px', 'fontFamily':'arial'}}}%%
flowchart TB
    Start([User Creates Target])
    
    Stage1[Target Creation]
    Stage2[Polling & Backup Discovery]
    Stage3[ScanInstance Creation]
    Stage4[Pre-scan Processing]
    Stage5[Threat Scanning]
    Stage6[Report Upload]
    Stage7[Grafana Visualization]
    
    End([Scan Complete])
    
    Start --> Stage1
    Stage1 --> Stage2
    Stage2 --> Stage3
    Stage3 --> Stage4
    Stage4 --> Stage5
    Stage5 --> Stage6
    Stage6 --> Stage7
    Stage7 --> End
    
    style Start fill:#4A90E2,stroke:#2E5C8A,stroke-width:3px,color:#fff
    style End fill:#50C878,stroke:#2D7A4A,stroke-width:3px,color:#fff
    style Stage1 fill:#9B59B6,stroke:#6C3A80,stroke-width:2px,color:#fff
    style Stage2 fill:#1ABC9C,stroke:#148F77,stroke-width:2px,color:#fff
    style Stage3 fill:#E74C3C,stroke:#A93226,stroke-width:2px,color:#fff
    style Stage4 fill:#F39C12,stroke:#C87F0A,stroke-width:2px,color:#fff
    style Stage5 fill:#27AE60,stroke:#1E8449,stroke-width:2px,color:#fff
    style Stage6 fill:#E67E22,stroke:#BA4A00,stroke-width:2px,color:#fff
    style Stage7 fill:#48C9B0,stroke:#138D75,stroke-width:2px,color:#fff
```

## Component Overview

### 1. Threat Scanning Controller

Kubernetes controller that orchestrates the entire scanning lifecycle. Manages scan job creation, monitors progress, and handles error recovery.

### 2. Scan Job (Forensic Engine)

Unified scanning workload that discovers backups, extracts metadata, performs threat analysis using the Threat Database, and publishes results to Redis and Postgres.

### 3. Backup Target

S3 or NFS storage containing VM backup snapshots and disk images to be scanned. Provides read-only access for security analysis.

### 4. Reporting Target

S3-compatible storage for archiving threat scan reports and detailed security findings in JSON format.

### 5. Threat Database

External threat intelligence source providing up-to-date CVE database, malware signatures, known attack indicators, and security intelligence feeds.

### 6. Redis Database

High-performance in-memory cache for real-time scan metrics and intermediate scan results.

### 7. Postgres Database (Cache DB)

Relational database storing historical scan results, threat analytics, and time-series data. Primary data source for Grafana dashboards.

### 8. Grafana Dashboard

Interactive visualization platform that queries Postgres to display threat heatmaps, trends, statistics, and executive summary views.

#### Consolidated Dashboard

![Consolidated Dashboard](./images/grafana_dashboard_2.png)

The consolidated dashboard provides an overview across all backups:
- **Overall Threat Statistics**: Aggregated metrics across all scanned backups
- **Backup Plan Evolution**: Trends showing threat patterns over time
- **Cross-Backup Analysis**: Comparative views of security posture
- **High-Level Insights**: Executive summary of the entire backup infrastructure

#### Detailed Backup Insights

![Detailed Dashboard](./images/grafana.png)

The detailed dashboard provides deep insights into individual backups:
- **Unique Threats**: Count of distinct threats discovered in a specific backup
- **Threat IOCs**: Indicators of Compromise detected
- **Total Threats**: Overall threat count for the backup
- **IOC Risk Rate**: Percentage of critical security indicators
- **Threat Activity Heatmap**: Visual representation of threat density over time
- **Trend Analysis**: Historical threat patterns and evolution for the backup

## Key Benefits

✅ **Automated Security**: Continuous threat scanning of backup data without manual intervention

✅ **Kubernetes-Native**: Seamlessly integrates with Kubernetes workflows and GitOps practices

✅ **Scalable Architecture**: Handles large backup datasets with parallel job execution

✅ **Comprehensive Threat Detection**: Leverages multiple threat intelligence sources

✅ **Actionable Insights**: Clear visualizations help prioritize security responses

✅ **Storage Agnostic**: Works with various S3-compatible storage backends

---

*This document provides a high-level overview for executive demonstrations. Technical implementation details are available in separate documentation.*
