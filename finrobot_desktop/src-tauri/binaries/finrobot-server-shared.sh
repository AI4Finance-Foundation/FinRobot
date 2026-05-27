#!/usr/bin/env bash
# Tauri sidecar wrapper for the FinRobot Python FastAPI server.
#
# Phase 4b: assumes `uv` is on PATH. The wrapper resolves the project root
# relative to this script's location and delegates to uv run.
#
# Phase 4c (planned): replace with a bundled Python interpreter so the
# .app is self-contained and works without uv on PATH.
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

# --reload is dev-only behavior: this script is the Phase 4b implementation
# that delegates to uv. Phase 4c bundled interpreter will replace this whole
# script, at which point reload becomes inappropriate. Until then, every
# `cargo tauri dev` run is a dev run, so reload by default — saves restarting
# the desktop app after every Python edit.
exec uv run finrobot serve --reload "$@"
