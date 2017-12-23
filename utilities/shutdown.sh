#!/bin/bash
#
# ./shutdown.sh server_path
#
# Every 5 seconds, checks whether the instance is going to be shut down or
# terminated soon. If the instance is to be stopped or terminated, does the
# following:
#
# 1. Notifies players via a server broadcast.
# 2. Shuts the server down.
# 3. Runs a backup on the server world and pushes it to S3.
#
# NOTE: This assumes that the "minecraft" tmux session is available and the
# first pane is the one the minecraft server and console is running in.

# Deal with script arguments
SERVER_ROOT=${1:-/minecraft}

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

        minecraft_msg "[AWS] Warning! Spot instance terminating!" "red"
        minecraft_msg "[AWS] Server going down in $DELAY seconds!" "red"

        # Brief delay, allowing players to finish up before shutting down
        sleep $DELAY

        # Shut the server down, and wait for it to exit
        minecraft_cmd "stop"
        pid=`pgrep -f ServerStart.sh`
        while ps -p $pid; do
            sleep 1
        done

        # Create and push a backup to S3
        $SERVER_ROOT/mining-camp/utilities/prospector.py backup_current

        break
    fi

    sleep 5
done
