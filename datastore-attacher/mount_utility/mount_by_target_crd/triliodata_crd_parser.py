import os
import logging as mainLogging

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from mount_utility import constants, kube_utilities, utilities
from mount_utility import logger

logging = logger.logger


def parse_cr_response(api_res_json):
    obj_dict = dict()
    if api_res_json["spec"]["type"].lower() == constants.NFS:
        obj_dict = {
            "id": api_res_json["metadata"]["uid"],
            "storageType": api_res_json["spec"]["type"],
            "name": api_res_json["metadata"]["name"],
            "metaData": {
                "mountOptions": api_res_json["spec"]["nfsCredentials"].get(
                    "nfsOptions", ""
                ),
                "nfsExport": api_res_json["spec"]["nfsCredentials"]["nfsExport"],
            },
        }
    elif api_res_json["spec"]["type"].lower() == constants.OBJECT_STORE:
        s3_endpoint_url = ""
        skip_cert_verification = (
            api_res_json["spec"]["objectStoreCredentials"]["skipCertVerification"]
            if "skipCertVerification" in api_res_json["spec"]["objectStoreCredentials"]
            else False
        )
        skip_certfile_creation_in_credential_secret = skip_cert_verification
        if "url" in api_res_json["spec"]["objectStoreCredentials"]:
            s3_endpoint_url = api_res_json["spec"]["objectStoreCredentials"]["url"]

        if (
            not
            skip_cert_verification and
            "sslCertConfig" in api_res_json["spec"]["objectStoreCredentials"]
        ):
            skip_certfile_creation_in_credential_secret = True
            configmap_name = api_res_json["spec"]["objectStoreCredentials"][
                "sslCertConfig"
            ]["certConfigMap"]["name"]
            configmap_namespace = api_res_json["spec"]["objectStoreCredentials"][
                "sslCertConfig"
            ]["certConfigMap"]["namespace"]
            cert_key = api_res_json["spec"]["objectStoreCredentials"]["sslCertConfig"][
                "certKey"
            ]
            kube_utilities.mount_target_ssl_cert_configmap(
                configmap_name=configmap_name,
                configmap_namespace=configmap_namespace,
                cert_key=cert_key,
            )
        if "credentialSecret" in api_res_json["spec"]["objectStoreCredentials"]:
            secret_name = api_res_json["spec"]["objectStoreCredentials"][
                "credentialSecret"
            ]["name"]
            secret_namespace = api_res_json["spec"]["objectStoreCredentials"][
                "credentialSecret"
            ]["namespace"]
            access_key_id, access_key = kube_utilities.get_target_secret_credentials(
                secret_name,
                secret_namespace,
                skip_certfile_creation_in_credential_secret,
            )
        else:
            access_key_id = api_res_json["spec"]["objectStoreCredentials"]["accessKey"]
            access_key = api_res_json["spec"]["objectStoreCredentials"]["secretKey"]

        obj_dict = {
            "id": api_res_json["metadata"]["uid"],
            "storageType": api_res_json["spec"]["type"],
            "name": api_res_json["metadata"]["name"],
            "namespace": api_res_json.get("metadata", {}).get("namespace", ""),
            "vendor": api_res_json["spec"]["vendor"],
            "metaData": {
                "accessKeyID": access_key_id,
                "accessKey": access_key,
                "s3Bucket": api_res_json["spec"]["objectStoreCredentials"][
                    "bucketName"
                ],
                "regionName": (
                    api_res_json["spec"]["objectStoreCredentials"]["region"]
                    if "region" in api_res_json["spec"]["objectStoreCredentials"]
                    else ""
                ),
                "storageNFSSupport": "TrilioVault",
                "storageDasDevice": "",
                "s3EndpointUrl": s3_endpoint_url,
                "objectLockingEnabled": (
                    api_res_json["spec"]["objectStoreCredentials"][
                        "objectLockingEnabled"
                    ]
                    if "objectLockingEnabled"
                    in api_res_json["spec"]["objectStoreCredentials"]
                    else False
                ),
                "skipCertVerification": (
                    api_res_json["spec"]["objectStoreCredentials"][
                        "skipCertVerification"
                    ]
                    if "skipCertVerification"
                    in api_res_json["spec"]["objectStoreCredentials"]
                    else False
                ),
                "hasDefaultRetentionPeriod": (
                    api_res_json["spec"]["objectStoreCredentials"][
                        "objectLockingEnabled"
                    ]
                    if "objectLockingEnabled"
                    in api_res_json["spec"]["objectStoreCredentials"]
                    else False
                ),
            },
        }
        if obj_dict["metaData"]["objectLockingEnabled"] and "status" in api_res_json \
            and "defaultRetentionPeriod" in api_res_json["status"] \
                and api_res_json["status"]["defaultRetentionPeriod"] == 0:
            obj_dict["metaData"]["hasDefaultRetentionPeriod"] = False
    return obj_dict


def get_ds_from_target_crds(
        target_crd_name,
        target_crd_namespace,
        target_cred_hash,
        group,
        version):
    api_response = ""

    try:
        if constants.VM_MOUNT in os.environ:
            config.load_kube_config()
        else:
            config.load_incluster_config()
        client.rest.logger.setLevel(mainLogging.INFO)
        api_instance = client.CustomObjectsApi()
    except ApiException as e:
        logging.error("Error while creating kubernetes client :", e.reason)
        raise e
    except BaseException as e:
        logging.error(e)

    if target_crd_name:
        try:
            logging.info("using target name to fetch the target resource")
            logging.info("fetching target-cr for group: " + group)

            # Wrap API call with retry mechanism
            if not target_crd_namespace:
                api_response = utilities.retry(
                    api_instance.get_cluster_custom_object,
                    max_retries=5,
                    timeout=2,
                    group=group,
                    version=version,
                    plural=constants.TARGET_CRD_PLURAL,
                    name=target_crd_name
                )
            else:
                api_response = utilities.retry(
                    api_instance.get_namespaced_custom_object,
                    max_retries=5,
                    timeout=2,
                    group=group,
                    version=version,
                    namespace=target_crd_namespace,
                    plural=constants.TARGET_CRD_PLURAL,
                    name=target_crd_name
                )
        except ApiException as e:
            logging.error("Error while getting Target :" + e.reason)
            raise e
        except BaseException as e:
            logging.error(e)
    elif target_cred_hash:
        try:
            logging.info("using credential hash to fetch the target resource")
            logging.info("fetching target-cr for group: " + group)

            # Wrap API call with retry mechanism
            targets = utilities.retry(
                api_instance.list_cluster_custom_object,
                max_retries=5,
                timeout=2,
                group=group,
                version=version,
                plural=constants.TARGET_CRD_PLURAL
            )

            if len(targets["items"]) == 0:
                raise Exception("Target is not present in any of the namespace")
            for tg in targets["items"]:
                logging.info(
                    "Checking target %s namespace %s for credential hash %s"
                    % (
                        tg["metadata"]["name"],
                        tg["metadata"]["namespace"],
                        target_cred_hash,
                    )
                )
                if (
                    "annotations" in tg["metadata"] and
                    constants.CREDENTIAL_HASH_ANNOTATION in
                    tg["metadata"]["annotations"]
                ):
                    if (
                        tg["metadata"]["annotations"][
                            constants.CREDENTIAL_HASH_ANNOTATION
                        ] == target_cred_hash
                    ):
                        logging.info(
                            "Found target matching with credential hash " + target_cred_hash
                        )
                        api_response = tg
                        break
            if not api_response:
                raise Exception(
                    "No target found with credential hash " + target_cred_hash
                )
        except ApiException as e:
            logging.error("Error while getting Target :" + e.reason)
            raise e
        except BaseException as e:
            raise e

    return api_response


def parse_datastore(api_res_json):
    """
    fetched the list of all the datastores from the secret yaml and
    returns the list of nfs and s3 datastores by the names specified and
    if no flag is specified, returns the default datastore defined by admin
    :param version: str -> The custom resource's version
    :param group: str -> The custom resource's group
    :param crd_namespace: str -> The custom resource's namespace
    :param crd_name: str -> The custom resource's name
    :return: list[dict] -> datastores_list according to the filters
    """
    logging.debug("Parsing the target-cr to get the list of datastores")
    datastore = None

    if api_res_json:
        datastore = parse_cr_response(api_res_json)

    if not type(datastore).__name__ == "dict":
        logging.error("No datastore found in the target-cr. Exiting now...")
        return None
    return datastore
