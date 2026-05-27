#!/bin/bash
# FinRobot deploy helper — start/stop/status the web server.
# Usage: ./deploy.sh start | stop | status

set -euo pipefail

HOST="${FINROBOT_HOST:-127.0.0.1}"
PORT="${FINROBOT_PORT:-8321}"

case "${1:-help}" in
  start)
    echo "Starting FinRobot server on ${HOST}:${PORT}..."
    echo "WARNING: To expose to network, set FINROBOT_HOST=0.0.0.0 (no authentication!)"
    uv run finrobot serve --host "$HOST" --port "$PORT" &
    echo "PID: $!"
    ;;
  stop)
    pkill -f "finrobot serve" && echo "Stopped." || echo "Not running."
    ;;
  status)
    pgrep -f "finrobot serve" > /dev/null && echo "Running" || echo "Stopped"
    ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
