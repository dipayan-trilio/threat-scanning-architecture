import argparse
import sys
from kubernetes.client.rest import ApiException

from mount_utility import constants
from mount_utility import utilities
from mount_utility.mount_by_target_crd import triliodata_crd_parser
from mount_utility import logger

logging = logger.logger


def init():
    try:
        parser = argparse.ArgumentParser("Mounts the Datastores. \
            Available flags: --target-name, --target-namespace.")
        group = parser.add_mutually_exclusive_group(required=True)
        parser.add_argument('--group', dest="group", default=constants.TVK_CRD_GROUP,
                            help="The group name of target crd to read datastores")
        parser.add_argument('--version', dest="version", default=constants.TVK_CRD_VERSION,
                            help="The version of target crd group to read datastores")
        group.add_argument('--target-name', dest="target_name", required=False,
                           help="The name of target crd to read datastores")
        group.add_argument('--target-credential-hash', dest="cred_hash", required=False,
                           help="Credential hash which is present on the target as annotation")
        parser.add_argument('--service-type', dest="service_type", default=constants.DatastoreAttacherService,
                            help="The serviceType using this data-attacher")

        args = parser.parse_args()
        cr_group = args.group
        cr_version = args.version
        target_cr_name = args.target_name
        target_cr_namespace = None  # Always None - targets are cluster-scoped
        target_cred_hash = args.cred_hash

        logger.targetGroup = cr_group
        logger.service_type = args.service_type
        if target_cr_name:
            logger.transaction_resource_name = target_cr_name
            logger.transaction_resource_namespace = target_cr_namespace if target_cr_namespace else ""
        elif target_cred_hash:
            logger.transaction_resource_name = target_cred_hash
            logger.transaction_resource_namespace = ""
        logger.SetLoggerIdentifier()
        # ds_base_path will be used as a mountpoint for nfs, s3 datastores.
        # created "triliodata" directory via dockerfile as only
        # single datastore will be mounted at a time.
        # It will resolved the problem of backing-chain for migration from nfs to s3 & vice-versa.
        # TODO return map instead of multiple values
        return constants.DEFAULT_DATASTORE_BASE_PATH, target_cr_name, target_cr_namespace, target_cred_hash, \
            cr_group, cr_version

    except Exception as ex:
        logging.exception(ex)
        sys.exit(1)


def main(base_path, name, namespace, cred_hash, cr_group, cr_version):
    try:
        logging.info("Fetching target cr to get the datastore")
        target_json = triliodata_crd_parser.get_ds_from_target_crds(
            name, namespace, cred_hash, cr_group, cr_version)

        # list of all the datastores according to the criteria like datastore
        #  type, names
        datastore = triliodata_crd_parser.parse_datastore(target_json)

        logging.info("Fetched the list of datastores to be mounted")
        if not datastore:
            logging.error("ERROR: no datastores found according to \
                      the details passed")
            sys.exit(1)

        logger.transactionID = datastore.get("id", "")
        logger.SetLoggerIdentifier()

        metadata = datastore.get(constants.METADATA)
        metadata[constants.NAME] = datastore.get(constants.NAME)
        utilities.mount_datastore(metadata, datastore.get(constants.DATASTORE_TYPE), base_path,
                                  datastore.get('vendor', constants.OTHER_VENDOR))
        return True
    except ApiException as ex:
        logging.exception("Exception when calling CustomObjectsApi->\
            get_namespaced_custom_object: %s\n" % ex)
    except Exception as ex:
        logging.exception(ex)
        sys.exit(1)


if __name__ == '__main__':
    ds_base_path, crd_name, crd_namespace, crd_cred_hash, group, version = init()
    main(ds_base_path, crd_name, crd_namespace, crd_cred_hash, group, version)
