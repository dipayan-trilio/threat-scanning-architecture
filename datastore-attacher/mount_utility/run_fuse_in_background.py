#!/usr/bin/env python
import os
import s3fuse
from mount_utility import constants
from mount_utility import logger
logging = logger.logger


def mount():
    conf_file_path = os.path.join(
        constants.TMP_VAULT_DIR,
        constants.S3_VAULT_CONF)
    logging.debug(
        "running s3fuse mount using " +
        constants.S3_VAULT_CONF +
        "configuration file")
    s3fuse.mount(conf_file_path)


if __name__ == "__main__":
    try:
        mount()
    except Exception as ex:
        logging.exception(ex)
