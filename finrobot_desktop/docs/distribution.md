# Distribution Feasibility Research

> Research document covering packaging options for FinAgent CLI and Desktop app.
> This is a research artifact, not a spec. No code changes are implied.

---

## 1. PyInstaller Feasibility

### Overview

PyInstaller bundles a Python application and its dependencies into a single
directory (or single executable) by analyzing imports, collecting `.so`/`.pyd`
files, and embedding a minimal Python interpreter.

### Hidden Import Challenges

FinAgent's dependency tree includes several packages that rely on dynamic or
lazy imports, which PyInstaller's static analysis cannot discover automatically:

| Package | Dynamic Import Issue | PyInstaller Workaround |
|---------|---------------------|----------------------|
| **pydantic-ai** | Plugin-style model provider loading (`anthropic`, `openai`, `groq`, etc.) resolved at runtime via `importlib`. PyInstaller's static tracer misses these entirely. | `--hidden-import=pydantic_ai.models.anthropic` etc. Must be enumerated manually for every supported provider. |
| **pydantic / pydantic-core** | Rust-compiled `pydantic_core` `.so` with platform-specific binary. Usually collected correctly, but version mismatches between PyInstaller hooks and pydantic releases have caused repeated breakage (see pyinstaller/pyinstaller-hooks-contrib). | Use latest `pyinstaller-hooks-contrib`. Pin pydantic version in lockfile. |
| **httpx / httpcore / h2** | httpx uses `anyio` which conditionally imports `trio` or `asyncio` backends. h2 (HTTP/2) has optional C extensions. | `--hidden-import=httpcore._backends.anyio` and `--collect-submodules=httpx`. |
| **aiosqlite** | Spawns a worker thread that imports `sqlite3` — generally fine, but the thread's event loop interaction has caused issues in frozen environments where `sys.executable` points to the PyInstaller bootloader. | Usually works. Test thoroughly on all target platforms. |
| **numpy** (transitive via yfinance/matplotlib) | Large binary with BLAS/LAPACK shared libraries. PyInstaller must collect the correct platform-specific `.so` files. Known to fail on Apple Silicon with MKL builds. | Use `--collect-all=numpy`. Expect 50-80 MB added to bundle. |
| **openpyxl** | Pure Python, generally clean. But imports `et_xmlfile` lazily. | `--hidden-import=et_xmlfile`. |
| **matplotlib** | Backends loaded dynamically. Data files (fonts, stylesheets) must be collected. One of the most fragile packages to freeze. | `--collect-data=matplotlib --collect-submodules=matplotlib`. Adds ~30 MB. |
| **yfinance** | Uses `requests`/`curl_cffi` with optional backends. Import paths vary by version. | `--collect-submodules=yfinance`. |

### Single-File Mode (`--onefile`)

PyInstaller `--onefile` packs everything into a single executable that
self-extracts to a temp directory on launch. For FinAgent this means:

- **Cold start time**: 5-15 seconds to extract ~200+ MB of Python + numpy +
  matplotlib + pydantic before the application even begins running.
- **Disk usage**: The compressed executable is ~100-150 MB, but extraction
  doubles disk usage at runtime.
- **Anti-virus false positives**: Self-extracting executables are commonly
  flagged by Windows Defender and other AV software.

**Verdict**: `--onefile` is not viable for a desktop application that needs
responsive startup. `--onedir` (directory mode) is more practical but still
requires maintaining a fragile hook configuration.

### Overall PyInstaller Assessment

PyInstaller *can* package FinAgent, but the maintenance burden is high:

1. Every pydantic-ai version bump may require updating hidden imports.
2. numpy/matplotlib on multiple platforms (x86_64, arm64, Windows, macOS,
   Linux) requires per-platform CI testing of the frozen build.
3. The skill files (`skills/` directory) and instruction markdown files must be
   manually added as data files.
4. aiosqlite's thread + event loop pattern in frozen environments needs
   platform-specific validation.

---

## 2. electron-builder + uv Sidecar

### Overview

This is the approach already documented in `ARCHITECTURE.md`. The Electron app
does not bundle a frozen Python binary. Instead, it bundles the `uv` package
manager (a single Rust binary, ~15 MB per platform) and uses it to create and
manage a Python virtual environment on the user's machine.

### Architecture

```
desktop/
  build/
    uv-sidecar/
      uv-linux-x64        # ~15 MB
      uv-darwin-arm64      # ~15 MB
      uv-windows-x64.exe   # ~15 MB
  resources/
    pyproject.toml         # FinAgent dependency spec
    uv.lock                # Reproducible lockfile
    finagent/              # Source code (or wheel)
```

### Lifecycle

1. **Build time** (`scripts/build-electron.sh`):
   - `scripts/prepare-uv.mjs` downloads platform-specific `uv` binaries into
     `desktop/build/uv-sidecar/`.
   - electron-builder packages the Electron app with `uv-sidecar/` and
     `resources/` as `extraResources`.

2. **First launch** (managed by `desktop/electron/main.ts`):
   - Electron detects no `.venv` in the app data directory.
   - Runs `uv sync --project <resources-path>` to create a venv from `uv.lock`.
   - Shows a loading screen during installation (~30-60 seconds).
   - On completion, proceeds to step 3.

3. **Every launch**:
   - Electron spawns `uv run --project <resources-path> finagent serve --port <port>`.
   - Waits for the FastAPI server to respond on `localhost:<port>`.
   - Opens the main window, which connects to the local server via HTTP/SSE.

4. **Updates**:
   - App update (via electron-updater) ships new `uv.lock` + source code.
   - Next launch, `uv sync` detects the changed lockfile and updates the venv.
   - No manual PyInstaller hook maintenance required.

### Per-Platform uv Binary Bundling

| Platform | uv Binary | Size | Notes |
|----------|-----------|------|-------|
| macOS arm64 | `uv-aarch64-apple-darwin` | ~15 MB | Primary dev target |
| macOS x86_64 | `uv-x86_64-apple-darwin` | ~15 MB | Intel Mac support |
| Windows x64 | `uv-x86_64-pc-windows-msvc.exe` | ~17 MB | Most common desktop target |
| Linux x64 | `uv-x86_64-unknown-linux-gnu` | ~15 MB | For Linux desktop users |

electron-builder's `extraResources` config selects the correct binary per
target platform at build time. The `prepare-uv.mjs` script downloads from
`https://github.com/astral-sh/uv/releases`.

### Dual-Process Architecture

```
                 Electron (Node.js)
                 ┌────────────────────────┐
                 │  main.ts               │
                 │  - spawns uv process   │
                 │  - manages lifecycle   │
                 │  - IPC for safeStorage │
                 └──────────┬─────────────┘
                            │ child_process.spawn()
                            │
                 ┌──────────▼─────────────┐
                 │  Python (FastAPI)       │
                 │  - finagent serve       │
                 │  - localhost:<port>     │
                 │  - SSE streaming        │
                 └──────────┬─────────────┘
                            │ HTTP / SSE
                            │
                 ┌──────────▼─────────────┐
                 │  React UI (renderer)    │
                 │  - useChat (SSE)        │
                 │  - localhost:<port>     │
                 └────────────────────────┘
```

- Electron's main process owns the Python child process lifecycle (start,
  health check, graceful shutdown on app quit).
- The renderer process communicates with Python exclusively over HTTP/SSE.
  No Electron IPC is used for data transfer.
- API keys are stored via Electron's `safeStorage` (encrypted at OS level)
  and injected as environment variables when spawning the Python process.

### Advantages Over PyInstaller

1. **No binary repackaging** -- uv installs native wheels directly from PyPI.
   numpy, matplotlib, openpyxl just work without DLL hell or hook maintenance.
2. **Reproducible via lockfile** -- `uv.lock` guarantees identical dependency
   resolution across platforms, like `cargo.lock` or `yarn.lock`.
3. **Trivial dependency upgrades** -- update `uv.lock`, ship new app version.
   No re-tuning of PyInstaller hooks.
4. **uv is cross-platform** -- single Rust binary, no runtime dependencies.
5. **Debugging** -- the Python environment is a standard venv. Users (and
   developers) can inspect, modify, and debug it with normal tools.

---

## 3. Conclusion and Recommendation

### Recommended Approach: uv Sidecar (Already Documented in ARCHITECTURE.md)

The uv sidecar approach is the recommended distribution strategy for FinAgent's
desktop application. It avoids the fragility of PyInstaller's frozen
environments while providing a clean, reproducible installation experience.

This approach is already designed and partially implemented in the project's
architecture (`desktop/electron/main.ts` lifecycle, `scripts/prepare-uv.mjs`
build script, `desktop/build/uv-sidecar/` directory structure).

### Why Not PyInstaller

PyInstaller is viable for simple Python applications but introduces
disproportionate maintenance burden for FinAgent due to:

- **pydantic-ai's dynamic model provider imports** require manually maintained
  hidden import lists that break on version bumps.
- **numpy + matplotlib** add ~100 MB to the frozen bundle and have
  platform-specific binary collection issues (especially Apple Silicon).
- **aiosqlite's worker thread pattern** in frozen environments has edge cases
  that are difficult to test comprehensively.
- **Skill files and markdown instructions** must be manually managed as
  PyInstaller data files rather than naturally living in the filesystem.

PyInstaller remains a fallback option for CLI-only distribution (no Electron)
if a user specifically needs a single standalone binary, but it is not the
primary distribution strategy.

### Caveats

1. **First-launch internet requirement**: `uv sync` downloads Python packages
   from PyPI on first launch. Users behind corporate firewalls or on air-gapped
   machines will not be able to complete setup without network access.

2. **Offline wheel cache option**: For offline installations, pre-download
   wheels into `resources/wheels/` and configure
   `uv sync --offline --find-links ./wheels/`. This adds ~150-200 MB to the
   installer but removes the network requirement. This should be offered as an
   alternative download (e.g., "FinAgent Desktop (offline)" vs "FinAgent
   Desktop (standard)").

3. **Python version management**: uv can install Python itself if not present
   on the system. The `pyproject.toml` `requires-python = ">=3.11"` constraint
   guides uv to select an appropriate version. This mostly just works, but
   should be tested on clean OS installs.

4. **Installer size**: The base Electron app + uv binary is ~80-100 MB
   (comparable to other Electron apps). The Python venv created on first launch
   adds ~200-400 MB to disk, but this is managed by uv and can be cleaned up
   via standard uv commands.
