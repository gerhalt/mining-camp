#!/bin/bash
#
# ./shutdown.sh minecraft_root
#
# `minecraft_root` should be the base directory everything minecraft-related is
# installed to, usually /minecraft. This script can be run in two different
# modes, depending on whether it is backgrounded (&) or not.
#
# "Daemon" Mode
#
# Every 5 seconds, checks whether the instance is going to be shut down or
# terminated soon. If the instance is to be stopped or terminated, performs the
# same steps as Active mode.
#
# "Active" Mode
#
# Immediately does the following
#
# 1. Notifies players via a server broadcast that the server will be shut down
#    after a brief delay.
# 2. Shuts the server down.
# 3. Runs a backup on the server world and pushes it to S3.
#
#
# NOTE: This assumes that the "minecraft" tmux session is available and the
# first pane is the one the minecraft server and console is running in.

# Deal with script arguments
MINECRAFT_ROOT=${1:-/minecraft}

TMUX_SESSION=minecraft
TMUX_PANE=${TMUX_SESSION}:0.0

# Number of seconds to wait before shutting server down
DELAY=30


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

# shutdown_server
#
# Sends a shutdown command to the tmux pane the server in running in, then
# waits for it to exit.
shutdown_server () {
    minecraft_cmd "stop"
    pid=`pgrep -f server-start.sh`
    while ps -p $pid > /dev/null; do
        sleep 1
    done
}


# Check if the script is running in the foreground or in the background.
# - Background: Run in daemon mode, checking for emergency shutdown action
#     every few seconds.
# - Foreground: Run in active mode, immediately shutting down and backing up
#     the server.

# "+" in the ps output indicates the process is running in the foreground
mypid=$$
if [[ "$(ps -o stat= -p $mypid)" =~ \+ ]]; then
    # Foreground, script mode
    echo "Notifying users"
    minecraft_msg "[MINING-CAMP] Warning! Server is shutting down!" "red"
    minecraft_msg "[MINING-CAMP] Server going down in $DELAY seconds!" "red"

    # Brief delay, allowing players to finish up before shutting down
    echo "Shutting down server in $DELAY seconds"
    sleep $DELAY
    shutdown_server

    echo "Creating and pushing backup to S3"
    $MINECRAFT_ROOT/utilities/prospector.py backup
else
    # Background, daemon mode
    echo "Running in background mode!"

    while [ true ]; do
        # This fetches only the headers, mutes all of curl's output, and prints
        # only the HTTP status code returned. If this code is anything other than a
        # 404, investigate further.
        status_code=`curl -I -s -o /dev/null -w '%{http_code}' http://169.254.169.254/latest/meta-data/spot/instance-action`

        if [ "$status_code" != "404" ]; then
            # Determine what action is being taken on the instance
            # See http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-interruptions.html
            # for more details on this.
            resp=`curl http://169.254.169.254/latest/meta-data/spot/instance-action`
            # resp='{"action": "stop", "time": "2017-09-18T08:22:00Z"}'

            # Parse the action and the time out of the message
            action=`echo $resp | jq -r '.action'`
            time=`echo $resp | jq -r '.time'`

            minecraft_msg "[MINING-CAMP] Warning! Spot instance terminating!" "red"
            minecraft_msg "[MINING-CAMP] Server going down in $DELAY seconds!" "red"

            # Brief delay, allowing players to finish up before shutting down
            sleep $DELAY
            shutdown_server

            # Create and push a backup to S3
            $MINECRAFT_ROOT/utilities/prospector.py backup

            break
        fi

        sleep 5
    done
fi
