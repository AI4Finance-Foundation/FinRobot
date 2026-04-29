#!/bin/bash
# FinAgent deploy helper — start/stop/status the web server.
# Usage: ./deploy.sh start | stop | status

set -euo pipefail

HOST="${FINAGENT_HOST:-127.0.0.1}"
PORT="${FINAGENT_PORT:-8000}"

case "${1:-help}" in
  start)
    echo "Starting FinAgent server on ${HOST}:${PORT}..."
    echo "WARNING: To expose to network, set FINAGENT_HOST=0.0.0.0 (no authentication!)"
    uv run finagent serve --host "$HOST" --port "$PORT" &
    echo "PID: $!"
    ;;
  stop)
    pkill -f "finagent serve" && echo "Stopped." || echo "Not running."
    ;;
  status)
    pgrep -f "finagent serve" > /dev/null && echo "Running" || echo "Stopped"
    ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
