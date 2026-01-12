TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S'

# Target-CRD constants
TARGET_CRD_PLURAL = 'targets'  # str | the custom resource's plural name.
BACKUP_KIND_PLURAL = 'backups'  # str | the custom resource's plural name.
BACKUPPLAN_KIND_PLURAL = 'backupplans'  # str | the custom resource's plural name.

# For TPRs this would be lowercase plural kind.
# str | the custom resource's group
TVK_CRD_GROUP = 'threatscanning.trilio.io'
TVK_CRD_VERSION = 'v1'  # str | the custom resource's version
TARGET_CRD_NAMESPACE = "default"

NFS = 'nfs'
S3 = 's3'
AZUREBLOB = 'azureblob'
YAML_TRUE = 'yes'
YAML_FALSE = 'no'
ALL_DATASTORES = 'all'
DEFAULT_DATASTORE = 'defaultDatastore'
NFS_DATASTORE_NAME = "test-nfs-1"
S3_DATASTORE_NAME = "test-s3-1"
NFS_EXPORT = "nfsExport"
OBJECT_STORE = "objectstore"
OBJECT_LOCKING_ENABLE = "objectLockingEnabled"

# trilio-secret keys
DATASTORE = 'datastore'
RETENTION_POLICY = 'retentionPolicy'
DEFAULT_TIMEOUTS = 'defaultTimeouts'

# trilio-secret Datastore metadata keys
DATASTORE_TYPE = 'storageType'
MOUNT_OPTIONS = 'mountOptions'
SERVER = 'server'
SHARE = 'share'
METADATA = 'metaData'
NAME = 'name'

# Default directories, files and paths
DEFAULT_SCRIPTS_PATH = 'scripts/'
TMP_VAULT_DIR = '/tmp/trilio-tmp'
S3_VAULT_CONF = 'vault.conf'
S3_FUSE_DIR = 's3fuse'
DEFAULT_DATASTORE_BASE_PATH = '/triliodata'
TEMP_DATASTORE_BASE_PATH = '/triliodata-temp'
TRILIO_SECRET_FILE = 'trilio-secret'
TRILIO_SECRET_PATH = '/etc/secret'
LOG_FILE_PATH = '/tmp/s3_log.txt'
VENDOR = 'vendor'
OTHER_VENDOR = 'Other'

# S3 vault.conf keys
S3_SSL = False
S3_SKIP_CERT_VERIFICATION = 'skipCertVerification'
S3_ENABLE_THREADPOOL = True
S3_SUPPORT_EMPTY_DIR = False
S3_SIGNATURE_VERSION = 'default'
S3_AUTH_VERSION = 'DEFAULT'
S3_FUSE_FILE = 's3vaultfuse.py'
S3_ACCESS_KEY_ID = 'accessKeyID'
S3_ACCESS_KEY = 'accessKey'
S3_SECRET_KEY = 'secretKey'
S3_BUCKET = 's3Bucket'
S3_ENDPOINT_URL = "s3EndpointUrl"
S3_REGION_NAME = 'regionName'
S3_STORAGE_DAS_DEVICE = 'storageDasDevice'
S3_STORAGE_NFS_SUPPORT = 'storageNFSSupport'
S3_MAX_POOL_CONNECTIONS = '500'
S3_READ_TIMEOUT = 'S3_READ_TIMEOUT'
DEFAULT_CONF_SECTION = '[DEFAULT]'
VERBOSE = True
LOGGING_LEVEL = {
    "INFO": "info",
    "DEBUG": "debug",
    "WARN": "warn",
    "ERROR": "error",
}
WORKER_POOL_SIZE = 5

# Log level constants
DEBUG_LOG_LEVEL = "DEBUG"

# mount consts
PYTHON_BINARY = "/usr/bin/python3"
DEFAULT_WAIT_TIMEOUT = 2
CONVERT_TO_SECONDS = 60
OBJECT_STORE_MOUNT_FILE = "run_fuse_in_background.py"
CACHE_SIZE = 20

# K8s Resource name
SECRET_NAME = "secretName"
SECRET_NAMESPACE = "secretNamespace"

# tvk target secret
TARGET_SECRET_PATH = "/tvk/target-secret/"
SSL_CERT_FILE_NAME = "ca-bundle.pem"
VM_MOUNT = "VM_MOUNT"

# Vendor
AZURE_VENDOR = "Azure"
AWS_VENDOR = "AWS"

# Minio constants
MINIO_URL = "http://127.0.0.1:9000/"
MinIO_Gateway_URL = "http://127.0.0.1:9000/minio/health/live"
MinIOWait = 5
MinIORootUserKey = "MINIO_ROOT_USER"
MinIORootPasswdKey = "MINIO_ROOT_PASSWORD"
MinIOConfigPath = "/tmp/.minio"
MinIOENDPOINT = "ENDPOINT"
MinIOExecutable = "/opt/tvk/minio"
_MINIO_SERVER_DEBUG = "_MINIO_SERVER_DEBUG"
_MINIO_SERVER_DEBUG_ON = "on"

# proxy consts
ProxyCABundle = "PROXY_CA_CONFIGMAP"
ProxyCAMountPath = "/proxy-certs"

# Credential Hash
CREDENTIAL_HASH_ANNOTATION = "trilio.io/credentials-hash"

TVKConfig = "threat-scanning-config"
LogLevelEnv = "LOG_LEVEL"
DefaultLogLevel = "Info"
PodUID = "POD_UID"
TVKVersion = "RELEASE_TAG"
InstanceID = "INSTANCE_ID"
TargetKind = "Target"
DatastoreAttacherService = "DatastoreAttacher"
ValidationService = "Validation"

# Target Types for Threat Scanning
TARGET_TYPE_BACKUP = "backup"
TARGET_TYPE_REPORTING = "reporting"

PVQcow2Name = "pv.qcow2"

# trilio cr json filenames
BACKUP_JSON_FILE_NAME = "backup.json"
BACKUPPLAN_JSON_FILE_NAME = "backupplan.json"
CLOUD_INIT_DATA_DIR_NAME = "/opt/tvk/cloudinit-data"
FILE_RECOVERY_VM_ENCRYPTION_DIR_NAME = "encryption-metadata"
ENCRYPTION_FILE_NAME = "encryptKey"

# trilio json response keys
SUCCESS = "success"
ERROR = "error"

DEFAULT_MAX_POOL_SIZE = 100
