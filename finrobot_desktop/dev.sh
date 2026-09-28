#!/usr/bin/env bash
# dev.sh — local dev launcher for FinRobot (live backend source + frontend, no freezing).
#
# Every run is a clean restart: it kills the old live backend / vite first, then brings both up.
# The backend runs from finrobot source (including /api/debate; LLM and data keys are read from
# the OS keychain, not from .env), so re-run this script after editing backend code.
# The frontend runs vite HMR — edit and it hot-reloads.
#
# Two postures (the backend is live source either way; only the frontend shell differs):
#   ./dev.sh         browser posture — frontend served in the browser at http://localhost:5173
#   ./dev.sh --app   desktop-app posture — frontend in a native Tauri window (cd desktop && cargo tauri dev)
#
# --app still uses the live backend: FINROBOT_DEV_LIVE_BACKEND=1 makes the Tauri shell skip the
# frozen PyInstaller sidecar, and the window talks to the live backend this script started through
# the vite proxy (so .py edits take effect immediately). Without --app it never touches cargo tauri dev.
#
# Usage:  ./dev.sh [--app]   (Ctrl+C stops the frontend and backend / app together)

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_PORT=8321
FRONTEND_PORT=5173
BACKEND_LOG=/tmp/finrobot-backend.log
FRONTEND_DIR="$ROOT/desktop"
# Upper bound on waiting for backend readiness (seconds). On a fresh .venv the first import has to
# cold-compile the whole dependency tree to .pyc (temporalio/tokenizers/tiktoken/edgar are heavy),
# so a cold start can exceed 60s; a warm one is ~12s. The kill -0 liveness check below runs every
# second, so a real crash exits in ~1s — raising this bound only gives headroom to the legitimate
# "alive but still cold-compiling" path without weakening crash detection. Override via env.
BACKEND_READY_TIMEOUT="${FINROBOT_BACKEND_READY_TIMEOUT:-240}"

# ── Frontend shell: browser (default) | app (native Tauri window) ────────────
FRONTEND_MODE=browser
case "${1:-}" in
  --app) FRONTEND_MODE=app ;;
  "")    ;;
  *) echo "Unknown argument: $1 (usage: ./dev.sh [--app])" >&2; exit 2 ;;
esac

# ── Pick the backend executable: prefer the venv's finrobot, fall back to uv run ─
if [ -x ".venv/bin/finrobot" ]; then
  BACKEND_CMD=(.venv/bin/finrobot serve --host 127.0.0.1 --port "$BACKEND_PORT")
else
  BACKEND_CMD=(uv run finrobot serve --host 127.0.0.1 --port "$BACKEND_PORT")
fi

# ── Kill whatever is listening on a port (macOS-safe; no xargs -r) ───────────
kill_port() {
  local port="$1" pids
  pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null
  fi
}

echo "▸ Stopping any old live backend / vite ..."
pkill -f "finrobot serve" 2>/dev/null
pkill -f "desktop/node_modules/.bin/vite" 2>/dev/null
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
sleep 1

# ── Start the live backend (background) ──────────────────────────────────────
echo "▸ Starting live backend (source, :${BACKEND_PORT}), log → ${BACKEND_LOG}"
"${BACKEND_CMD[@]}" >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Stop the backend too on Ctrl+C / exit
cleanup() {
  echo
  echo "▸ Stopping backend (pid $BACKEND_PID) ..."
  kill "$BACKEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

# ── Wait for backend readiness (/openapi.json always exists on FastAPI) ──────
echo -n "  Waiting for backend "
READY=""
for i in $(seq 1 "$BACKEND_READY_TIMEOUT"); do
  if curl -sf -m 2 "http://127.0.0.1:${BACKEND_PORT}/openapi.json" >/dev/null 2>&1; then
    READY=1
    echo "✓ (pid $BACKEND_PID)"
    break
  fi
  # Backend process already died (usually a key / config problem) → print the log and exit
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "✗ backend process exited"
    echo "──── tail of $BACKEND_LOG ────"
    tail -25 "$BACKEND_LOG"
    exit 1
  fi
  echo -n "."
  sleep 1
done
if [ -z "$READY" ]; then
  echo "✗ not ready within ${BACKEND_READY_TIMEOUT}s — see $BACKEND_LOG"
  tail -25 "$BACKEND_LOG"
  kill "$BACKEND_PID" 2>/dev/null
  exit 1
fi

# dev --app uses the live backend and skips the frozen sidecar at runtime (lib.rs:
# FINROBOT_DEV_LIVE_BACKEND). But at compile time — dev included — tauri-build copies the sidecar
# declared in tauri.conf.json bundle.resources (sidecar/dist/finrobot-server), and compilation fails
# if that path does not exist. A fresh tree has no such ~330MB PyInstaller artifact (it is only
# needed for packaging, is produced by src-tauri/sidecar/build.sh, and is not in git). dev should not
# have to freeze one just to compile, so we drop in a placeholder that is never executed in dev
# (the env var already skips the spawn), purely to satisfy the compile-time resource check. If it
# does get executed (misuse / forgetting the env var), it errors with guidance instead of failing
# silently.
ensure_dev_sidecar_placeholder() {
  local bundle_dir="$FRONTEND_DIR/src-tauri/sidecar/dist/finrobot-server"
  [ -e "$bundle_dir" ] && return 0   # real frozen artifact or an existing placeholder → leave it alone
  echo "▸ No frozen sidecar found; installing a dev placeholder (not executed in live-backend mode; for packaging, run src-tauri/sidecar/build.sh first)"
  mkdir -p "$bundle_dir"
  cat > "$bundle_dir/finrobot-server" <<'STUB'
#!/usr/bin/env bash
echo "[finrobot-server] dev placeholder sidecar — this should not be executed." >&2
echo "  dev:       ./dev.sh --app sets FINROBOT_DEV_LIVE_BACKEND=1 to skip this sidecar and use the live backend." >&2
echo "  packaging: run desktop/src-tauri/sidecar/build.sh first to produce the real PyInstaller-frozen backend." >&2
exit 1
STUB
  chmod +x "$bundle_dir/finrobot-server"
}

# ── Start the live frontend (foreground; Ctrl+C triggers cleanup to stop the backend) ─
if [ "$FRONTEND_MODE" = app ]; then
  echo "▸ Starting the desktop app (Tauri window, vite :${FRONTEND_PORT} + live backend :${BACKEND_PORT})"
  echo "  The first run compiles the Rust shell and takes a few minutes; after that it opens instantly"
  echo "  (Ctrl+C stops the app / vite / backend together)"
  echo
  ensure_dev_sidecar_placeholder
  # FINROBOT_DEV_LIVE_BACKEND=1 → the Tauri shell skips the frozen sidecar and the window connects
  # to the live backend above. cargo tauri dev starts vite itself via beforeDevCommand
  # (npm run dev, cwd=desktop/) and opens the window.
  (cd "$FRONTEND_DIR" && FINROBOT_DEV_LIVE_BACKEND=1 cargo tauri dev)
else
  echo "▸ Starting the live frontend (vite, :${FRONTEND_PORT})"
  echo "  Open in your browser → http://localhost:${FRONTEND_PORT}"
  echo "  (Ctrl+C stops the frontend and backend together)"
  echo
  cd "$FRONTEND_DIR" && npm run dev
fi
