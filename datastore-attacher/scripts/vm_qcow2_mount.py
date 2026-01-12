#!/usr/bin/python3
import random
import re
import os
import subprocess
import sys
import argparse
import json
import glob

from mount_utility import constants

file_recovery_vm_cr_name, file_recovery_vm_cr_namespace, location, vm_name, action = "", "", "", "", ""


def _(*args):
    return str(args[0])


class log():

    def __init__(self, show_logs=False):
        self.show_logs = show_logs

    def printer(self, data):
        if self.show_logs:
            print(data)

    def info(self, *arg):
        self.printer(arg[0])

    def exception(self, *arg):
        self.printer(arg[0])

    def error(self, *arg):
        self.printer(arg[0])

    def debug(self, *arg):
        self.printer(arg[0])

    def critical(self, *arg):
        self.printer(arg[0])

    def warning(self, *arg):
        self.printer(arg[0])


LOG = None
partitions = []


def getfdisk_output(devname=None):
    """
    Retrieves and parses the output of the 'fdisk -l' command to list partitions.

    Parameters:
    devname (str): The device name (e.g., '/dev/sda') to be passed to the fdisk command.
                   If None, the command will list partitions for all devices.

    Returns:
    list: A list of dictionaries, each representing a partition with its details.

    Example 'fdisk -l /dev/sda' output:
    """
    partitions = []
    cmdspec = ["sudo", "fdisk", "-l", ]
    if devname:
        cmdspec.append(str(devname))
    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)
    stdout_value, stderr_value = process.communicate()
    parse = False

    # Sample fdisk output
    """
    Disk /dev/sda: 1000 GB, 1000171334912 bytes
    255 heads, 63 sectors/track, 121601 cylinders, total 1953458176 sectors
    Units = sectors of 1 * 512 = 512 bytes
    Sector size (logical/physical): 512 bytes / 4096 bytes
    I/O size (minimum/optimal): 4096 bytes / 4096 bytes
    Disk identifier: 0x00000000

       Device Boot      Start         End      Blocks   Id  System
    /dev/sda1   *        2048    19531775     9764864   83  Linux
    /dev/sda2        19531776  1953458175   966963200   8e  Linux LVM
    """

    # parsing logic
    """
    For each subsequent line, it splits the line into fields.
    It initializes an empty dictionary partition to store partition details.
    It extracts and assigns values from the fields to the dictionary:
    Device Name: The first field.
    Boot Device: If the second field is "*", it's a boot device.
    start: The starting sector.
    end: The ending sector.
    blocks: The number of blocks, stripped of any trailing "+".
    id: The partition ID, converted to lowercase.
    system: The system type, which can span multiple fields.
    """
    # validation
    """
    It checks if the 'start', 'end', and 'blocks' fields contain numeric values using regular expressions.
    If valid, the partition dictionary is appended to the partitions list.

    The function returns the list of partitions, each represented as a dictionary with detailed attributes.
    """

    for line in stdout_value.split("\n"):
        if parse:
            partition = {}
            fields = line.split()
            if (len(fields) == 0):
                continue
            index = 0
            # Parsing the fields of each partition line
            partition["Device Name"] = fields[index]
            index += 1

            # Check if the partition is a boot device
            if fields[index] == "*":
                partition["Boot Device"] = str(True)
                index += 1
            else:
                partition["Boot Device"] = str(False)

            # Extracting start, end, blocks, id, and system type
            partition["start"] = fields[index]
            index += 1
            partition["end"] = fields[index]
            index += 1
            partition["blocks"] = fields[index].strip("+")
            index += 1
            partition["id"] = fields[index].lower()
            index += 1
            partition["system"] = " ".join(fields[index:])
            index += 1

            # TODO: verify if we can get any info in partition which will cause issue in parsing
            # Validate if 'start', 'end', and 'blocks' are numeric before adding to the list
            if len(re.findall(r'\d+', partition['start'])) and \
                    len(re.findall(r'\d+', partition['end'])) and \
                    len(re.findall(r'\d+', partition['blocks'])):
                partitions.append(partition)

        # Start parsing after detecting the line with "Device Boot"
        if "Device" in line and "Boot" in line:
            parse = True
    return partitions


def getgptdisk_output(devname=None):
    partitions = []
    cmdspec = ["sudo", "parted", "-s", ]
    if devname:
        cmdspec.append(str(devname))
    cmdspec.append("print")
    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)
    stdout_value, stderr_value = process.communicate()
    stdout_value = stdout_value.decode('utf-8')

    # Sample command (parted -s /dev/nbd8 print ) output
    # Model: Unknown (unknown)
    # Disk /dev/nbd8: 32.2GB
    # Sector size (logical/physical): 512B/512B
    # Partition Table: gpt
    # Disk Flags:

    # Number  Start   End     Size    File system  Name  Flags
    #  1      1049kB  2097kB  1049kB                     bios_grub
    #  2      2097kB  107MB   105MB   fat16              boot, esp
    #  3      107MB   32.2GB  32.1GB  xfs

    parse = False
    fs_start_index, fs_end_index, name_start_index, name_end_index = None, None, None, None
    if not process.returncode:
        for line in stdout_value.split("\n"):
            if parse:
                partition = {}
                fields = line.split()
                if (len(fields) == 0):
                    continue
                index = 0
                partition["Number"] = fields[index]
                index += 1
                partition["start"] = fields[index]
                index += 1
                partition["end"] = fields[index]
                index += 1
                partition["size"] = fields[index]
                index += 1

                fsval = line[fs_start_index:fs_end_index].strip()
                if len(fsval) > 0:
                    partition["filesystem"] = fsval

                partition["name"] = ""
                nameval = line[name_start_index:name_end_index].strip()
                if len(nameval) > 0:
                    partition["name"] = nameval

                partition['devname'] = devname
                if "0.00B" in partition['start']:
                    partition["partname"] = devname
                else:
                    partition["partname"] = "%sp%s" % (devname, str(partition['Number']))
                partitions.append(partition)
            if "Number" in line and "Start" in line and "End" in line and \
                    "Size" in line and "File system" in line and "Flags" in line:
                parse = True
                fs_start_index = line.find("File system")
                name_start_index = line.find("Name")
                fs_end_index = name_start_index
                name_end_index = line.find("Flags")
    else:
        partition = {}
        partition["devname"] = devname

        # if partition table is not avaialable then we will be trying to mount whole device.
        # thats why keeping `partname` equls to `devname`.
        # And keeping `filesystem` to `unknown` to avoid skipping mounting for this partition
        # in `mount_filesystems` function.
        partition["partname"] = devname
        partition["filesystem"] = "unknown"
        partitions.append(partition)
    return partitions


def mountdevice(devname, mntpath):
    mountoptions = [[], ["-o", "nouuid"], ["-o", "ro"], ["-o", "ro,noload"]]

    try:
        for opt in mountoptions:
            cmdspec = ["sudo", "mount", ]
            cmdspec += opt
            cmdspec += [devname, mntpath]
            process = subprocess.Popen(cmdspec,
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       bufsize=-1,
                                       close_fds=True,
                                       shell=False)
            stdout_value, stderr_value = process.communicate()
            if process.returncode == 0:
                LOG.info(" ".join(cmdspec))
                return
            else:
                LOG.info("failed to execute {} command, stdout:{}, \
                         stderr:{}".format(" ".join(cmdspec),
                                           stdout_value, stderr_value))
    except BaseException as ex:
        raise BaseException(ex)


def umountdevice(mntpath):
    mountoptions = [[], ["-o", "nouuid"], ["-o", "ro"], ["-o", "ro,noload"]]
    for opt in mountoptions:
        try:
            cmdspec = ["sudo", "umount", ]
            cmdspec += opt
            cmdspec += [mntpath]
            process = subprocess.Popen(cmdspec,
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       bufsize=-1,
                                       close_fds=True,
                                       shell=False)
            stdout_value, stderr_value = process.communicate()
            if process.returncode == 0:
                return
        except BaseException as e:
            cmdstring = " ".join(cmdspec)
            LOG.exception(f"Failed to execute command '{cmdstring}', thrown exception {e}")


def lvtodev():
    cmdspec = ["sudo", "lvs", "--noheading", "-o", "lv_path,devices"]
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)
    stdout_value, stderr_value = process.communicate()
    stdout_value = stdout_value.decode('utf-8')
    # sample output
    # /dev/vg0/lv_root       /dev/sda2(0)
    # /dev/vg0/lv_home       /dev/sda2(4096)
    # /dev/vg0/lv_swap       /dev/sda2(8192)

    lv2pv = {}
    for line in stdout_value.split("\n"):
        if len(line.split()) >= 2:
            lv = line.split()[0]
            dev = line.split()[1].split("(")[0]
            if lv not in lv2pv:
                lv2pv[lv] = set([])
            lv2pv[lv].add(dev)
    return lv2pv


def mountvolumes(disks):
    lv2pv = lvtodev()
    vg_refresh_cmds = ['sudo vgchange --refresh',
                       'sudo pvscan',
                       'sudo vgscan',
                       'sudo vgchange --refresh']
    for cmd in vg_refresh_cmds:
        cmdspec = cmd.split()
        LOG.info(_(" ".join(cmdspec)))
        process = subprocess.Popen(cmdspec,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   bufsize=-1,
                                   close_fds=True,
                                   shell=False)
        stdout_value, stderr_value = process.communicate()
        if stderr_value:
            LOG.warning(_('Error: cmd "%s", %s' % (cmd, stderr_value)))
    cmdspec = ["sudo", "lvdisplay", "-c"]
    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)
    stdout_value, stderr_value = process.communicate()
    stdout_value = stdout_value.decode('utf-8')
    mountspath = disks['mount_dir']
    if process.returncode == 0 and len(stdout_value) > 0:
        for line in stdout_value.split("\n"):
            fields = line.split(":")
            if len(fields) == 0:
                continue
            lvpath = fields[0].strip()
            if os.path.exists(lvpath):
                volume = os.path.split(lvpath)[1]
                vgname = fields[1]
                should_continue = False
                for pv in list(lv2pv[lvpath]):
                    if [p for p in disks['vms']['nbds'] if p in pv]:
                        should_continue = True
                        break
                if not should_continue:
                    continue
                vmpath = os.path.join(mountspath, "volumes")
                try:
                    os.makedirs(vmpath, exist_ok=True)
                except BaseException as ex:
                    raise BaseException(ex)
                vgpath = os.path.join(vmpath, vgname)
                try:
                    os.makedirs(vgpath, exist_ok=True)
                except BaseException as ex:
                    raise BaseException(ex)
                mntpath = os.path.join(vgpath, volume)
                try:
                    os.makedirs(mntpath, exist_ok=True)
                except BaseException as ex:
                    raise BaseException(ex)
                mountdevice(lvpath, mntpath)


def create_overlayfiles(disks, encryptKey):
    overlays_dir = disks['overlays_dir']
    os.makedirs(overlays_dir, exist_ok=True)
    os.makedirs(os.path.join(overlays_dir, "vms"), exist_ok=True)
    for ds in disks['vms'].get('backups'):
        ds_path_arr = ds.split("/")
        disk_name = ds_path_arr[len(ds_path_arr) - 2]
        os.makedirs(os.path.join(overlays_dir, "vms", disk_name), exist_ok=True)
        base = os.path.basename(ds)
        overlay_path = os.path.join(overlays_dir, "vms", disk_name, base)

        cmdspec = []
        process = None

        if encryptKey:
            cmdspec = [
                "sudo", "qemu-img", "create",
                "--object", f"secret,id=sec0,data={encryptKey}",
                "-o", "encrypt.format=luks,encrypt.key-secret=sec0",
                "-b", (
                    f'json:{{ "encrypt.key-secret": "sec0", "driver": "qcow2", '
                    f'"file": {{ "driver": "file", "filename": "{ds}" }} }}'
                ),
                "-f", "qcow2", f"{overlay_path}"
            ]

            process = subprocess.Popen(cmdspec, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        else:
            cmdspec = ["sudo", "qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", ds, overlay_path]
            process = subprocess.Popen(cmdspec,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             bufsize=-1,
                             close_fds=True,
                             shell=False)
        LOG.info(_(" ".join(cmdspec)))

        stdout_value, stderr_value = process.communicate()
        LOG.debug("command:{}, stdout: {}, stderr: {}".format(cmdspec, stdout_value, stderr_value))
        if process.returncode and stderr_value:
            raise Exception(stderr_value)
        disks['vms']['overlays'][disk_name] = overlay_path
    return


def mount_overlays(disks, encryptKey):

    NBD_DEVICE_RE = re.compile('nbd[0-9]+')

    def _detect_nbd_devices():
        """Detect nbd device files."""
        return list(filter(NBD_DEVICE_RE.match, os.listdir('/sys/block/')))

    def _find_unused(devices):
        for device in devices:
            if not os.path.exists(os.path.join('/sys/block/', device, 'pid')):
                if not os.path.exists('/var/lock/qemu-nbd-%s' % device):
                    return device
                else:
                    LOG.error(_('NBD error - previous umount did not '
                                'cleanup /var/lock/qemu-nbd-%s.') % device)
        LOG.warning(_('No free nbd devices'))
        return None

    def _allocate_nbd():
        if not os.path.exists('/sys/block/nbd0'):
            LOG.error(_('nbd module not loaded'))
            return None
        devices = _detect_nbd_devices()
        random.shuffle(devices)
        device = _find_unused(devices)
        if not device:
            # really want to log this info, not raise
            return None
        return os.path.join('/dev', device)

    LOG.info("Overlay file to NBD Mapping")
    for disk_name, disk_path in disks['vms'].get('overlays', {}).items():
        device = _allocate_nbd()
        if encryptKey:
            cmdspec = [
                "sudo", "qemu-nbd",
                "--object", f"secret,id=sec0,data={encryptKey}",
                "-c", device,
                "--image-opts", f"driver=qcow2,file.filename={disk_path},encrypt.format=luks,encrypt.key-secret=sec0"
            ]
        else:
            cmdspec = ["sudo", "qemu-nbd", "-c", device, disk_path]
        LOG.info(_(" ".join(cmdspec)))
        subprocess.call(cmdspec)
        disks['vms']['nbds'][disk_name] = device
        LOG.info("%s ==> %s" % (disk_path, device))


def umount_overlays(disks):
    if disks:
        for disk_name, nbd_device in disks['vms'].get('nbds', {}).items():
            LOG.debug('Flush nbd device %s with disk_name %s' % (nbd_device, disk_name))
            cmdspec = ['sudo', 'blockdev', '--flushbufs', nbd_device]
            LOG.info(_(" ".join(cmdspec)))
            subprocess.call(cmdspec)
            LOG.debug('Release nbd device %s' % nbd_device)
            cmdspec = ["sudo", "qemu-nbd", "-d", nbd_device]
            LOG.info(_(" ".join(cmdspec)))
            subprocess.call(cmdspec)
        disks['vms']['nbds'] = {}


def scan_overlay_files(disks):
    for disk_name, dev in disks['vms'].get('nbds', {}).items():
        assert os.path.exists(dev)
        disks["vms"]["partitions"][disk_name] = getgptdisk_output(dev)


def create_mntdirs(disks):
    # TODO: We need to recreate directory structure of windows and linux
    for disk_name, partitions in disks['vms'].get('partitions', {}).items():
        # for diskname in partitions:
        for part in partitions:
            # creating mount directories only if partition contains `partname` and
            # it is having any `filesystem`
            if "partname" in part and "filesystem" in part:
                fsdevname = part["partname"]
                mntpath = disks['mount_dir']
                os.makedirs(os.path.join(mntpath, disk_name), exist_ok=True)
                mntpath = os.path.join(mntpath, disk_name, os.path.basename(fsdevname))
                try:
                    os.makedirs(mntpath, exist_ok=True)
                except BaseException as ex:
                    raise BaseException(ex)


def mount_filesystems(disks):
    for disk_name, disk_partitions in disks["vms"]["partitions"].items():
        for part in [part for part in disk_partitions if 'filesystem' in part]:
            mountdevice(part['partname'], os.path.join(disks['mount_dir'],
                                             disk_name,
                                             os.path.basename(part['partname'])))
    mountvolumes(disks)
    cmdspec = ["sudo", "mount"]
    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)
    stdout_value, stderr_value = process.communicate()
    stdout_value = stdout_value.decode('utf-8')
    LOG.info("")
    LOG.info("======Mounted File systems=======")
    LOG.info(stdout_value)
    LOG.info("=================================")
    LOG.info("")


def umount_filesystems(mntdir):
    for item in os.listdir(mntdir):
        if os.path.ismount(os.path.join(mntdir, item)):
            umountdevice(os.path.join(mntdir, item))
        if os.path.isdir(os.path.join(mntdir, item)):
            umount_filesystems(os.path.join(mntdir, item))


def check_for_encryption(location):
    try:
        encrypt_key = None

        backup_plan = get_backupplan(location)

        # Check if encryption is specified in the backup plan
        if "encryption" in backup_plan.get("spec", {}):
            encryption_file_path = os.path.join(
                constants.CLOUD_INIT_DATA_DIR_NAME,
                f"{file_recovery_vm_cr_name}-{file_recovery_vm_cr_namespace}",
                constants.FILE_RECOVERY_VM_ENCRYPTION_DIR_NAME,
                constants.ENCRYPTION_FILE_NAME
            )

            # Verify if the encryption secret file exists
            if not os.path.exists(encryption_file_path):
                raise Exception("encryption secret is not present for encrypted backupplan")

            # Read the encryption key from the file as plain text
            with open(encryption_file_path, 'r') as encryption_file:
                encrypt_key = encryption_file.read().strip()

            if not encrypt_key:
                raise Exception("encryption secret is empty")

            return encrypt_key
    except Exception as e:
        raise Exception(f"error while reading encryption secret: {str(e)}")


def parse_vm_images(vm_backup, vm_name):
    vm_images = []
    datasnapshot_list = []

    if vm_backup.get("status").get("status") != "Available":
        return None

    snapshot = vm_backup.get("status").get("snapshot")
    if snapshot.get("custom"):
        dataSnapshots = snapshot.get("custom").get("dataSnapshots")
        datasnapshot_list.extend(dataSnapshots)
    elif snapshot.get("helmCharts"):
        helm = snapshot.get("helmCharts")
        for hs in helm:
            if hs is not None:
                datasnapshot_list.extend(hs.get("dataSnapshots"))
    elif snapshot.get("operators"):
        operator = snapshot.get("operators")
        for op in operator:
            datasnapshot_list.extend(op.get("dataSnapshots"))
            if op.get("helm"):
                datasnapshot_list.extend(op.get("helm").get("dataSnapshots"))

    for ds in datasnapshot_list:
        if ds.get("owner") and ds.get("owner").get("name") == vm_name:
            vm_images.append("{}/{}/{}".format(constants.DEFAULT_DATASTORE_BASE_PATH,
                                               ds.get("location"), constants.PVQcow2Name))
    return vm_images


def write_to_disk(file_path=None, disks={}):
    if not file_path:
        file_path = '{}-{}-disks.json'.format(file_recovery_vm_cr_name, file_recovery_vm_cr_namespace)

    # Check if the file exists
    if os.path.exists(file_path):
        LOG.info(f"{file_path} already exists. Overwriting...")

    # Write the JSON data to the file
    with open(file_path, 'w') as json_file:
        json.dump(disks, json_file, indent=4)
        LOG.info(f"{file_path} has been written successfully.")


# In the current working directory, a JSON configuration file is created for each backup mount.
# This file contains details about the mounted NBD devices, which are necessary for unmounting them during cleanup.
def read_from_disk(file_path=None):
    disks = {}
    json_files = []

    # Determine the list of JSON files to process based on the file_path parameter
    if file_path:
        # If file_path is provided, use it as the only JSON file to process
        json_files = [file_path]
    else:
        # If file_path is not provided, list all JSON files in the current working directory
        json_files = glob.glob('*disks.json')

    for file_path in json_files:
        # Check if the file exists
        if os.path.exists(file_path):
            with open(file_path, 'r') as json_file:
                file_content = json.load(json_file)
                # Verify if the JSON contains the 'vms->nbds' key structure
                if 'vms' in file_content and 'nbds' in file_content['vms']:
                    LOG.info(f"JSON data read from file: {file_path}")
                    disks[file_path] = file_content
        else:
            LOG.info(f"{file_path} does not exist.")
    return disks


def perform_action(linux_vm, action, encryptKey):
    try:
        disks = {
            'vms': {
                'backups': linux_vm,
                'overlays': {},
                'nbds': {},
                'partitions': {},
            },
            'overlays_dir': '/overlays',
            'mount_dir': '/mnt',
        }

        if action == "mount":
            create_overlayfiles(disks, encryptKey)
            mount_overlays(disks, encryptKey)
            scan_overlay_files(disks)
            create_mntdirs(disks)
            mount_filesystems(disks)
            write_to_disk(disks=disks)
        elif action == "unmount":
            mount_dir = disks['mount_dir']
            umount_filesystems(mount_dir)
            all_disks = read_from_disk()
            for file_path, file_content in all_disks.items():
                umount_overlays(file_content)
                write_to_disk(file_path, file_content)
        else:
            LOG.error("Invalid action specified: %s", action)
            raise Exception("invalid action provided. Supported actions: 'mount', 'unmount'")
        return json_response(
            constants.SUCCESS,
            f"successfully performed the {action} operation",
            build_pvc_map_response(disks))
    except Exception as e:
        LOG.error(f"An error occurred during '{action}' operation: {str(e)}")
        raise Exception(f"An error occurred during '{action}' operation: {str(e)}")


def get_backupplan(location):
    backupplan_json_path = os.path.join(constants.DEFAULT_DATASTORE_BASE_PATH, location,
                                        constants.BACKUPPLAN_JSON_FILE_NAME)
    try:
        vm_backupplan = None
        with open(backupplan_json_path, "r") as backupplan_json_file:
            vm_backupplan = json.load(backupplan_json_file)

        return vm_backupplan
    except Exception as e:
        raise Exception(f"failed to retrieve backup plan from '{backupplan_json_path}' location: {str(e)}")


def get_vm_backup(location):
    backup_json_path = os.path.join(constants.DEFAULT_DATASTORE_BASE_PATH, location,
                                    constants.BACKUP_JSON_FILE_NAME)
    try:
        with open(backup_json_path, "r") as backup_json_file:
            return json.load(backup_json_file)
    except Exception as e:
        raise Exception(f"failed to retrieve backup from '{backup_json_path}' location: {str(e)}")


def initialize():
    global file_recovery_vm_cr_name, file_recovery_vm_cr_namespace, location, vm_name, action, LOG
    try:
        parser = argparse.ArgumentParser("VM filerecovery. \
        Available flags: --vm-backup-name, --vm-backup-namespace --vm-name --action.")
        parser.add_argument('--action', dest="action", required=True,
                            help="The action could be either mount or unmount")

        parser.add_argument("--location", dest="location",
                            help="VM Backup location stored on target")

        parser.add_argument('--vm-name', dest="vm_name",
                            help="The name of backed up VM required to identify VM images location")

        parser.add_argument('--filerecovery-vm-cr-name', dest="file_recovery_vm_cr_name",
                            help="The name of the FileRecovery VM CR")

        parser.add_argument('--filerecovery-vm-cr-namespace', dest="file_recovery_vm_cr_namespace",
                            help="The namespace of the FileRecovery VM CR")

        parser.add_argument("--show-logs", dest="show_logs", required=False, action="store_true",
                            help="print the all type of logs")

        args = parser.parse_args()

        file_recovery_vm_cr_name = args.file_recovery_vm_cr_name
        file_recovery_vm_cr_namespace = args.file_recovery_vm_cr_namespace
        action = args.action
        location = args.location
        vm_name = args.vm_name
        LOG = log(args.show_logs)
    except Exception as ex:
        raise Exception(f"failed to initialize the script: {str(ex)}")


def check_for_required_args(required_args):
    if any(arg is None for arg in required_args):
        raise ValueError("Argument not present: {}".format(
            "file_recovery_vm_cr_name" if file_recovery_vm_cr_name is None
            else "file_recovery_vm_cr_namespace" if file_recovery_vm_cr_namespace is None
            else "location" if location is None
            else "vm_name" if vm_name is None
            else "action"
        ))


def json_response(status: str, message: str, data=None):
    res = {
        "status": status,
        "message": message,
        "data": data
    }
    return json.dumps(res)


def build_pvc_map_response(disks):
    res = {}
    for disk_name, disk_partitions in disks["vms"]["partitions"].items():
        res[disk_name] = []
        for part in [part for part in disk_partitions if 'filesystem' in part]:
            path = os.path.join(disks['mount_dir'], disk_name, os.path.basename(part['partname']))
            res[disk_name].append(path)

    return res


# Example Success Response:
# {
#   "status": "success",
#   "message": "successfully performed the mount operation",
#   "data": {
#     "pvc-name-1": ["/mnt/linux_vm/pvc-name-1/nbd7p1"],
#     "pvc-name-2": [
#       "/mnt/linux_vm/pvc-name-2/nbd11p1",
#       "/mnt/linux_vm/pvc-name-2/nbd11p2"
#     ]
#   }
# }
#
# Example Error Response:
# {
#   "status": "error",
#   "message": "error occurred while mounting vm",
#   "error": "descriptive error message"
# }

if __name__ == "__main__":
    try:
        initialize()
        vm_images = []
        encrypt_key = None

        if action == "mount":
            check_for_required_args(
                [file_recovery_vm_cr_name, file_recovery_vm_cr_namespace, action, location, vm_name]
            )
            vm_backup = get_vm_backup(location)

            vm_backup_name = vm_backup.get("metadata").get("name")
            vm_backup_namespace = vm_backup.get("metadata").get("namespace")

            vm_images = parse_vm_images(vm_backup, vm_name)
            if not vm_images:
                raise Exception("no VM images found in the specified backup.")

            encrypt_key = check_for_encryption(location)

        check_for_required_args([action])
        result = perform_action(vm_images, action, encrypt_key)
        print(result)
    except Exception as e:
        print(json_response(constants.ERROR, "error occurred while mounting vm", str(e)))
        sys.exit(1)
