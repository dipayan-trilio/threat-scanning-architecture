FROM python:3.12-slim

LABEL name=threat-scanning-datastore-attacher
LABEL vendor=Trilio\ Data\ Inc.
LABEL version=VERSION
LABEL release=RELEASE
LABEL summary=Threat\ Scanning\ Datastore\ Attacher
LABEL description=Threat\ Scanning\ Datastore\ Attacher\ with\ PreScan,\ Target\ Validation\ and\ Polling
LABEL maintainer=Trilio\ Data\ Inc.

ARG TARGETOS
ARG TARGETARCH

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    fuse \
    libfuse-dev \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    python3-dev \
    nfs-common \
    jq \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install s3fuse with private index using secret
# RUN --mount=type=secret,id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL \
#     pip3 install --upgrade pip setuptools wheel && \
#     pip3 install --no-cache-dir 's3fuse==5.2.0' --extra-index-url ${S3_FUSE_PIP_INDEX_URL}

RUN pip3 install --upgrade pip setuptools wheel

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Install additional dependencies for targetPoller and validation
RUN pip3 install --no-cache-dir \
    jsonformatter>=0.3.1 \
    azure-storage-blob>=12.25.1

# Create mount directories
RUN mkdir -p /triliodata && \
    mkdir -p /triliodata-temp && \
    mkdir -p /opt/threat-scanning/datastore-attacher

# Create Python symlink
RUN ln -sf /usr/local/bin/python3 /usr/bin/python3 && \
    ln -sf /usr/local/bin/python3 /usr/bin/python

# Configure FUSE
RUN echo $'# mount_max = 1000 \nuser_allow_other' >> /etc/fuse.conf

# Install yq
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; \
    elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi && \
    curl -Lo /usr/bin/yq https://github.com/mikefarah/yq/releases/download/2.2.1/yq_linux_${ARCH} && \
    chmod +x /usr/bin/yq

# Copy datastore-attacher code
COPY . /opt/threat-scanning/datastore-attacher/

RUN pip3 install --no-cache-dir /opt/threat-scanning/datastore-attacher/s3fuse-5.2.0a2-py3-none-any.whl

RUN rm ./opt/threat-scanning/datastore-attacher/s3fuse-5.2.0a2-py3-none-any.whl

WORKDIR /opt/threat-scanning

# Set PYTHONPATH so Python can find the datastore-attacher modules
ENV PYTHONPATH=/opt/threat-scanning/datastore-attacher

# Set base path for scripts
ENV BASE_PATH=/opt/threat-scanning/datastore-attacher

# Create convenience scripts for different operations
RUN echo '#!/bin/bash\n\
python3 /opt/threat-scanning/datastore-attacher/scripts/target_validations.py "$@"' \
> /usr/local/bin/target-validator && chmod +x /usr/local/bin/target-validator

RUN echo '#!/bin/bash\n\
python3 -m prescan.cli "$@"' \
> /usr/local/bin/prescan && chmod +x /usr/local/bin/prescan

RUN echo '#!/bin/bash\n\
python3 /opt/threat-scanning/datastore-attacher/targetPoller/main.py "$@"' \
> /usr/local/bin/target-poller && chmod +x /usr/local/bin/target-poller

# Default command
CMD ["/bin/bash"]
