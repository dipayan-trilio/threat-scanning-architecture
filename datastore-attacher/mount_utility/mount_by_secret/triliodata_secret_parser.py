import sys
import os
import logging
from io import StringIO
from mount_utility import constants
from mount_utility import utilities

import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

logging.basicConfig(level=logging.INFO)


def get_list_from_secret_by_key(key):
    """
    returns the list (nested dict) of all the objects by the
    key passed. key can be 'datastore'/'retentionPolicy'/'defaultTimeouts'
    :param key: str -> key (datastore/defaultTimeouts/retentionPolicy) to be parsed from the trilio-secret file
    :return: list[dict] -> list of all objects for a specific key in the secret
    """
    try:
        secret_file_path, secret_filename = utilities.get_secret_path_filename()
        logging.debug(
            "fetching the dictionary from %s/%s",
            secret_file_path,
            secret_filename)

        secret_from_file = open(os.path.join(secret_file_path,
                                             secret_filename)).read()
        secret_dict = yaml.load(StringIO(secret_from_file), Loader=Loader)
        obj_dict = secret_dict.get(key)
        logging.debug("parsed the secret yaml from the file: \n%s", obj_dict)

        return obj_dict
    except OSError as err:
        logging.exception("Could not open/read secret file:", err)
    except yaml.YAMLError as exc:
        logging.exception("Unable to parse secret file:", exc)
    except Exception as ex:
        logging.exception(ex)
        raise Exception(ex)


def get_default_ds(datastores):
    """
    return the datastore key-value (nested dict)
    which is set as default by the admin
    :param datastores: List[dict] -> list of all the datastore from which the default is to be found
    :return: dict -> dict of a datastore
    """
    try:
        logging.debug(
            "Fetching default datastore from all the list of datastores across all the types")
        if datastores:
            for ds in datastores:
                if ds.get(constants.DEFAULT_DATASTORE) == constants.YAML_TRUE:
                    logging.debug(
                        "Found default datastore with name %s and type %s", ds.get(
                            constants.NAME), ds.get(
                            constants.DATASTORE_TYPE))
                    return ds
        else:
            logging.error("error: no datastores returned from the secret environment variable")
            return {}

    except Exception as ex:
        logging.exception(ex)
        raise Exception(ex)


def get_ds_by_type(datastores, ds_type):
    """
    returns the list (nested dict) of all the
    datastore of a given type
    :param datastores: List[dict] -> list of all the datastore from which the default is to be found
    :param ds_type: str -> type of datastore to be mounted (NFS/S3)
    :return: list[dict] -> datastore_list by type
    """
    try:
        ds_of_type = []

        logging.debug(
            "Fetching the Datastore by the type: %s from the list of all datastores",
            ds_type)
        if datastores:
            for ds in datastores:
                if ds.get(constants.DATASTORE_TYPE) == ds_type:
                    ds_of_type.append(ds)
            logging.debug("prepared the list of all the datastores of the type: %s, total found: %s",
                          constants.DATASTORE_TYPE,
                          len(ds_of_type))
            return ds_of_type
        else:
            logging.error(
                "error: no datastores returned from the secret environment variable")
            return ds_of_type

    except Exception as ex:
        logging.exception(ex)
        raise Exception(ex)


def get_ds_by_name(datastores, ds_name):
    """
    returns the list (nested dict) of all the
    datastore of a given name
    ASSUMPTION: Each datastore name will be unique
    :param datastores: List[dict] -> list of all the datastore from which the default is to be found
    :param ds_name: str -> name of the datastore to be found
    :return: dict -> datastore dict by name
    """
    try:
        logging.debug("Getting datastores by name %s", ds_name)
        if datastores:
            for ds in datastores:
                if ds.get(constants.NAME) == ds_name:
                    logging.debug("Found the datastore with the given name: %s\n", ds)
                    return ds
        else:
            logging.error("error: no datastores returned from the secret environment variable")
            return []

    except Exception as ex:
        logging.exception(ex)
        raise Exception(ex)


def parse_datastore(all_ds, ds_name, default_datastore):
    """
    fetched the list of all the datastores from the secret yaml and
    returns the list of nfs and s3 datastores by the names specified and
    if no flag is specified, returns the default datastore defined by admin
    :param all_ds: List[dict] -> list of all the datastores
    :param ds_name: str -> name of the datastore to be found
    :param default_datastore: bool -> True if default datastore is to be found
    :return: list[dict] -> datastores_list according to the filters
    """
    try:
        logging.debug("Parsing the secret yaml to get the list of datastores")
        all_datastores = get_list_from_secret_by_key(constants.DATASTORE)
        if not all_datastores:
            logging.error("No datastore found in the secret yaml. Exiting now...")
            sys.exit(1)

        datastores = []

        if default_datastore:
            # if nothing is specified, get default datastore
            ds = get_default_ds(all_datastores)
            logging.debug("Fetched the default datastore as no flag is specified with the name %s and type %s",
                          ds.get(constants.NAME),
                          ds.get(constants.DATASTORE_TYPE))
            datastores.append(ds)
            return datastores

        if ds_name:
            logging.debug("fetching the datastore with the name: %s", ds_name)
            datastores.append(get_ds_by_name(all_datastores, ds_name))
            return datastores

        if all_ds:
            logging.debug("fetched all the datastores to be mounted")
            return all_datastores

    except Exception as ex:
        logging.exception(ex)
        raise Exception(ex)
