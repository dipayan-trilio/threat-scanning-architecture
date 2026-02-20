# Datastore Attacher Docker Image

This Docker image provides a unified container for running:
- **Target Validation** - Validates backup and reporting targets
- **PreScan** - Pre-scan validation for backup instances
- **Target Poller** - Polls targets for new backups and manages ScanInstance lifecycle

## Building the Image

### Prerequisites

The build requires access to Trilio's private PyPI repository for s3fuse installation. You need to provide the index URL as a Docker secret.

### Basic Build

```bash
cd datastore-attacher

# Build with secret for s3fuse installation
export S3_FUSE_PIP_INDEX_URL="https://24IhR6-gQgH3MfsbfId7qjzfkkwYzsCc3Q@pypi.fury.io/triliodata/"

docker build \
  --secret id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL \
  -t threat-scanning-datastore-attacher:latest \
  .
```

**Note:** Docker BuildKit must be enabled for secrets support. Enable it with:
```bash
export DOCKER_BUILDKIT=1
```

### Build with Version Tags

```bash
export S3_FUSE_PIP_INDEX_URL="https://24IhR6-gQgH3MfsbfId7qjzfkkwYzsCc3Q@pypi.fury.io/triliodata/"

docker build \
  --secret id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL \
  --build-arg VERSION=1.0.0 \
  --build-arg RELEASE=1 \
  -t threat-scanning-datastore-attacher:1.0.0 \
  .
```

### Multi-Architecture Build

```bash
export S3_FUSE_PIP_INDEX_URL="https://24IhR6-gQgH3MfsbfId7qjzfkkwYzsCc3Q@pypi.fury.io/triliodata/"

docker buildx build \
  --secret id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL \
  --platform linux/amd64,linux/arm64 \
  -t threat-scanning-datastore-attacher:latest \
  --push \
  .
```

### Alternative: Build from File Secret

If you prefer to store the URL in a file:

```bash
# Create secret file
echo "https://24IhR6-gQgH3MfsbfId7qjzfkkwYzsCc3Q@pypi.fury.io/triliodata/" > .s3fuse-index-url

# Build using file secret
docker build \
  --secret id=S3_FUSE_PIP_INDEX_URL,src=.s3fuse-index-url \
  -t threat-scanning-datastore-attacher:latest \
  .

# Clean up
rm .s3fuse-index-url
```

## Image Contents

### Installed Components

- **Python 3.9** - Base runtime
- **s3fuse 5.2.0** - S3 filesystem mounting
- **FUSE** - Filesystem in userspace
- **NFS utilities** - NFS mount support
- **Kubernetes client** - K8s API interaction
- **boto3** - AWS S3 client
- **Azure Storage Blob** - Azure blob storage support

### Directory Structure

```
/opt/threat-scanning/datastore-attacher/
├── mount_utility/          # Mount utilities for NFS/S3
├── prescan/                # PreScan validation module
├── targetPoller/           # Target polling module
├── scripts/                # Validation scripts
└── shared/                 # Shared utilities (backup detection, metadata)

/triliodata/                # Default mount point for targets
/triliodata-temp/           # Temporary mount point
```

### Convenience Scripts

The image includes wrapper scripts for easy execution:

- `/usr/local/bin/target-validator` - Run target validation
- `/usr/local/bin/prescan` - Run prescan validation
- `/usr/local/bin/target-poller` - Run target poller

## Usage Examples

### 1. Target Validation

#### Validate Backup Target (Read-Only)

```bash
docker run --rm \
  --privileged \
  -v /path/to/kubeconfig:/root/.kube/config \
  threat-scanning-datastore-attacher:latest \
  target-validator \
    --target-name=minio-target \
    --type=backup \
    --group=threatscanning.trilio.io \
    --version=v1
```

#### Validate Reporting Target (Write-Enabled)

```bash
docker run --rm \
  --privileged \
  -v /path/to/kubeconfig:/root/.kube/config \
  threat-scanning-datastore-attacher:latest \
  target-validator \
    --target-name=reporting-target \
    --type=reporting \
    --group=threatscanning.trilio.io \
    --version=v1
```

### 2. PreScan Validation

```bash
docker run --rm \
  --privileged \
  -v /path/to/kubeconfig:/root/.kube/config \
  threat-scanning-datastore-attacher:latest \
  prescan \
    --scan-instance=sample-scan-instance \
    --namespace=default
```

### 3. Target Poller

```bash
docker run --rm \
  --privileged \
  -v /path/to/kubeconfig:/root/.kube/config \
  threat-scanning-datastore-attacher:latest \
  target-poller \
    --target-name=minio-target \
    --namespace=trilio-system \
    --reporting-target=test-s3-target-3
```

### 4. Interactive Shell

```bash
docker run -it --rm \
  --privileged \
  -v /path/to/kubeconfig:/root/.kube/config \
  threat-scanning-datastore-attacher:latest \
  /bin/bash
```

## Kubernetes Deployment

### Job for Target Validation

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: threat-scan-validator-minio-target
  namespace: threat-scanning-system
spec:
  template:
    spec:
      serviceAccountName: threat-scanning-controller
      containers:
      - name: validator
        image: threat-scanning-datastore-attacher:latest
        command: ["/usr/local/bin/target-validator"]
        args:
          - "--target-name=minio-target"
          - "--type=backup"
          - "--group=threatscanning.trilio.io"
          - "--version=v1"
        securityContext:
          privileged: true
          capabilities:
            add: ["SYS_ADMIN"]
        volumeMounts:
        - name: credentials
          mountPath: /etc/credentials
          readOnly: true
      volumes:
      - name: credentials
        secret:
          secretName: minio-credentials
      restartPolicy: Never
```

### Job for PreScan

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: threat-scan-prescan-sample-scan
  namespace: threat-scanning-system
spec:
  template:
    spec:
      serviceAccountName: threat-scanning-controller
      containers:
      - name: prescan
        image: threat-scanning-datastore-attacher:latest
        command: ["/usr/local/bin/prescan"]
        args:
          - "--scan-instance=sample-scan-instance"
        securityContext:
          privileged: true
          capabilities:
            add: ["SYS_ADMIN"]
      restartPolicy: Never
```

### CronJob for Target Poller

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: threat-scan-poller-minio-target
  namespace: threat-scanning-system
spec:
  schedule: "*/5 * * * *"  # Every 5 minutes
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: threat-scanning-controller
          containers:
          - name: poller
            image: threat-scanning-datastore-attacher:latest
            command: ["/usr/local/bin/target-poller"]
            args:
              - "--target-name=minio-target"
              - "--namespace=trilio-system"
              - "--reporting-target=test-s3-target-3"
            securityContext:
              privileged: true
              capabilities:
                add: ["SYS_ADMIN"]
            env:
            - name: POLLER_SCHEDULE
              value: "*/5 * * * *"
          restartPolicy: Never
```

## Environment Variables

### Common Variables

- `PYTHONPATH` - Set to `/opt/threat-scanning/datastore-attacher`
- `BASE_PATH` - Set to `/opt/threat-scanning/datastore-attacher`

### Target Validation

- `INSTALL_NAMESPACE` - Namespace for threat scanning system (default: `threat-scanning-system`)

### Target Poller

- `POLLER_SCHEDULE` - Cron schedule for polling (default: `*/5 * * * *`)
- `IGNORE_RECENT_UPDATES_MINUTES` - Ignore backups updated within N minutes (default: `5`)

## Security Considerations

### Privileged Mode

The container requires `--privileged` mode or specific capabilities for:
- **FUSE mounting** - For S3 filesystem mounting
- **NFS mounting** - For NFS target access

Minimum required capabilities:
```yaml
securityContext:
  privileged: true
  capabilities:
    add:
      - SYS_ADMIN
```

### Service Account

The container needs a Kubernetes service account with permissions to:
- Read Target CRs
- Create/Update/Delete ScanInstance CRs
- Read Secrets (for target credentials)
- Read ConfigMaps (for SSL certificates)

## Troubleshooting

### Build Issues

#### Docker BuildKit Not Enabled

If you see an error like "unknown flag: --secret":

```bash
# Enable BuildKit
export DOCKER_BUILDKIT=1

# Or use buildx
docker buildx build --secret id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL ...
```

#### S3fuse Installation Fails

If s3fuse installation fails during build:

```bash
# Verify the secret is set
echo $S3_FUSE_PIP_INDEX_URL

# Should output: https://24IhR6-gQgH3MfsbfId7qjzfkkwYzsCc3Q@pypi.fury.io/triliodata/

# Try building with verbose output
docker build --progress=plain \
  --secret id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL \
  -t threat-scanning-datastore-attacher:latest .
```

### FUSE Mount Issues

If you see errors like "fusermount: failed to open /dev/fuse":

```bash
# Ensure container is running in privileged mode
docker run --privileged ...

# Or add specific capabilities
docker run --cap-add SYS_ADMIN --device /dev/fuse ...
```

### S3 Connection Issues

For self-signed certificates:

```bash
# Set environment variable to skip SSL verification (not recommended for production)
docker run -e AWS_CA_BUNDLE="" ...
```

### Kubernetes API Connection

Ensure kubeconfig is properly mounted:

```bash
docker run -v ~/.kube/config:/root/.kube/config:ro ...
```

Or use in-cluster configuration when running as a Kubernetes Job/Pod.

### Python Module Import Errors

If you see "ModuleNotFoundError":

```bash
# Verify PYTHONPATH is set
docker run threat-scanning-datastore-attacher:latest \
  python3 -c "import sys; print(sys.path)"

# Should include: /opt/threat-scanning/datastore-attacher
```

## Development

### Local Testing

```bash
# Build image
export S3_FUSE_PIP_INDEX_URL="https://24IhR6-gQgH3MfsbfId7qjzfkkwYzsCc3Q@pypi.fury.io/triliodata/"
export DOCKER_BUILDKIT=1

docker build \
  --secret id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL \
  -t threat-scanning-datastore-attacher:dev \
  .

# Run with local code mounted (for development)
docker run -it --rm \
  --privileged \
  -v $(pwd):/opt/threat-scanning/datastore-attacher \
  -v ~/.kube/config:/root/.kube/config:ro \
  threat-scanning-datastore-attacher:dev \
  /bin/bash
```

### Debugging

```bash
# Run with verbose logging
docker run --rm \
  --privileged \
  -e LOG_LEVEL=DEBUG \
  threat-scanning-datastore-attacher:latest \
  target-validator --target-name=minio-target --type=backup
```

## Image Size Optimization

Current image is based on `python:3.9-slim` for balance between size and functionality.

To further reduce size:
- Use `python:3.9-alpine` (requires more build dependencies)
- Use multi-stage builds
- Remove unnecessary dependencies

## License

Copyright © Trilio Data Inc.

