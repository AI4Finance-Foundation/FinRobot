#!/usr/bin/env bash
# Freeze `finrobot serve` into the standalone Tauri sidecar binary.
#
# Output: src-tauri/binaries/finrobot-server-<target-triple> — the name Tauri's
# externalBin matcher expects (e.g. finrobot-server-aarch64-apple-darwin).
#
# Prereq: the `package` extra is installed (`uv sync --extra package`), which
# pulls in pyinstaller. Run from anywhere; paths are resolved absolutely.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # src-tauri/sidecar
SRC_TAURI="$(cd "$SCRIPT_DIR/.." && pwd)"                       # src-tauri
REPO_ROOT="$(cd "$SRC_TAURI/.." && pwd)"                        # repo root
BINARIES_DIR="$SRC_TAURI/binaries"
SPEC="$SCRIPT_DIR/finrobot-server.spec"

# Tauri names sidecars by the Rust *host* target triple. Derive it from rustc
# so the output matches whatever platform we're building on.
if ! command -v rustc &>/dev/null; then
    echo >&2 "[build-sidecar] ERROR: rustc not found — needed to resolve the target triple."
    exit 1
fi
TRIPLE="$(rustc -Vv | sed -n 's/^host: //p')"
if [[ -z "$TRIPLE" ]]; then
    echo >&2 "[build-sidecar] ERROR: could not parse host triple from rustc."
    exit 1
fi

# Prefer the project venv's pyinstaller; fall back to `uv run`.
if [[ -x "$REPO_ROOT/.venv/bin/pyinstaller" ]]; then
    PYINSTALLER=("$REPO_ROOT/.venv/bin/pyinstaller")
else
    PYINSTALLER=(uv run --extra package pyinstaller)
fi

echo "[build-sidecar] target triple: $TRIPLE"
echo "[build-sidecar] running PyInstaller…"

cd "$REPO_ROOT"
"${PYINSTALLER[@]}" \
    --noconfirm \
    --clean \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    "$SPEC"

SRC_BIN="$SCRIPT_DIR/dist/finrobot-server"
if [[ ! -f "$SRC_BIN" ]]; then
    echo >&2 "[build-sidecar] ERROR: expected binary not found at $SRC_BIN"
    exit 1
fi

mkdir -p "$BINARIES_DIR"
DEST_BIN="$BINARIES_DIR/finrobot-server-$TRIPLE"
# rm first: if DEST_BIN is a symlink (legacy dev shim), a bare cp would follow
# it and overwrite the link *target* instead of replacing the link itself.
rm -f "$DEST_BIN"
cp "$SRC_BIN" "$DEST_BIN"
chmod +x "$DEST_BIN"

echo "[build-sidecar] done -> $DEST_BIN"
ls -lh "$DEST_BIN"
