import datetime
import errno
import shutil

import os
import shlex
import subprocess
import sys
import time
import threading
import requests
import boto3
import botocore

from io import BytesIO

from distutils import dir_util

from mount_utility import constants
from mount_utility import logger
logging = logger.logger


def get_secret_path_filename():
    if 'TRILIO_SECRET_PATH' in os.environ:
        secret_file_path = os.getenv('TRILIO_SECRET_PATH')
    else:
        secret_file_path = constants.TRILIO_SECRET_PATH
    if 'TRILIO_SECRET_FILE' in os.environ:
        secret_filename = os.getenv('TRILIO_SECRET_FILE')
    else:
        secret_filename = constants.TRILIO_SECRET_FILE
    return secret_file_path, secret_filename


def chmod_r(path, mode):
    """Recursive chmod
    :param path: str -> path of the file/folder whose permission to be changed
    :param mode: str -> mode of permission
    """
    try:
        os.chmod(path, mode)
        for root, dirnames, filenames in os.walk(path):
            for dirname in dirnames:
                os.chmod(os.path.join(root, dirname), mode)
            for filename in filenames:
                os.chmod(os.path.join(root, filename), mode)

    except OSError as os_err:
        raise Exception(os_err)
    except Exception as ex:
        raise Exception(ex)


def rm_rf(path):
    """Recursively removes file/directory
    :param path: str -> path of the folder/file to be removed
    """
    # Make sure all files are writeable and dirs executable to remove
    try:
        if os.path.isfile(path):
            chmod_r(path, 0o777)
            os.remove(path)
        elif os.path.isdir(path):
            chmod_r(path, 0o777)
            dir_util.remove_tree(path)

    except OSError as os_err:
        raise Exception(os_err)
    except Exception as ex:
        raise Exception(ex)


def mkdir(folder):
    """Create a new folder
    :param folder: str -> complete path of the folder to be created
    """
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except OSError as ex:
            # Ignore rare 'File exists' race conditions.
            raise Exception(ex)


def file_exists_in_dir(dir_path, file_name):
    """If a file exists in the directory return True else False
    :param dir_path: str -> path of the directory in which file to be checked
    :param file_name: str -> name of the file to be checked
    :return: bool -> True, if file exists at the path
    """
    for file in os.listdir(dir_path):
        if file_name in file:
            return True
    return False


def run_cmd(command, shell=False):
    cmd = shlex.split(command)
    if shell:
        cmd = command

    print("\n")
    logging.info("Executing command {}".format(command))
    logging.info(
        "{} command execution starting time: {}".format(
            command, datetime.datetime.now()))
    try:
        proc = subprocess.Popen(
            cmd,
            stderr=sys.stderr,
            stdout=sys.stdout,
            shell=shell,
            executable='/bin/bash')
        timeout = time.time() + constants.CONVERT_TO_SECONDS * \
            constants.DEFAULT_WAIT_TIMEOUT

        while proc.poll() is None:
            logging.info("waiting for command to complete...")
            time.sleep(2)
            if time.time() > timeout:
                raise Exception("{} command timeout.".format(command))

        logging.info(
            "{} command execution completion time: {}".format(
                command, datetime.datetime.now()))

        if proc.returncode:
            err_msg = "command :{}, exitcode :{}".format(
                command, proc.returncode)
            logging.critical(err_msg)
            raise Exception(err_msg)

        logging.info(
            "Command:{}, ExitCode:{}\n".format(
                command, proc.returncode))

    except subprocess.CalledProcessError as e:
        logging.error(e.output)
    except BaseException as e:
        logging.error(e)


def is_nested_dict(dictionary):
    """
    helper function to check if a dictionary is nested
    :param dictionary: dict -> dictionary to be checked
     if its a nested dictionary
    :return: bool -> True of its a nested dictionary else false
    """
    logging.info("Checking if the dictionary is nested")
    return any(isinstance(i, dict) for i in list(dictionary.values()))


def hash_boolean(key):
    """
    A hash function to return true if 'yes' else false
    :param key: str -> (Yes/No)
    :return: str -> Converts 'Yes' to 'True' and 'No' to 'False'
    """
    if key == constants.YAML_TRUE:
        return True
    return False


def append_create_dict_to_file(dictionary, file_path):
    """
    appends to a file or create new file and adds the passed dictionary
    :param dictionary: dict -> dictionary to write/append to the file
    :param file_path: str -> file path on which
    the operation needs to be performed
    :return:
    """
    try:
        logging.debug("Creating vault conf file at %s", file_path)
        with open(file_path, "a+") as filePointer:
            for key, value in list(dictionary.items()):
                tmp = key + " = '" + str(value) + "'\n"
                filePointer.write(tmp)
    except Exception as e:
        raise Exception(e)
    return True


def getSSLPath():
    ssl_cert_path = os.path.join(
        constants.TARGET_SECRET_PATH,
        constants.SSL_CERT_FILE_NAME)
    return ssl_cert_path


def create_vault_conf(metadata_list, base_path, vendor):
    """
    :param base_path: string -> base_path is the mountpoint path
    :param metadata_list: dict -> dictionary of the metadata passed from the secret
    :return: vault.conf dict -> dictionary of all the conf params
    """
    s3_auth_version = os.getenv(
        'S3_AUTH_VERSION') if 'S3_AUTH_VERSION' in os.environ else constants.S3_AUTH_VERSION
    s3_ssl = os.getenv(
        'S3_SSL') if 'S3_SSL' in os.environ else constants.S3_SSL

    if 'S3_ENABLE_THREADPOOL' in os.environ:
        s3_enable_threadpool = os.getenv('S3_ENABLE_THREADPOOL')
    else:
        s3_enable_threadpool = constants.S3_ENABLE_THREADPOOL

    if 'S3_SUPPORT_EMPTY_DIR' in os.environ:
        s3_support_empty_dir = os.getenv('S3_SUPPORT_EMPTY_DIR')
    else:
        s3_support_empty_dir = constants.S3_SUPPORT_EMPTY_DIR

    if 'S3_SIGNATURE_VERSION' in os.environ:
        s3_signature_version = os.getenv('S3_SIGNATURE_VERSION')
    else:
        s3_signature_version = constants.S3_SIGNATURE_VERSION

    if 'WORKER_POOL_SIZE' in os.environ:
        worker_pool_size = os.getenv('WORKER_POOL_SIZE')
    else:
        worker_pool_size = constants.WORKER_POOL_SIZE

    logging_level = os.getenv(constants.LogLevelEnv, "").lower() or constants.LOGGING_LEVEL.get("INFO")

    s3_old_data_dir = constants.TEMP_DATASTORE_BASE_PATH

    if not os.path.exists(s3_old_data_dir):
        try:
            s3_old_data_dir = os.path.join(base_path, base_path + "-temp")
            os.makedirs(s3_old_data_dir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

    s3_skip_cert_verification = metadata_list.get(constants.S3_SKIP_CERT_VERIFICATION)

    endpoint_url = metadata_list.get(constants.S3_ENDPOINT_URL, "")

    # Get s3_read_timeout from environment variable
    s3_read_timeout = os.environ.get(constants.S3_READ_TIMEOUT)
    if s3_read_timeout is None:
        logging.info(f"{constants.S3_READ_TIMEOUT} not found in environment variables, using default value")

    conf_data = {
        "vault_data_directory": base_path,
        "vault_data_directory_old": s3_old_data_dir,
        "vault_storage_das_device": metadata_list.get(constants.S3_STORAGE_DAS_DEVICE),
        "vault_storage_type": constants.AZUREBLOB if vendor == constants.AZURE_VENDOR else constants.S3,
        "vault_s3_auth_version": s3_auth_version,
        "vault_s3_access_key_id": metadata_list.get(constants.S3_ACCESS_KEY_ID),
        "vault_s3_secret_access_key": metadata_list.get(constants.S3_ACCESS_KEY),
        "vault_s3_region_name": metadata_list.get(constants.S3_REGION_NAME),
        "vault_s3_bucket": metadata_list.get(constants.S3_BUCKET),
        "vault_s3_endpoint_url": "" if not endpoint_url else endpoint_url,
        "vault_s3_signature_version": s3_signature_version,
        "vault_s3_ssl": str(s3_ssl),
        "vault_s3_ssl_verify": str(not s3_skip_cert_verification),
        "vault_enable_threadpool": str(s3_enable_threadpool),
        "vault_s3_support_empty_dir": str(s3_support_empty_dir),
        "vault_storage_nfs_export": metadata_list.get(constants.S3_STORAGE_NFS_SUPPORT),
        "verbose": str(constants.VERBOSE),
        "vault_logging_level": logging_level,
        "vault_s3_max_pool_connections": constants.S3_MAX_POOL_CONNECTIONS,
        "bucket_object_lock": str(metadata_list.get(constants.OBJECT_LOCKING_ENABLE, False)),
        "vault_cache_size": str(constants.CACHE_SIZE),
        "log_file": str(constants.LOG_FILE_PATH),
        "use_manifest_suffix": "True",
        "worker_pool_size": worker_pool_size
    }

    if vendor == constants.AZURE_VENDOR:
        conf_data["azure_immutability_enabled"] = str(metadata_list.get('hasDefaultRetentionPeriod', False))

    # Add s3_read_timeout to conf_data if it exists in environment
    if s3_read_timeout is not None:
        conf_data["vault_s3_read_timeout"] = str(s3_read_timeout)

    ssl_cert_path = getSSLPath()
    if os.path.exists(ssl_cert_path):
        conf_data["vault_s3_ssl"] = "true"
        conf_data["vault_s3_ssl_cert"] = ssl_cert_path
    return conf_data


def mount_object_datastore(metadata_list, base_path, vendor):
    """
    commands:
    create ${ROOT}/tmp/<ds_name>_vault.conf
    python3 ${ROOT}/s3fuse/s3vaultfuse.py --config-file=${ROOT}/tmp/<ds_name>_vault.conf
    :param metadata_list: dict -> dictionary of the metadata passed from the secret
    :param base_path: str -> base path, from where the datastore is to be mounted
    """
    # current working dir -> /datastore-attacher, the Workdir in the
    # container
    logging.info(
        "Mounting the %s datastore by the name %s",
        constants.OBJECT_STORE,
        metadata_list.get(
            constants.NAME))

    # Create the ./tmp directory
    logging.debug(
        "Creating a directory %s to keep the vault files for each fuse process",
        constants.TMP_VAULT_DIR)
    mkdir(constants.TMP_VAULT_DIR)

    # Create vault.conf file in ./tmp/ dir
    conf_file_path = os.path.join(
        constants.TMP_VAULT_DIR,
        constants.S3_VAULT_CONF)
    logging.debug(
        "Creating vault file for s3fuse at %s by the name %s",
        constants.TMP_VAULT_DIR,
        conf_file_path)

    conf_data = create_vault_conf(metadata_list, base_path, vendor)

    logging.debug("Fetched the conf data in dictionary: %s \n", str(conf_data))
    try:
        with open(conf_file_path, "w+") as fp:
            fp.write(constants.DEFAULT_CONF_SECTION + "\n")
    except IOError as e:
        logging.error(e.output)

    logging.info(
        'Writing the conf data to the conf file: %s\n',
        conf_file_path)
    append_create_dict_to_file(conf_data, conf_file_path)

    chmod_r(conf_file_path, 0o777)
    logging.debug(
        'Conf file created at %s with data:\n %s',
        conf_file_path,
        conf_data)
    object_store_mount_file = os.path.join(
        os.path.dirname(
            os.path.realpath(__file__)),
        constants.OBJECT_STORE_MOUNT_FILE)
    cmd = "{} {} &".format(constants.PYTHON_BINARY, object_store_mount_file)

    # save the output of the s3fuse process in a log file in case of VM mount.
    s3_mount_log = "/var/log/s3_mount.log"
    if constants.VM_MOUNT in os.environ:
        # 'nohup' prevents the process from being terminated when the SSH session closes.
        # This ensures that the script keeps running even after the SSH connection ends.

        # '&' runs the process in the background.
        # - This allows the Python script to continue running without blocking execution.

        # 'disown' detaches the process from the shell's job table.
        # - This ensures that the process is not linked to the current shell session,
        #   preventing it from being terminated if the SSH session is closed.
        cmd = f'nohup {constants.PYTHON_BINARY} {object_store_mount_file} >> {s3_mount_log} 2>&1 & disown'

    logging.info("command: {}".format(cmd))
    run_cmd(cmd, True)

    logging.debug('Running the fuse process for conf file: %s', conf_file_path)

    try:
        wait_until_mount(base_path)
    except Exception as e:
        # if VM mount is failed then log the output of the s3fuse process.
        if constants.VM_MOUNT in os.environ:
            logging.info("Mount operation failed for the s3fuse process. Log output:")
            with open(s3_mount_log, "r") as file:
                logging.error(file.read())

        raise Exception(e)

    # remove the conf files once process is done
    logging.info("Removing all the vault files from the ./tmp directory")
    rm_rf(constants.TMP_VAULT_DIR)


def wait_until_mount(base_path):
    timeout = time.time() + constants.CONVERT_TO_SECONDS * \
        constants.DEFAULT_WAIT_TIMEOUT
    while True:
        logging.info(
            "{}: Waiting for mount operation to complete.".format(
                datetime.datetime.now()))
        if os.path.ismount(base_path):
            logging.info(
                "{}: Target mounted successfully.".format(
                    datetime.datetime.now()))
            return True

        # poll every 2 sec's until timeout
        time.sleep(2)

        if time.time() > timeout:
            logging.error(
                "{}: timeout exceeded, not able to mount within time.".format(
                    datetime.datetime.now()))
            raise Exception(
                "{} is not a mountpoint. We can't proceed further.".format(base_path))


def retry(func, max_retries=3, timeout=5, *args, **kwargs):
    """
    Retry a function with fixed timeout between attempts.

    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts (default: 3)
        timeout: Fixed timeout in seconds between retries (default: 5)
        *args: Positional arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function

    Returns:
        The return value of the function if successful

    Raises:
        The last exception if all retries fail
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            retry_count += 1
            if retry_count == max_retries:
                raise
            logging.warning(f"Retry {retry_count}/{max_retries} to execute function. Error: {str(e)}")
            time.sleep(timeout)


def delete_path(fpath):
    if os.path.exists(fpath):
        if os.path.isfile(fpath):
            os.remove(fpath)
        elif os.path.isdir(fpath):
            shutil.rmtree(fpath)


def qemu_verification(test_directory, immutable_target):
    """
    Creates a QCOW2 image, formats it, creates a directory inside, and copies a file.
    """

    qcow2_path = f"/{test_directory}/disk.qcow2"

    try:
        cmd = "qemu-img create -f qcow2 " + qcow2_path + " 10M"
        # Step 1: Create a QCOW2 image
        run_cmd(cmd, True)

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Error occurred: {e}")
        # Always clean up the QCOW2 image on failure
        if os.path.exists(qcow2_path) and not immutable_target:
            os.remove("disk.qcow2")
            logging.info(f"🗑️  QCOW2 image '{qcow2_path}' has been deleted due to failure.")
        return

    # Cleanup on success if requested
    if not immutable_target:
        retry(func=delete_path, fpath=qcow2_path)
        logging.info(f"🗑️  QCOW2 image '{qcow2_path}' has been deleted after successful execution.")


def mount_nfs_datastore(metadata_list, base_path):
    """
    commands:
    rpc.statd & rpcbind -f &
    mount -t "${FSTYPE}" -o "${MOUNT_OPTIONS}" "${SERVER}":"${SHARE}" "${MOUNTPOINT}"
    :param metadata_list: dict -> dictionary of the metadata passed from the secret
    :param base_path: str -> base path, from where the datastore is to be mounted
    """
    logging.info(
        "mounting the NFS datastore by the name %s",
        metadata_list.get(
            constants.NAME))
    rpc_cmd = 'rpc.statd &'
    rpc_bind = 'rpcbind -f &'
    run_cmd(rpc_cmd, True)
    run_cmd(rpc_bind, True)

    logging.debug("Mounting the datastore at %s", base_path)

    if metadata_list.get(constants.SERVER) is None:
        cmd = 'mount -t {FS_TYPE} {nfsExport} {MOUNTPOINT} -v' \
            .format(FS_TYPE=constants.NFS,
                    nfsExport=metadata_list.get(constants.NFS_EXPORT),
                    MOUNTPOINT=base_path)

    else:
        cmd = 'mount -t {FS_TYPE} {SERVER}:{SHARE} {MOUNTPOINT} -v' \
            .format(FS_TYPE=constants.NFS,
                    SERVER=metadata_list.get(constants.SERVER),
                    SHARE=metadata_list.get(constants.SHARE),
                    MOUNTPOINT=base_path)

    if metadata_list.get(constants.MOUNT_OPTIONS) != "":
        cmd = cmd + " -o " + metadata_list.get(constants.MOUNT_OPTIONS)

    # If target is being mounted inside Virtual Machine, we need to run mount command with sudo.
    if constants.VM_MOUNT in os.environ:
        cmd = 'sudo ' + cmd
    run_cmd(cmd)
    wait_until_mount(base_path)


def mount_datastore(metadata_list, ds_type, base_path, vendor):
    """
    calls the specific function for a type of datastore passing its metadata
    :param ds_type: str -> type of datastore to be mounted (NFS/S3)
    :param metadata_list: dict -> dictionary of the metadata of a datastore passed from the secret
    :param base_path: str -> base path, from where the datastore is to be mounted
    :param vendor: str -> vendor of the datastore
    """
    if ds_type == constants.NFS or ds_type.lower() == constants.NFS:
        logging.info("Mounting datastore of type %s", constants.NFS)
        mount_nfs_datastore(metadata_list, base_path)
    elif ds_type == constants.S3 or ds_type.lower() == constants.OBJECT_STORE:
        try:
            logging.info("Mounting datastore of type %s", constants.OBJECT_STORE)
            mount_object_datastore(metadata_list, base_path, vendor)

        except Exception as msg:
            logging.info("Caught exception while mounting %s. Retrying.", msg)
            mount_object_datastore(metadata_list, base_path, vendor)
    else:
        raise ValueError("Invalid Datastore type")


def wait_until_unmount(mount_point):
    timeout = time.time() + constants.CONVERT_TO_SECONDS * \
        constants.DEFAULT_WAIT_TIMEOUT
    while True:
        logging.info(
            "{}: waiting for mount operation to complete.".format(
                datetime.datetime.now()))
        if not os.path.ismount(mount_point):
            logging.info(
                "{}: target unmounted successfully.".format(
                    datetime.datetime.now()))
            secret_file_path, secret_filename = get_secret_path_filename()
            if file_exists_in_dir(secret_file_path, secret_filename):
                rm_rf(os.path.join(secret_file_path, secret_filename))
            return True

        # poll every 2 sec's until timeout
        time.sleep(2)

        if time.time() > timeout:
            logging.error(
                "{}: timeout exceeded, not able to unmount within time.".format(
                    datetime.datetime.now()))
            raise Exception(
                "unable to un-mount the mount point {}.".format(mount_point))


def start_minio_gateway(minIOURL, minIOCertDir):
    try:
        # Construct command arguments
        minio_arguments = [
            "--anonymous",  # Hide sensitive information from logging
            "--json",      # Output logs in JSON format for better parsing
            "gateway",
            "azure",
            minIOURL,
            "--config-dir=" + constants.MinIOConfigPath,
            "--certs-dir=" + minIOCertDir
        ]

        # Initialize environment variables
        env = os.environ.copy()

        if os.getenv(constants.LogLevelEnv, "").upper() == constants.DEBUG_LOG_LEVEL:
            env[constants._MINIO_SERVER_DEBUG] = constants._MINIO_SERVER_DEBUG_ON

        # Start the process with stdout/stderr piped to see logs in pod logs
        process = subprocess.Popen(
            [constants.MinIOExecutable] + minio_arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout to capture all logs
            env=env
        )

        # Read and forward the output to our own stdout
        while True:
            output = process.stdout.readline()
            if output == b'' and process.poll() is not None:
                break
            if output:
                sys.stdout.buffer.write(output)
                sys.stdout.buffer.flush()

        return process.poll()
    except Exception as e:
        logging.error("Failed to start MinIO gateway: %s", str(e))
        raise


def wait_for_minio_gateway_to_be_ready(retry_count: int = 21) -> bool:
    scount = 0
    http_code = None
    for index in range(1, retry_count):
        logging.info('Waiting for MinIO gateway to come up')
        # Execute HTTP GET request
        try:
            response = requests.get(constants.MinIO_Gateway_URL)
            http_code = response.status_code
        except requests.exceptions.RequestException as e:
            logging.exception("error executing MinIO gateway ready command." + str(e))

        # Check HTTP status code
        if http_code != 200:
            time.sleep(constants.MinIOWait)
        else:
            logging.info('Waiting for MinIO gateway to get stable')
            time.sleep(constants.MinIOWait)
            scount += 1
            if scount > 2:
                logging.info('MinIO Gateway is up!')
                break

        # If it's the last iteration, exit loop
        if index == retry_count - 1:
            logging.exception("MinIO gateway is not up, wait operation timeout.")
            return False
        return True


def is_azure_target(vendor: str) -> bool:
    return vendor.lower() == constants.AZURE_VENDOR.lower()


def start_minio_getway_for_azure(metadata: dict):
    if metadata and "vendor" in metadata and is_azure_target(metadata["vendor"]):
        access_key_id, secret_key = metadata["accessKeyID"], metadata["accessKey"]

        os.environ[constants.MinIORootUserKey] = access_key_id
        os.environ[constants.MinIORootPasswdKey] = secret_key
        minIOCertDir = constants.MinIOConfigPath

        if constants.ProxyCABundle in os.environ:
            minIOCertDir = constants.ProxyCAMountPath

        minIOURL = ""
        if "s3EndpointUrl" in metadata and metadata["s3EndpointUrl"]:
            minIOURL = "{}/{}".format(metadata["s3EndpointUrl"], metadata["s3Bucket"])

        # Start the function in a separate thread
        thread = threading.Thread(target=start_minio_gateway, args=(minIOURL, minIOCertDir))
        thread.daemon = True
        thread.start()

        wait_for_minio_gateway_to_be_ready()


def validate_s3_permission(metadata_list: dict, ds_type: str):
    if ds_type == constants.S3 or ds_type.lower() == constants.OBJECT_STORE:
        logging.info("Verifying S3 permissions...")

        try:
            ssl_cert_path = getSSLPath()
            use_ssl = False
            endpoint_url = metadata_list[constants.S3_ENDPOINT_URL] if \
                metadata_list[constants.S3_ENDPOINT_URL] else None
            use_ssl = os.path.exists(ssl_cert_path)
            verify = ssl_cert_path if use_ssl else not metadata_list.get(constants.S3_SKIP_CERT_VERIFICATION)

            # set use_ssl to True if endpoint_url starts with https
            if endpoint_url and endpoint_url.startswith("https"):
                use_ssl = True

            client = boto3.client(
                's3',
                aws_access_key_id=metadata_list.get(constants.S3_ACCESS_KEY_ID),
                aws_secret_access_key=metadata_list.get(constants.S3_ACCESS_KEY),
                region_name=metadata_list.get(constants.S3_REGION_NAME),
                use_ssl=use_ssl,
                endpoint_url=endpoint_url,
                verify=verify
            )
            object_lock = metadata_list.get(constants.OBJECT_LOCKING_ENABLE)
            bucket_name = metadata_list.get(constants.S3_BUCKET)
            verify_s3_methods(client, bucket_name, object_lock)

        except botocore.exceptions.ClientError:
            logging.exception("AWS ClientError occurred during S3 validation")
            raise
        except botocore.exceptions.BotoCoreError:
            logging.exception("AWS BotoCoreError occurred during S3 validation")
            raise
        except Exception:
            logging.exception("Unexpected error while validating S3 permissions")
            raise


def verify_s3_methods(client: str, bucket_name: str, obj_lock=False):
    # List to collect all validation errors
    validation_errors = []

    def safe_execute(operation_name, func, *args, **kwargs):
        """Helper function to execute S3 operations safely."""
        try:
            logging.info(f"{operation_name} Check Started")
            func(*args, **kwargs)
            logging.info(f"{operation_name} Check Completed")
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError, Exception) as e:
            logging.error(f"Error during {operation_name} - {str(e)}")
            validation_errors.append({"operation": operation_name, "error": str(e), "exception": e})

    # Get object from s3 using versionId. If versioning
    # is disabled, it logs the info and exits
    # S3fuse uses versionId to delete objects. So this check is required
    def get_object_version(Bucket: str, Key: str):
        object_headers = client.head_object(Bucket=Bucket, Key=Key)
        try:
            versionId = object_headers['VersionId']
            client.get_object(Bucket=Bucket, Key=Key, VersionId=versionId)
        except KeyError:
            logging.info("Object versioning is not enabled. Ignoring object versioning check.")
            return None
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError):
            logging.exception("Unexpected error while getting object versioning")
            raise
        except Exception:
            logging.exception("Unexpected error while getting object versioning")
            raise

    # Delete object from s3 using versionId. If versioning
    # is disabled, it logs the info and exits
    # S3fuse uses versionId to delete objects. So this check is required
    def delete_object_version(Bucket: str, Key: str):
        object_headers = client.head_object(Bucket=Bucket, Key=Key)
        try:
            versionId = object_headers['VersionId']
            client.delete_object(Bucket=Bucket, Key=Key, VersionId=versionId)
        except KeyError:
            logging.info("Object versioning is not enabled. Ignoring object version deletion check.")
            return None
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError):
            logging.exception("Unexpected error while deleting object version")
            raise
        except Exception:
            logging.exception("Unexpected error while getting object versioning")
            raise

    operations = [
        ("head_bucket", client.head_bucket, {"Bucket": bucket_name}),
        ("list_objects", client.list_objects, {"Bucket": bucket_name}),
        ("put_object", client.put_object, {"Bucket": bucket_name, "Key": "test", "Body": "test"}),
        ("get_object", client.get_object, {"Bucket": bucket_name, "Key": "test"}),
        ("get_object_version", get_object_version, {"Bucket": bucket_name, "Key": "test"}),
        ("head_object", client.head_object, {"Bucket": bucket_name, "Key": "test"}),
        ("copy_object", client.copy_object, {"CopySource": {"Bucket": bucket_name, "Key": "test"},
                                             "Bucket": bucket_name, "Key": "test_copy"}),
        ("upload_file", client.upload_fileobj, {"Fileobj": BytesIO(b"Sample file content"),
                                                "Bucket": bucket_name, "Key": "uploaded_test"}),
        ("list_object_versions", client.list_object_versions, {"Bucket": bucket_name})
    ]
    delete_operations = [
        ("delete_object", client.delete_object, {"Bucket": bucket_name, "Key": "test"}),
        ("delete_object_version", delete_object_version, {"Bucket": bucket_name, "Key": "test_copy"}),
        ("delete_uploaded_file", client.delete_object, {"Bucket": bucket_name, "Key": "uploaded_test"}),
        ("delete_directory", client.delete_object, {"Bucket": bucket_name, "Key": "testdirectory/"})
    ]

    def get_paginator():
        paginator = client.get_paginator("list_objects")
        for _ in paginator.paginate(Bucket=bucket_name):
            pass

    operations.append(("get_paginator", get_paginator, {}))

    # Some S3 compatible storage does not directory type object
    # with body. So we need to handle that exception and create a
    # directory object with empty body
    # This function validates if directory creation is supported or not
    def create_directory(new_path: str):
        try:
            client.put_object(
                Bucket=bucket_name, Key=new_path,
                Body='TrilioVault directory object',
                ContentType='application/x-directory')

        except botocore.exceptions.ClientError as error:
            # Dell Powerscale does not allow
            # Adding a body to directory object.
            # So we need to handle that exception
            # and create a directory object with empty body
            if error.response['Error']['Code'] == 'InvalidRequest':
                try:
                    client.put_object(
                        Bucket=bucket_name, Key=new_path,
                        ContentType='application/x-directory')
                except Exception:
                    raise

    operations.append(("create_directory", create_directory, {"new_path": "testdirectory/"}))

    if not obj_lock:
        operations.extend(delete_operations)
    else:
        operations.append(("get_object_lock_configuration", client.get_object_lock_configuration,
                           {"Bucket": bucket_name}))

    for op_name, func, kwargs in operations:
        safe_execute(op_name, func, **kwargs)

    # Log each failed operation and raise exception if there are any errors
    if validation_errors:
        # Log each failed operation as a single structured log entry
        for error_info in validation_errors:
            # Extract meaningful error message
            if isinstance(error_info['exception'], botocore.exceptions.ClientError):
                error_code = error_info['exception'].response['Error']['Code']
                error_message = error_info['exception'].response['Error']['Message']
                logging.error(
                    f"Operation '{error_info['operation']}' failed - "
                    f"Error Code: {error_code}, Error Message: {error_message}"
                )
            else:
                logging.error(f"Operation '{error_info['operation']}' failed - Error: {error_info['error']}")

        # Raise an exception to indicate validation failure
        raise Exception("S3 permission validation failed")
