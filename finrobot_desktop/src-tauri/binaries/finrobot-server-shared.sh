#!/usr/bin/env bash
# Tauri sidecar wrapper for the FinRobot Python FastAPI server.
#
# Tauri resolves this file via a platform-triple symlink, e.g.:
#   finrobot-server-aarch64-apple-darwin -> finrobot-server-shared.sh
#
# Arguments forwarded from Tauri: --host 127.0.0.1 --port 8321

set -euo pipefail

# Resolve project root: src-tauri/binaries/ -> src-tauri/ -> project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Require uv; give a clear error if missing.
if ! command -v uv &>/dev/null; then
    echo >&2 "[finrobot-server] ERROR: 'uv' not found on PATH."
    echo >&2 "[finrobot-server] Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

HOST="127.0.0.1"
PORT="8321"
ARGS=("$@")
for ((i = 0; i < ${#ARGS[@]}; i++)); do
    case "${ARGS[$i]}" in
        --host)
            HOST="${ARGS[$((i + 1))]:-$HOST}"
            ;;
        --port)
            PORT="${ARGS[$((i + 1))]:-$PORT}"
            ;;
    esac
done

if command -v curl &>/dev/null && command -v lsof &>/dev/null; then
    if ! curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
        PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
        for PID in $PIDS; do
            CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
            PPID_VALUE="$(ps -p "$PID" -o ppid= 2>/dev/null | tr -d ' ' || true)"
            PARENT_CMD="$(ps -p "$PPID_VALUE" -o command= 2>/dev/null || true)"
            if [[ "$CMD" == *"finrobot"* || "$CMD" == *"uvicorn"* || "$CMD" == *"uv run"* || "$PARENT_CMD" == *"finrobot"* ]]; then
                echo >&2 "[finrobot-server] Clearing unresponsive FinRobot process on ${HOST}:${PORT} (pid=${PID})."
                kill "$PID" 2>/dev/null || true
            fi
        done
        sleep 1
    fi
fi

if [[ "${FINROBOT_SERVER_RELOAD:-0}" == "1" ]]; then
    exec uv run finrobot serve --reload "$@"
fi

exec uv run finrobot serve "$@"
