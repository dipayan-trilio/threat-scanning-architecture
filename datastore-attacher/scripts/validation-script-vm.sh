#!/bin/bash

# Function to execute a command and check its result
run_check() {
  local COMMAND=$1
  local ERROR=$2

  # Trim spaces from the command
  COMMAND=$(echo "$COMMAND" | xargs)

  echo -e "\nChecking: $COMMAND"
  if eval "$COMMAND" >/dev/null 2>&1; then
    echo -e "Status: SUCCESS"
  else
    echo -e "Status: FAILED"
    failed_checks+=("Command: '$COMMAND' Error Description: $ERROR")
  fi
}

# Array of commands and user-friendly descriptions
system_checks=(
  "yum list installed | grep epel-release                    ### epel-release repository is missing. Ensure it is installed and properly configured."
  "python3 --version                                         ### Python 3 is not installed or not available. Verify the Python 3 setup on your system."
  "pip3 --version                                            ### Python 3 PIP is missing. Make sure pip is installed and accessible."
  "yum list installed | grep python3-pip                     ### python3-pip package is missing. Verify if it is installed."
  "pip3 show setuptools                                      ### Python setuptools package is missing. Confirm that setuptools is installed."
  "yum list installed | grep python3-setuptools              ### python3-setuptools package is missing. Verify if it is installed."
  "yum list installed | grep tzdata                          ### tzdata package is missing. Confirm that it is installed."
  "timedatectl status | grep \'Time zone\'                     ### Time zone configuration is incorrect. Ensure your system has the correct time zone set."
  "yum list installed | grep librbd1                         ### The required library librbd1 is missing. Verify its installation."
  "yum list installed | grep lvm2                            ### Logical Volume Manager (lvm2) tools are missing. Check if they are installed."
  "yum list installed | grep yum-utils                       ### yum-utils package is missing. Confirm that yum-utils is installed."
  "yum list installed | grep qemu-img                        ### QEMU image tool is missing. Ensure qemu-img is installed."
  "yum list installed | grep ntfs-3g                         ### ntfs-3g driver is not installed. Confirm its availability on your system."
  "pip3 show PyYAML                                          ### PyYAML package is not installed. Verify if it is available for Python 3. Install by running 'pip3 install PyYAML'."
  "pip3 show jsonformatter                                   ### JSON Formatter package is missing. Verify its installation for Python 3. Install by running 'pip3 install jsonformatter'."
  "pip3 show s3fuse                                          ### s3fuse package is not installed. Check if it is installed and accessible. Install by running 'pip3 install s3fuse'."
  "yum repolist | grep docker-ce                             ### Docker CE repository is not added. Confirm that the repository is configured correctly."
  "yum list installed | grep docker-ce                       ### Docker CE is not installed. Verify its availability on your system."
  "yum list installed | grep docker-ce-cli                   ### docker-ce-cli package is missing. Confirm if it is installed."
  "yum list installed | grep containerd.io                   ### containerd.io is missing. Ensure it is properly installed."
  "yum list installed | grep docker-buildx-plugin            ### Docker Buildx plugin is missing. Verify its installation status."
  "yum list installed | grep docker-compose-plugin           ### Docker Compose plugin is not installed. Confirm its availability on your system."
  "systemctl is-enabled docker                               ### Docker service is not enabled. Verify its startup configuration."
  "systemctl is-active docker                                ### Docker service is not running. Ensure it is started and running correctly."
  "test -d /triliodata                                       ### Directory /triliodata does not exist. Verify its presence on the system."
  "test -d /triliodata-temp                                  ### Directory /triliodata-temp does not exist. Ensure it is created."
  "test -d /opt/tvk                                          ### Directory /opt/tvk does not exist. Confirm that the directory exists."
  "grep \'export PYTHONPATH=/opt/tvk/datastore-attacher\' /etc/profile.d/custom_env.sh ### PYTHONPATH environment variable is not set. Verify its addition to environment variables."
  "test -x /etc/profile.d/custom_env.sh                     ### Environment script '/etc/profile.d/custom_env.sh' is not executable. Ensure proper file permissions are set."
)

# Array to store failed checks
failed_checks=()

# Run system checks
for check in "${system_checks[@]}"; do
  # Split command and error message
  IFS='###' read -r COMMAND ERROR <<< "$check"
  run_check "$COMMAND" "$ERROR"
done

# Display the final result
if [ ${#failed_checks[@]} -eq 0 ]; then
  echo -e "\nAll checks passed successfully."
  exit 0
else
  echo -e "\nThe following checks failed:\n"
  for failure in "${failed_checks[@]}"; do
    echo "- $failure"
  done
  exit 1
fi
