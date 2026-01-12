import argparse
import os
import sys

from mount_utility import constants
from mount_utility import utilities
from mount_utility import logger
logging = logger.logger


def init():
    try:
        parser = argparse.ArgumentParser("Unmount the Datastore. Available Flags --mountpoint. \
            If any flag not passed, default datastore will be unmounted")

        parser.add_argument('--mountpoint', dest="mountpoint", nargs='?', default=constants.DEFAULT_DATASTORE_BASE_PATH,
                            help="The path of a single datastore which has to be unmounted")

        args = parser.parse_args()

        if not os.path.exists(args.mountpoint):
            logging.error("Mount point does not exist")

        if not os.path.ismount(args.mountpoint):
            raise Exception("Path {} is not Mounted.".format(args.mountpoint))

        return args.mountpoint

    except BaseException as ex:
        logging.exception(ex)
        sys.exit(1)


def main(mount_point):
    logging.debug("Unmounting the datastore at %s", mount_point)
    cmd = 'umount -f -l {MOUNTPOINT}'.format(MOUNTPOINT=mount_point)

    utilities.run_cmd(cmd)
    utilities.wait_until_unmount(mount_point)


if __name__ == '__main__':
    ds_base_path = init()
    main(ds_base_path)
