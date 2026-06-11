#!/usr/bin/env bash
# Freeze `finrobot serve` into the standalone Tauri sidecar bundle.
#
# Output: desktop/src-tauri/sidecar/dist/finrobot-server/ — a PyInstaller
# one-dir bundle (exe + _internal/). tauri.conf.json ships this directory as a
# bundle resource ("resources"), and sidecar.rs spawns the exe from
# Contents/Resources/finrobot-server/. One-dir (not one-file) because the
# one-file bootloader re-extracts ~330 MB on every launch → 47-88 s cold start.
#
# Prereq: the `package` extra is installed (`uv sync --extra package`), which
# pulls in pyinstaller. Run from anywhere; paths are resolved absolutely.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # desktop/src-tauri/sidecar
SRC_TAURI="$(cd "$SCRIPT_DIR/.." && pwd)"                       # desktop/src-tauri
DESKTOP_DIR="$(cd "$SRC_TAURI/.." && pwd)"                      # desktop
REPO_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"                      # repo root
SPEC="$SCRIPT_DIR/finrobot-server.spec"

# Prefer the project venv's pyinstaller; fall back to `uv run`.
if [[ -x "$REPO_ROOT/.venv/bin/pyinstaller" ]]; then
    PYINSTALLER=("$REPO_ROOT/.venv/bin/pyinstaller")
else
    PYINSTALLER=(uv run --extra package pyinstaller)
fi

echo "[build-sidecar] running PyInstaller…"

cd "$REPO_ROOT"
"${PYINSTALLER[@]}" \
    --noconfirm \
    --clean \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    "$SPEC"

DIST_DIR="$SCRIPT_DIR/dist/finrobot-server"
DIST_EXE="$DIST_DIR/finrobot-server"
if [[ ! -x "$DIST_EXE" ]]; then
    echo >&2 "[build-sidecar] ERROR: expected one-dir exe not found at $DIST_EXE"
    exit 1
fi

# PyInstaller emits ~37 symlinks (dylib aliases + the Python.framework
# Current/Resources layout). Tauri's resource walker fails on them at build
# time ("Not a directory"), so ship a fully dereferenced copy — a few MB of
# duplication for a symlink-free bundle that every copier downstream
# (tauri-build dev copy, bundler, updater tar) handles identically.
DEREF_DIR="$SCRIPT_DIR/dist/.finrobot-server-deref"
rm -rf "$DEREF_DIR"
cp -RL "$DIST_DIR" "$DEREF_DIR"
rm -rf "$DIST_DIR"
mv "$DEREF_DIR" "$DIST_DIR"
if find "$DIST_DIR" -type l | grep -q .; then
    echo >&2 "[build-sidecar] ERROR: symlinks remain after dereference"
    exit 1
fi

# Legacy one-file layout: a stale triple-named binary here would silently win
# over the fresh one-dir bundle in old configs; remove the whole dir.
rm -rf "$SRC_TAURI/binaries"

echo "[build-sidecar] done -> $DIST_DIR"
du -sh "$DIST_DIR"
