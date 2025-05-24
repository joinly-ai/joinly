#!/usr/bin/env bash

CLIENT="${1:-vncviewer}"
HOST="${2:-localhost}"
PORT="${3:-5900}"

if ! command -v "$CLIENT" &> /dev/null; then
    echo "Error: $CLIENT executable not found." >&2
    exit 1
fi

echo "Waiting for VNC server at ${HOST}:${PORT}..."
while true; do

    banner=$(echo -n | nc -w1 "$HOST" "$PORT" | head -c 3 2>/dev/null)
    if [[ $banner == RFB ]]; then
        "$CLIENT" "${HOST}:${PORT}"
    fi

    sleep 1
done
