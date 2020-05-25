#!/bin/bash
#
# Dumps and pushes a backup of the current minecraft world. The actual backup
# and push to S3 is delegated to prospector, this script takes care of:
#
# 1. Notifying users that a dump is happening (a brief freeze may occur).
# 2. Suspending all writes to disk.
# 3. Performing a full, manual dump to disk.
# 4. Launching prospector to create and push the backup.
# 5. Resuming normal operates, including writes to disk.
#
# ./backup.sh [minecraft_root]
#
# `minecraft_root` should be the base directory everything minecraft-related is
# installed to, usually /minecraft.


# Deal with script arguments
MINECRAFT_ROOT=${1:-/minecraft}

TMUX_SESSION=minecraft
TMUX_PANE=${TMUX_SESSION}:0.0


# TODO: Helper functions are duplicated from shutdown.sh

# minecraft_cmd <string>
#
# Connect to the "minecraft" tmux session and send commands to the
# first pane, presumably the one the server is running in.
minecraft_cmd () {
    tmux send-keys -t "${TMUX_PANE}" "$1" C-m
}

# minecraft_msg <text> [<color>]
#
# Connects to the "minecraft" tmux session and sends a message containing
# <text> marked for all users. <color> is a string, defaulting to "gold" if not
# set. See supported colors here:
# https://minecraft.gamepedia.com/Formatting_codes
minecraft_msg () {
    action="${1}"
    color="${2:-gold}"

    # Sends a json-formatted message to all players
    minecraft_cmd "/tellraw @a {\"text\": \"$action\", \"color\": \"$color\"}"
}

echo "Starting backup at `date`"
minecraft_msg "[MINING-CAMP] Backing up world..."

# Make sure any half-finished commands are cleared out, if someone was manually
# playing with the server
minecraft_cmd C-m

# Turn off automatic saving, and flush world state to disk
minecraft_cmd "/save-off"
minecraft_cmd "/save-all flush"

# Sleep while flushing
sleep 15

# Delegate backup create and transfer to prospector
$MINECRAFT_ROOT/utilities/prospector.py backup

# Log and notify server users
if [ $? -eq 0 ]; then
    msg="Backup completed successfully at `date`!"
    echo "${msg}"
else
    msg="Backup failed at `date`!"
    echo "${msg}" >&2
fi
minecraft_msg "[MINING-CAMP] ${msg}"

# Resume normal server operations even if the backup failed
minecraft_cmd "/save-on"
