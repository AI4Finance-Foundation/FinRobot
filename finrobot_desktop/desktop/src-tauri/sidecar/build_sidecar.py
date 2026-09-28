#!/usr/bin/env python3
"""Freeze `finrobot serve` into the standalone Tauri sidecar bundle.

Cross-platform replacement for the old bash-only ``build.sh``: runs on macOS,
Windows, and Linux from one source of truth. Output:
``desktop/src-tauri/sidecar/dist/finrobot-server/`` — a PyInstaller one-dir
bundle (launcher + ``_internal/``). ``tauri.conf.json`` ships the whole
directory as a bundle resource (dest dir ``sidecar/``) and ``sidecar.rs`` spawns
the launcher from it: ``finrobot-server`` on macOS/Linux, ``finrobot-server.exe``
on Windows (PyInstaller appends ``.exe`` from the same spec — no spec change).

One-dir, NOT one-file: the one-file bootloader re-extracts ~330 MB / 4200 files
on every launch (47-88 s cold start before Python even starts). One-dir skips
extraction — Python boots in ~1 s.

Prereq: the ``package`` extra is installed (``uv sync --extra package``), which
pulls in pyinstaller. Run from anywhere; paths resolve absolutely.

Usage (any OS):
    python desktop/src-tauri/sidecar/build_sidecar.py
On macOS/Linux ``build.sh`` is a thin wrapper around this script.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent  # desktop/src-tauri/sidecar
SRC_TAURI = SCRIPT_DIR.parent  # desktop/src-tauri
DESKTOP_DIR = SRC_TAURI.parent  # desktop
REPO_ROOT = DESKTOP_DIR.parent  # repo root
SPEC = SCRIPT_DIR / "finrobot-server.spec"

# PyInstaller appends `.exe` to the COLLECT launcher on Windows only; macOS and
# Linux leave it bare. sidecar.rs resolves the matching name per-OS.
EXE_NAME = "finrobot-server.exe" if os.name == "nt" else "finrobot-server"


def _pyinstaller_cmd() -> list[str]:
    """Prefer the project venv's pyinstaller; fall back to ``uv run``."""
    venv_bin = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    exe = venv_bin / ("pyinstaller.exe" if os.name == "nt" else "pyinstaller")
    if exe.is_file():
        return [str(exe)]
    return ["uv", "run", "--extra", "package", "pyinstaller"]


def _dereference_symlinks(dist_dir: Path) -> None:
    """macOS-only: replace the symlink-laden bundle with a dereferenced copy.

    PyInstaller emits ~37 symlinks on macOS (dylib aliases + the
    Python.framework ``Current``/``Resources`` layout). Tauri's resource walker
    fails on them at build time ("Not a directory"), so ship a fully
    dereferenced copy — a few MB of duplication for a symlink-free bundle every
    downstream copier (tauri-build dev copy, bundler, updater tar) handles
    identically. Mirrors the proven ``cp -RL`` from the old build.sh exactly
    (rather than ``shutil.copytree``, which can recurse on framework symlink
    chains); this path only ever runs on macOS. Windows/Linux one-dir bundles
    have no such symlinks, so the caller skips this entirely.
    """
    deref = dist_dir.parent / ".finrobot-server-deref"
    if deref.exists():
        shutil.rmtree(deref)
    subprocess.run(["cp", "-RL", str(dist_dir), str(deref)], check=True)
    shutil.rmtree(dist_dir)
    deref.rename(dist_dir)
    remaining = [p for p in dist_dir.rglob("*") if p.is_symlink()]
    if remaining:
        print(
            f"[build-sidecar] ERROR: {len(remaining)} symlinks remain after dereference",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> int:
    dist_root = SCRIPT_DIR / "dist"
    work_root = SCRIPT_DIR / "build"
    dist_dir = dist_root / "finrobot-server"

    print("[build-sidecar] running PyInstaller…")
    subprocess.run(
        [
            *_pyinstaller_cmd(),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_root),
            "--workpath",
            str(work_root),
            str(SPEC),
        ],
        cwd=str(REPO_ROOT),
        check=True,
    )

    dist_exe = dist_dir / EXE_NAME
    if not dist_exe.is_file():
        print(
            f"[build-sidecar] ERROR: expected one-dir launcher not found at {dist_exe}",
            file=sys.stderr,
        )
        return 1

    if sys.platform == "darwin":
        _dereference_symlinks(dist_dir)

    # Legacy one-file layout: a stale triple-named binary here would silently
    # win over the fresh one-dir bundle in old configs; remove the whole dir.
    shutil.rmtree(SRC_TAURI / "binaries", ignore_errors=True)

    print(f"[build-sidecar] done -> {dist_dir}")
    size = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file())
    print(f"[build-sidecar] bundle size: {size / 1024 / 1024:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
