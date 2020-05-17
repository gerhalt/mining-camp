#!/bin/bash
#
# Simple script to handle automatic server restarts. This helps with memory leaks accumulating too much RAM.
#

# Shut down the server gracefully and backup to S3
sh shutdown.sh

# Wait for a few minutes so that everything clears out. Especially the RAM which can accumulate.
sleep 5m

# Start up the server
sh bootstrap.sh