#!/usr/bin/env bash
set -euo pipefail

# start pulseaudio
pulseaudio --start --exit-idle-time=-1

# wait for pulseaudio to start
for i in {1..10}; do
  if pactl info >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# run app with commands
exec /app/.venv/bin/meeting-agent "$@"
