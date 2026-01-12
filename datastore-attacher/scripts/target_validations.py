#!/usr/bin/env python
import os
import sys
import argparse
import logging as mainLogging
from mount_utility import constants
from mount_utility import utilities
from mount_utility.mount_by_target_crd import triliodata_crd_parser
from mount_utility import logger

logging = logger.logger


class TargetValidation:

    def __init__(self):
        try:
            parser = argparse.ArgumentParser(
                description="Target validation for threat-scanning-architecture. "
                            "Validates backup targets (read-only) or reporting targets (write-enabled)."
            )
            parser.add_argument('--group', dest="group", default=constants.TVK_CRD_GROUP,
                                help="The group of target crd to read datastores")
            parser.add_argument('--version', dest="version", default=constants.TVK_CRD_VERSION,
                                help="The version of target crd to read datastores")
            parser.add_argument('--target-name', dest="target_name", required=True,
                                help="The name of target crd to read datastores")
            parser.add_argument('--type', dest="target_type", required=True,
                                choices=[constants.TARGET_TYPE_BACKUP, constants.TARGET_TYPE_REPORTING],
                                help="Target type: 'backup' (read-only validation) or 'reporting' (write validation)")
            parser.add_argument('--service-type', dest="service_type", default=constants.ValidationService,
                                help="The serviceType using this target-validator")
            args = parser.parse_args()
            
            self.group = args.group
            self.version = args.version
            self.target_cr_name = args.target_name
            self.target_cr_namespace = None  # Always None - targets are cluster-scoped
            self.target_type = args.target_type
            self.service_type = args.service_type
        except Exception as ex:
            logging.exception(ex)
            sys.exit(1)

        self.datastore_path = constants.DEFAULT_DATASTORE_BASE_PATH
        logger.service_type = self.service_type
        # this for `service_type` logger field in `triliodata_crd_parser` package
        triliodata_crd_parser.logging = logging
        logger.SetLoggerIdentifier()
        logging.info(f"Target validation in progress for type: {self.target_type}")

        target_json = triliodata_crd_parser.get_ds_from_target_crds(
            self.target_cr_name, self.target_cr_namespace, "",
            self.group, self.version
        )

        self.target = triliodata_crd_parser.parse_datastore(target_json)
        self.vendor = target_json["spec"]["vendor"]
        logger.targetGroup = self.group
        logger.transactionID = self.target.get("id", "")
        logger.transaction_resource_name = self.target_cr_name
        logger.transaction_resource_namespace = ""  # Empty string for cluster-scoped targets
        logger.SetLoggerIdentifier()

    def validate_backup_target(self):
        """
        Validates backup target with READ-ONLY operations.
        For backup targets, we only need to verify that we can:
        1. Mount the target (if ObjectStore via s3fuse, NFS via native mount)
        2. List files/objects
        3. Read file metadata (stat)
        4. Read file content (first few bytes)
        """
        logging.info("Validating backup target (read-only)")

        # Verify mount succeeded
        if not os.path.ismount(self.datastore_path):
            raise Exception(f"❌ {self.datastore_path} is not mounted. Backup target validation failed.")

        logging.info(f"✅ Verified {self.datastore_path} is mounted")

        # List files in bucket/share root
        try:
            files = os.listdir(self.datastore_path)
            logging.info(f"✅ Successfully listed {len(files)} objects in target")
        except Exception as e:
            raise Exception(f"❌ Failed to list objects in {self.datastore_path}: {e}")

        # If files exist, try reading metadata and content
        if files:
            # Find a regular file (not directory)
            test_file = None
            for item in files:
                full_path = os.path.join(self.datastore_path, item)
                if os.path.isfile(full_path):
                    test_file = full_path
                    break

            if test_file:
                # Test 1: Read file metadata (stat)
                try:
                    stat_info = os.stat(test_file)
                    logging.info(f"✅ Successfully read file metadata: {os.path.basename(test_file)} "
                                 f"(size={stat_info.st_size} bytes, mode={oct(stat_info.st_mode)})")
                except Exception as e:
                    raise Exception(f"❌ Failed to read file metadata for {test_file}: {e}")

                # Test 2: Read first 1KB of file content
                try:
                    with open(test_file, 'rb') as f:
                        first_bytes = f.read(1024)
                    logging.info(f"✅ Successfully read {len(first_bytes)} bytes from file {os.path.basename(test_file)}")
                except Exception as e:
                    raise Exception(f"❌ Failed to read file content from {test_file}: {e}")
            else:
                logging.info("ℹ️  No regular files found in target root, only directories. "
                             "Skipping file read test (list operation passed).")
        else:
            logging.info("ℹ️  Target is empty (no files or directories). "
                         "Validation passed (mount and list operations successful).")

        logging.info("✅ Backup target validation completed successfully")

    def validate_reporting_target(self):
        """
        Validates reporting target with WRITE operations using direct S3 API.
        For reporting targets, we use boto3 APIs to:
        1. Verify bucket access
        2. Create test object
        3. Read test object
        4. Delete test object
        
        This reuses the validate_s3_permission function from utilities.
        """
        logging.info("Validating reporting target (write-enabled using S3 API)")

        if self.target["storageType"].lower() != constants.OBJECT_STORE:
            raise Exception(f"❌ Reporting targets must be ObjectStore type, got: {self.target['storageType']}")

        # Use the existing validate_s3_permission function which tests:
        # - head_bucket, list_objects, put_object, get_object, delete_object, etc.
        try:
            utilities.validate_s3_permission(
                self.target[constants.METADATA],
                self.target.get(constants.DATASTORE_TYPE)
            )
        except Exception as e:
            raise Exception(f"❌ Reporting target validation failed: {e}")

        logging.info("✅ Reporting target validation completed successfully")

    def validate_nfs_backup_target(self):
        """
        Validates NFS backup target with READ-ONLY operations.
        Similar to ObjectStore backup validation but for NFS mounts.
        """
        logging.info("Validating NFS backup target (read-only)")

        # Verify NFS mount succeeded
        if not os.path.ismount(self.datastore_path):
            raise Exception(f"❌ {self.datastore_path} is not mounted. NFS backup target validation failed.")

        logging.info(f"✅ Verified NFS mount at {self.datastore_path}")

        # List files in NFS share
        try:
            files = os.listdir(self.datastore_path)
            logging.info(f"✅ Successfully listed {len(files)} items in NFS share")
        except Exception as e:
            raise Exception(f"❌ Failed to list items in NFS share {self.datastore_path}: {e}")

        # If files exist, try reading metadata and content
        if files:
            test_file = None
            for item in files:
                full_path = os.path.join(self.datastore_path, item)
                if os.path.isfile(full_path):
                    test_file = full_path
                    break

            if test_file:
                # Test 1: Read file metadata
                try:
                    stat_info = os.stat(test_file)
                    logging.info(f"✅ Successfully read NFS file metadata: {os.path.basename(test_file)} "
                                 f"(size={stat_info.st_size} bytes)")
                except Exception as e:
                    raise Exception(f"❌ Failed to read NFS file metadata for {test_file}: {e}")

                # Test 2: Read first 1KB
                try:
                    with open(test_file, 'rb') as f:
                        first_bytes = f.read(1024)
                    logging.info(f"✅ Successfully read {len(first_bytes)} bytes from NFS file")
                except Exception as e:
                    raise Exception(f"❌ Failed to read NFS file content from {test_file}: {e}")
            else:
                logging.info("ℹ️  No regular files found in NFS share root. "
                             "Validation passed (mount and list operations successful).")
        else:
            logging.info("ℹ️  NFS share is empty. "
                         "Validation passed (mount and list operations successful).")

        logging.info("✅ NFS backup target validation completed successfully")

    def validate(self):
        """
        Main validation entry point.
        Routes to appropriate validation method based on target type and storage type.
        """
        try:
            storage_type = self.target["storageType"].lower()
            logging.info(f"Target storage type: {storage_type}")
            logging.info(f"Target validation type: {self.target_type}")

            if self.target_type == constants.TARGET_TYPE_BACKUP:
                # Backup targets: read-only validation
                if storage_type == constants.NFS:
                    self.validate_nfs_backup_target()
                elif storage_type == constants.OBJECT_STORE:
                    self.validate_backup_target()
                else:
                    raise Exception(f"❌ Unsupported storage type for backup target: {storage_type}")

            elif self.target_type == constants.TARGET_TYPE_REPORTING:
                # Reporting targets: write validation (only ObjectStore supported)
                if storage_type != constants.OBJECT_STORE:
                    raise Exception(f"❌ Reporting targets must be ObjectStore type, got: {storage_type}")
                self.validate_reporting_target()

            else:
                raise Exception(f"❌ Unknown target type: {self.target_type}")

        except Exception as e:
            logging.exception(e)
            raise Exception(e)


if __name__ == "__main__":
    v = TargetValidation()
    v.validate()
    logging.info("=" * 80)
    logging.info(f"🎉 Target '{v.target_cr_name}' validation SUCCESSFUL (type: {v.target_type})")
    logging.info("=" * 80)
