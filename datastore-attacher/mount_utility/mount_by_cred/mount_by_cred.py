import argparse
import sys

from mount_utility import constants
from mount_utility import utilities
from mount_utility import logger

logging = logger.logger


def parse_arguments():
    logging.info("Parsing arguments")

    parser = argparse.ArgumentParser(
        description="Mounts the Datastores based on the provided storage type.",
        epilog="""
    Examples:

      1. Mount NFS storage with exports:
         python mount_by_cred.py nfs --nfs-exports /mnt/nfs_share --nfs-options nfsvers=4

      2. Mount Object Store with access key:
         python script.py objectstore --access-key-id <access-key-id>
            --access-key <access-key> --s3-bucket <bucket-name>

      3. Mount Object Store to specific location
         python mount_by_cred.py nfs --nfs-exports /mnt/nfs_share
            --nfs-options nfsvers=4 --datastore-base-path /mountpath
         python script.py objectstore --access-key-id <access-key-id>
            --access-key <access-key> --s3-bucket <bucket-name> --datastore-base-path /mountpath
    """,
        formatter_class=argparse.RawTextHelpFormatter  # Preserve text formatting
    )
    subparsers = parser.add_subparsers(dest='storage_type', help='Storage type to mount')

    nfs_parser = subparsers.add_parser('nfs', help="Mount NFS storage")
    nfs_parser.add_argument('--nfs-options', dest='mount_options', default='', help='NFS mount options')
    nfs_parser.add_argument('--nfs-exports', dest='nfs_exports', required=True, help='NFS exports')
    nfs_parser.add_argument('--datastore-base-path',
                            default=constants.DEFAULT_DATASTORE_BASE_PATH, help='Base path for datastore.')

    object_store_parser = subparsers.add_parser('objectstore', help="Mount Object Store")
    object_store_parser.add_argument('--access-key-id', required=True, help="Access key ID for object store.")
    object_store_parser.add_argument('--access-key', required=True, help="Access key for object store.")
    object_store_parser.add_argument('--bucket', required=True, help="bucket name.")
    object_store_parser.add_argument('--region-name', required=False, help="Region name for object store.")
    object_store_parser.add_argument('--endpoint-url', required=False, help="endpoint URL.")
    object_store_parser.add_argument('--object-locking-enabled', required=False, action='store_true',
                                     help="Enable object locking.")
    object_store_parser.add_argument('--skip-cert-verification', required=False, action='store_true',
                                     help="Skip certificate verification.")
    object_store_parser.add_argument('--vendor', required=False, help="Vendor name.")
    object_store_parser.add_argument('--datastore-base-path',
                                     default=constants.DEFAULT_DATASTORE_BASE_PATH, help='Base path for datastore.')

    args = parser.parse_args()

    if not args.storage_type:
        logging.error("Storage type not provided.")
        sys.exit(1)

    logging.info("Arguments parsed successfully")
    return args


def convert_to_dict(args):
    logging.info("Converting arguments to dictionary")

    obj_dict = {}
    if args.storage_type.lower() == constants.NFS:
        obj_dict = {
            constants.DATASTORE_TYPE: args.storage_type,
            constants.METADATA: {
                constants.MOUNT_OPTIONS: args.mount_options,
                constants.NFS_EXPORT: args.nfs_exports
            }
        }
    elif args.storage_type.lower() == constants.OBJECT_STORE:
        obj_dict = {
            constants.DATASTORE_TYPE: args.storage_type,
            constants.METADATA: {
                constants.S3_ACCESS_KEY_ID: args.access_key_id,
                constants.S3_ACCESS_KEY: args.access_key,
                constants.S3_BUCKET: args.bucket,
                constants.S3_STORAGE_NFS_SUPPORT: "TrilioVault",
                constants.S3_STORAGE_DAS_DEVICE: "",
                constants.S3_REGION_NAME: args.region_name if args.region_name else "",
                constants.S3_ENDPOINT_URL: args.endpoint_url if args.endpoint_url else "",
                constants.OBJECT_LOCKING_ENABLE: args.object_locking_enabled if args.object_locking_enabled else False,
                constants.S3_SKIP_CERT_VERIFICATION:
                    args.skip_cert_verification if args.skip_cert_verification else False,
                constants.VENDOR: args.vendor if args.vendor else "",
            }
        }
    return obj_dict


def main(data):
    datastore = convert_to_dict(data)

    try:
        logging.info(f"Mounting datastore: {datastore}")
        metadata = datastore.get(constants.METADATA)

        metadata[constants.NAME] = datastore.get(constants.NAME)

        utilities.mount_datastore(metadata, datastore.get(constants.DATASTORE_TYPE), data.datastore_base_path,
                                  metadata.get(constants.VENDOR, constants.OTHER_VENDOR))
        logging.info("Datastore mounted successfully.")
        return True

    except Exception as ex:
        error_msg = (
            f"Failed to mount datastore.\n"
            f"  Datastore: {datastore}\n"
            f"  Error: {str(ex)}"
        )
        logging.error(error_msg)
        sys.exit(1)


if __name__ == '__main__':
    args = parse_arguments()
    main(args)
