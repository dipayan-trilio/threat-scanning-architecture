import logging
import os
import json
import pytz
from datetime import datetime
from jsonformatter import JsonFormatter
from mount_utility import constants


class TimezoneJsonFormatter(JsonFormatter):
    def formatTime(self, record, datefmt=None):
        tz_str = os.environ.get('TZ')
        try:
            # Use UTC if TZ is not set
            tz = pytz.timezone(tz_str if tz_str else 'UTC')
        except pytz.UnknownTimeZoneError:
            # Fallback to UTC if timezone is invalid
            tz = pytz.utc

        ct = datetime.fromtimestamp(record.created, tz)

        if datefmt:
            return ct.strftime(datefmt)

        return super(TimezoneJsonFormatter, self).formatTime(record, datefmt)


fields = {}
log_level = logging._nameToLevel.get(
    str(os.getenv(constants.LogLevelEnv)).upper())
if not log_level:
    log_level = logging.INFO

pod_UID = os.getenv(constants.PodUID, "")

tvk_version = os.getenv(constants.TVKVersion, "")

instance_ID = os.getenv(constants.InstanceID, "")

targetGroup = ""
transactionID = ""
transaction_resource_name = ""
transaction_resource_namespace = ""
service_type = constants.DatastoreAttacherService

STRING_FORMAT = {
    "level": "%(levelname)s",
    "file": "%(pathname)s:%(lineno)s",
    "func": "funcName",
    "time": "asctime",
    "service_type": "",
    "service_id": pod_UID,
    "tvk_version": tvk_version,
    "tvk_instance_id": instance_ID,
    "transaction_type": constants.TargetKind,
    "group": "",
    "transaction_id": "",
    "transaction_resource_name": "",
    "transaction_resource_namespace": "",
    "msg": "message"
}
logger = logging.getLogger()
logger.setLevel(log_level)
formatter = TimezoneJsonFormatter(json.dumps(STRING_FORMAT), datefmt="%Y-%m-%dT%H:%M:%S%z")
sh = logging.StreamHandler()
sh.setFormatter(formatter)
logger.addHandler(sh)


def SetLoggerIdentifier():
    STRING_FORMAT["group"] = targetGroup
    STRING_FORMAT["transaction_id"] = transactionID
    STRING_FORMAT["transaction_resource_name"] = transaction_resource_name
    STRING_FORMAT["transaction_resource_namespace"] = transaction_resource_namespace
    STRING_FORMAT["service_type"] = service_type
    formatter = TimezoneJsonFormatter(json.dumps(STRING_FORMAT), datefmt="%Y-%m-%dT%H:%M:%S%z")
    shr = logging.StreamHandler()
    shr.setFormatter(formatter)
    shr.setLevel(log_level)
    if logger.hasHandlers():
        logger.handlers[0].setFormatter(formatter)
