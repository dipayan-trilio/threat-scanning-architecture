import os
import base64
import threading

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from mount_utility import utilities
from mount_utility import constants
from mount_utility import logger
import logging as mainLogging

logging = logger.logger


def get_target_secret_credentials(
    secret_name: str, secret_namespace: str, skip_certfile_creation: bool = False
):
    """
    Retrieves Object Store credentials from a Kubernetes
     secret and optionally creates SSL certificate file.

    Args:
        secret_name: Name of the Kubernetes secret
        secret_namespace: Namespace of the Kubernetes secret
        skip_certfile_creation: If True, skips creating certificate file

    Returns:
        tuple: (access_key, secret_key)
    """
    access_key = ""
    secret_key = ""

    if not secret_name:
        return "", ""

    try:
        # Load appropriate Kubernetes config
        if constants.VM_MOUNT in os.environ:
            config.load_kube_config()
        else:
            config.load_incluster_config()

        client.rest.logger.setLevel(mainLogging.INFO)
        v1 = client.CoreV1Api()

        # Get secret data with retry mechanism
        secret = utilities.retry(
            v1.read_namespaced_secret,
            max_retries=5,
            timeout=2,
            name=secret_name,
            namespace=secret_namespace
        )

        # Extract credentials
        access_key = (
            base64.b64decode(secret.data.get(constants.S3_ACCESS_KEY, b""))
            .decode("utf-8")
            .strip()
        )
        secret_key = (
            base64.b64decode(secret.data.get(constants.S3_SECRET_KEY, b""))
            .decode("utf-8")
            .strip()
        )

        # Log warnings for missing credentials
        if not access_key:
            logging.info(
                "Unable to get access key\
                 for ObjectStore from secret"
            )
        if not secret_key:
            logging.info(
                "Unable to get secret key\
                 for ObjectStore from secret"
            )

        # Handle certificate if needed
        if not skip_certfile_creation and constants.SSL_CERT_FILE_NAME in secret.data:
            with open(utilities.getSSLPath(), "w") as file:
                certificate = base64.b64decode(
                    secret.data[constants.SSL_CERT_FILE_NAME]
                ).decode("utf-8")
                if certificate:
                    file.write(certificate)
                    logging.info("Certificate file created")
                else:
                    logging.info(
                        "Unable to get certificate for ObjectStore from secret"
                    )

    except ApiException as e:
        logging.error(f"Error while getting Secret: {e.reason}")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
    return access_key, secret_key


def mount_target_ssl_cert_configmap(
    configmap_name: str, configmap_namespace: str, cert_key: str
) -> None:
    """
    Retrieves SSL certificate from a Kubernetes ConfigMap and creates the
    certificate file.

    Args:
        configmap_name: Name of the Kubernetes ConfigMap
        configmap_namespace: Namespace of the Kubernetes ConfigMap
        cert_key: Key in the ConfigMap containing the certificate data

    """
    if not configmap_namespace:
        logging.info(
            "Target SSL certificate configmap_namespace is empty, "
            "setting configmap_namespace to default"
        )
        configmap_namespace = "default"

    if not configmap_name:
        logging.error("Target SSL certificate configmap_name is empty")
        raise ValueError("ConfigMap name cannot be empty")

    if not cert_key:
        logging.error("Target SSL certificate cert_key is empty")
        raise ValueError("Certificate key cannot be empty")

    try:
        # Load appropriate Kubernetes config
        if constants.VM_MOUNT in os.environ:
            config.load_kube_config()
        else:
            config.load_incluster_config()

        client.rest.logger.setLevel(mainLogging.INFO)
        v1 = client.CoreV1Api()

        # Get ConfigMap data with retry mechanism
        config_map = utilities.retry(
            v1.read_namespaced_config_map,
            max_retries=5,
            timeout=2,
            name=configmap_name,
            namespace=configmap_namespace
        )

        # Check if certificate data exists
        if cert_key not in config_map.data:
            logging.error(
                f"SSL certificate not found for key {cert_key} "
                f"in ConfigMap {configmap_name}"
            )
            raise KeyError(
                f"Certificate key '{cert_key}'\
                 not found in ConfigMap"
            )

        certificate = config_map.data[cert_key]
        if not certificate:
            logging.error(f"SSL certificate for key {cert_key} in ConfigMap is empty")
            raise ValueError(f"Certificate data for key '{cert_key}' is empty")

        # Write certificate to file
        ssl_path = utilities.getSSLPath()
        with open(ssl_path, "w") as file:
            file.write(certificate)
        logging.info(
            f"Certificate file created at {ssl_path} "
            f"from ConfigMap using key {cert_key}"
        )

    except ApiException as e:
        logging.error(f"Error while getting ConfigMap: {e.reason}")
        raise
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise


def start_minio_gateway_if_azure_target(target: dict):
    if (
        target and
        "vendor" in target["spec"] and
        utilities.is_azure_target(target["spec"]["vendor"])
    ):
        logging.info("target vendor is Azure so starting MinIO gateway.")
        skip_cert_verification = (
            target["spec"]["objectStoreCredentials"]["skipCertVerification"]
            if "skipCertVerification" in target["spec"]["objectStoreCredentials"]
            else False
        )
        skip_certfile_creation_in_credential_secret = skip_cert_verification
        if (
            not
            skip_cert_verification and
            "sslCertConfig" in target["spec"]["objectStoreCredentials"]
        ):
            skip_certfile_creation_in_credential_secret = True
            configmap_name = target["spec"]["objectStoreCredentials"]["sslCertConfig"][
                "certConfigMap"
            ]["name"]
            configmap_namespace = target["spec"]["objectStoreCredentials"][
                "sslCertConfig"
            ]["certConfigMap"]["namespace"]
            cert_key = target["spec"]["objectStoreCredentials"]["sslCertConfig"][
                "certKey"
            ]
            mount_target_ssl_cert_configmap(
                configmap_name=configmap_name,
                configmap_namespace=configmap_namespace,
                cert_key=cert_key,
            )

        secret_name = target["spec"]["objectStoreCredentials"]["credentialSecret"][
            "name"
        ]
        secret_namespace = target["spec"]["objectStoreCredentials"]["credentialSecret"][
            "namespace"
        ]

        access_key_id, secret_key = get_target_secret_credentials(
            secret_name=secret_name,
            secret_namespace=secret_namespace,
            skip_certfile_creation=skip_certfile_creation_in_credential_secret,
        )

        os.environ[constants.MinIORootUserKey] = access_key_id
        os.environ[constants.MinIORootPasswdKey] = secret_key
        minIOCertDir = constants.MinIOConfigPath

        if constants.ProxyCABundle in os.environ:
            minIOCertDir = constants.ProxyCAMountPath

        minIOURL = ""
        if "url" in target["spec"]["objectStoreCredentials"]:
            minIOURL = "{}/{}".format(
                target["spec"]["objectStoreCredentials"]["url"],
                target["spec"]["objectStoreCredentials"]["bucketName"],
            )

        # Start the function in a separate thread
        thread = threading.Thread(
            target=utilities.start_minio_gateway, args=(minIOURL, minIOCertDir)
        )
        thread.daemon = True
        thread.start()

        utilities.wait_for_minio_gateway_to_be_ready()
