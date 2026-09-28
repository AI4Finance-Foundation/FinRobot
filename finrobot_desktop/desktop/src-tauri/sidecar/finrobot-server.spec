# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the FinRobot desktop sidecar.

Produces a one-dir ``finrobot-server`` bundle (exe + ``_internal/``) with a
Python interpreter, every finrobot dependency, and the read-only ``skills/``
corpus. Tauri ships the whole directory as a bundle resource and spawns the
exe as the backend; no Python install, no ``uv``, no source tree required on
the target machine.

One-dir, NOT one-file: the one-file bootloader re-extracts ~330 MB / 4200
files to a temp dir on every launch, which measured 47-88 s before Python even
started (macOS scans each fresh dylib). One-dir skips extraction entirely —
Python itself boots in ~1 s.

Build via ``desktop/src-tauri/sidecar/build.sh`` — do not call pyinstaller by
hand, the script wires up the repo root and the dist layout Tauri bundles.
"""

import os

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# SPECPATH is injected by PyInstaller: .../desktop/src-tauri/sidecar
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", "..", ".."))

# --- bundled read-only resources -------------------------------------------
# skills/ drives the research pipeline (equity-research, financial-analysis,
# …). Resolved at runtime via finrobot.paths.bundle_resource_root() -> _MEIPASS.
datas = [(os.path.join(REPO_ROOT, "skills"), "skills")]

# Non-.py data files shipped *inside* the finrobot package and read at runtime
# via Path(__file__).parent / ... — agent instructions
# (engine/agents/instructions/*_agent.md) and industry datasets
# (engine/data/datasets/*). collect_submodules only grabs .py modules, so these
# must be collected separately or create_sub_agents crashes on read_text().
datas += collect_data_files("finrobot")

# --- dynamic imports PyInstaller's static graph cannot see ------------------
hiddenimports = []
binaries_extra = []

# finrobot itself uses function-level imports pervasively (cli.py, server.py
# lazy-import routes/providers); pull in every submodule so none is dropped.
hiddenimports += collect_submodules("finrobot")

# pydantic-ai resolves provider/model classes lazily inside config.create_model
# (deepseek/anthropic/openai). keyring resolves its OS backend at runtime.
# uvicorn picks its event loop + HTTP protocol implementation dynamically.
hiddenimports += collect_submodules("pydantic_ai")
hiddenimports += collect_submodules("keyring")
hiddenimports += collect_submodules("uvicorn")

# The 13F background refresh imports this module from the (non-package) scripts/
# dir; it has no __init__.py, so name it explicitly and add REPO_ROOT to pathex.
hiddenimports += ["scripts.refresh_sec_holdings"]

# Packages that read their own version via importlib.metadata at *import* time
# (pydantic_ai/__init__ -> version("pydantic_ai_slim"); genai_prices/__init__ ->
# version("genai_prices")). Without the bundled .dist-info this raises
# PackageNotFoundError and the whole import chain dies. copy_metadata ships it.
for _dist in ("genai_prices", "pydantic_ai_slim"):
    datas += copy_metadata(_dist)

# genai_prices loads a bundled price dataset at runtime; edgartools ships
# reference data + lazy submodules. collect_all grabs data + dynamic libs +
# hidden submodules for each.
for _pkg in ("edgar", "genai_prices"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries_extra += _b
    hiddenimports += _h

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[REPO_ROOT],
    binaries=binaries_extra,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trim heavy deps the server never imports at runtime (verified: no
    # `import matplotlib` anywhere in finrobot/). tkinter/test tooling are
    # pulled in transitively but unused by a headless FastAPI server.
    excludes=["matplotlib", "tkinter", "IPython", "pytest", "notebook"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="finrobot-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="finrobot-server",
)
