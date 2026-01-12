import argparse
import errno
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from mount_utility import constants
from mount_utility import utilities

import triliodata_secret_parser

logging.basicConfig(level=logging.INFO)


def init():
    try:
        parser = argparse.ArgumentParser("Mounts the Datastores. Available flags: --target-name, --all-targets. \
            If any flag not passed, default datastore will be mounted")
        parser.add_argument('--target-name', dest="target_name", nargs='?',
                            help="The name of a single datastore who has to be mounted")
        parser.add_argument('--all-targets', dest="all_targets", action='store_true',
                            help="flag to mount all the datastores present in the secret")
        parser.add_argument('--mountpoint', dest="mountpoint", help="mountpoint to mount the specified target. \
                            default mountpoint will be /triliodata")
        parser.add_argument('--vendor', dest="vendor", help="Name of the vendor for the datastore \
                            to be mounted")

        args = parser.parse_args()
        default_ds = False
        ds_name = ""

        vendor = args.vendor
        single_ds = args.target_name
        all_ds = args.all_targets

        logging.info("Passed option for datastores: --target-name %s , --all-targets %s", single_ds,
                     all_ds)
        if all_ds and single_ds:
            parser.error("Only one flag is allowed, either --target-name <datastore-name> OR --all-targets")

        if not all_ds and not single_ds:
            # if no arg is specified, get default datastore
            logging.info("no option specified, marking it to get the default datastore")
            default_ds = True

        if not all_ds and single_ds:
            ds_name = single_ds

        # ds_base_path will be used as a mountpoint for nfs, s3 datastores.
        # created "triliodata" directory via dockerfile as only
        # single datastore will be mounted at a time.
        # It will resolved the problem of backing-chain for migration from nfs to s3 & vice-versa.
        mountpoint = args.mountpoint if args.mountpoint else constants.DEFAULT_DATASTORE_BASE_PATH

        if not os.path.exists(mountpoint):
            try:
                os.makedirs(mountpoint)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

        return default_ds, all_ds, mountpoint, ds_name, vendor

    except Exception as ex:
        logging.exception(ex)
        sys.exit(1)


def main(default_ds, all_ds, base_path, ds_name, vendor):
    """Create a new folder
    :param default_ds: bool -> flag to use the default datastore
    :param all_ds: bool -> flag to mount all the datastores present in the secret
    :param base_path: str -> complete path of the folder to be created
    :param ds_name: str -> The name of a single datastore who has to be mounted
    """
    try:
        logging.info("calling the parser the secret to get the datastore")
        # list of all the datastores according to the criteria like datastore
        # type, names
        datastores = triliodata_secret_parser.parse_datastore(all_ds, ds_name, default_ds)
        logging.info("Fetched the list of datastores to be mounted")

        if not datastores:
            logging.error("ERROR: no datastores found according to the details passed")
            sys.exit(1)

        with ThreadPoolExecutor(max_workers=len(datastores)) as executor:
            future_list = list()
            for ds in datastores:
                logging.info("Mounting each datastore one by one")
                # metadata will be having a list of all the key-value pairs of
                # configuration for specific datastore
                metadata = ds.get(constants.METADATA)
                metadata[constants.NAME] = ds.get(constants.NAME)
                if not vendor and ds.get(constants.DATASTORE_TYPE).lower() == constants.NFS:
                    vendor = constants.OTHER_VENDOR
                if not vendor and ds.get(constants.DATASTORE_TYPE).lower() == constants.S3:
                    vendor = constants.AWS_VENDOR
                future_list.append(executor.submit(utilities.mount_datastore, metadata,
                                                   ds.get(constants.DATASTORE_TYPE),
                                                   base_path, vendor))
            for future in future_list:
                logging.info('Mount thread completed. Final Result: {}'.format(future.result()))
        return True
    except Exception as ex:
        logging.exception(ex)
        sys.exit(1)


if __name__ == '__main__':
    default_datastore, all_datastores, ds_base_path, datastore_name, vendor = init()
    main(default_datastore, all_datastores, ds_base_path, datastore_name, vendor)
