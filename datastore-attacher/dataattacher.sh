#!/bin/bash
function check-status() {
    if [ "$1" != "0" ]
    then
      exit 1
    fi
}
if [[ $(cd /triliodata 2>&1 >/dev/null | grep "Transport endpoint is not connected") != '' || $(mount | grep "TrilioVault") == "" ]]
then
  umount /triliodata
  /usr/bin/python3 /opt/tvk/datastore-attacher/mount_utility/mount_by_target_crd/mount_datastores.py --target-credential-hash="$1"
  check-status "$?"
fi