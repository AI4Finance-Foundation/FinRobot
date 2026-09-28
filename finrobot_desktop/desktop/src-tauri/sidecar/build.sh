#!/usr/bin/env bash
# Thin wrapper → build_sidecar.py (the cross-platform freeze logic; one source
# of truth, runs on macOS/Linux/Windows). Kept so `sidecar/build.sh` and
# release.sh keep working on macOS/Linux unchanged; on Windows invoke
# build_sidecar.py directly (`python build_sidecar.py`). See that script for the
# full rationale (one-dir bundle, symlink dereference, etc.).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # desktop/src-tauri/sidecar
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"              # repo root

# Prefer the project venv's interpreter (matches the old script's pyinstaller
# resolution); fall back to whatever `python3` is on PATH.
PYTHON="$REPO_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

exec "$PYTHON" "$SCRIPT_DIR/build_sidecar.py" "$@"
