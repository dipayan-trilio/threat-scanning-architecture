#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail


DS_BASE_PATH=${DATASTORE_BASE_PATH:="/data"}

NFS_BASE_PATH="${DS_BASE_PATH}/nfs"
S3_BASE_PATH="${DS_BASE_PATH}/s3"

# create data dirs that will hold entire mountpoints for nfs and s3
create_dir(){
    mkdir -p "$1"
}

create_dir "${NFS_BASE_PATH}"

create_dir "${S3_BASE_PATH}"
