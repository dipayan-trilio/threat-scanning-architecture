FROM python:3.9-alpine

LABEL name=threat-scanning-datastore-attacher
LABEL vendor=Trilio\ Data\ Inc.
LABEL version=VERSION
LABEL release=RELEASE
LABEL summary=Threat\ Scanning\ Datastore\ Attacher
LABEL description=Threat\ Scanning\ Datastore\ Attacher
LABEL maintainer=Trilio\ Data\ Inc.

ARG TARGETOS
ARG TARGETARCH

# Install system dependencies
RUN apk add --no-cache \
    bash \
    curl \
    fuse \
    fuse-dev \
    gcc \
    g++ \
    make \
    musl-dev \
    libffi-dev \
    openssl-dev \
    python3-dev \
    cargo \
    rust \
    nfs-utils \
    jq \
    tzdata

# Install Python packages
RUN --mount=type=secret,id=S3_FUSE_PIP_INDEX_URL,env=S3_FUSE_PIP_INDEX_URL \
    pip3 install --upgrade pip && \
    pip3 install --no-cache-dir 's3fuse==5.2.0' --extra-index-url ${S3_FUSE_PIP_INDEX_URL} && \
    pip3 install --no-cache-dir 'kubernetes==33.1.0' && \
    pip3 install --no-cache-dir jsonformatter==0.3.1 && \
    pip3 install --no-cache-dir azure-storage-blob==12.25.1 && \
    pip3 install --no-cache-dir boto3==1.35.80

# Create mount directories
RUN mkdir -p /triliodata && mkdir -p /triliodata-temp

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

RUN mkdir -p /opt/threat-scanning/datastore-attacher

COPY . /opt/threat-scanning/datastore-attacher/

WORKDIR /opt/threat-scanning

# Set PYTHONPATH so Python can find the datastore-attacher modules
ENV PYTHONPATH=/opt/threat-scanning/datastore-attacher

CMD ["/bin/bash"]

