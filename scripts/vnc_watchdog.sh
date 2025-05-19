#!/usr/bin/env bash

HOST="${1:-localhost}"
PORT="${2:-5900}"
CLIENT="${3:-vncviewer}"

echo "Waiting for VNC server at ${HOST}:${PORT}..."
while true; do

    banner=$(echo -n | nc -w1 $HOST $PORT | head -c 3 2>/dev/null)
    if [[ $banner == RFB ]]; then
        $CLIENT "${HOST}:${PORT}"
    fi

    sleep 1
done
