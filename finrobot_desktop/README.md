# FinRobot Desktop

> Investment-bank-grade equity research, in a desktop app — deterministic finance numbers + LLM narrative, every figure traceable back to a function call.

FinRobot 是面向金融分析师 / 量化研究员 / 主动投资者的开源桌面端股票研究 app。一份 `research` pipeline 一键产出 13 章 artifact：Cover · Investment Thesis · Company Overview · Financial Analysis · Valuation · Recent News · Sensitivity · Catalysts · Technical & Advanced · Competitive Landscape · Financial Data · Ownership & Governance · Disclaimer。

**核心赌注：数字由代码算出，判断由 LLM 给出。** LLM 永远不产出无法追溯到 `engine/compute/*` 函数调用的数字。

## How it works

The app ships as a single `.app` containing two binaries that talk over local HTTP:

- **`finrobot-desktop`** — the Tauri shell: native window, menu bar, and the React UI.
- **`finrobot-server`** — a self-contained Python backend (FastAPI + PydanticAI + the deterministic compute engine), launched automatically in the background on `127.0.0.1:8321`.

You never start anything by hand. Opening the app boots the backend; quitting it shuts the backend down. No Python, no `uv`, no source tree required on the user's machine.

## Install (macOS, Apple Silicon)

1. Download `FinRobot_<version>_aarch64.dmg` from the [Releases](../../releases) page (or build it yourself — see below).
2. Open the `.dmg` and drag **FinRobot** into `Applications`.
3. **First open** — the app is not yet code-signed, so Gatekeeper will block a plain double-click. Either right-click the app → **Open** → **Open**, or clear the quarantine flag once:
   ```bash
   xattr -dr com.apple.quarantine /Applications/FinRobot.app
   ```
4. **First run** — open **Settings** and paste your own LLM API key (DeepSeek / OpenAI / Anthropic). FinRobot orchestrates *your* LLM account; it does not ship a key. Until a key is set, the app opens fine but analysis requests return a "configure your API key" notice instead of running.

Running an analysis needs internet (market data from yfinance / SEC EDGAR / optional FMP, plus your LLM provider). Launching and browsing existing reports does not.

## Build from source

Prerequisites: [`uv`](https://docs.astral.sh/uv/), Node 20+, Rust toolchain, and the Tauri CLI (`cargo install tauri-cli` → `cargo tauri`).

```bash
uv sync --extra package            # backend deps + pyinstaller (for the sidecar)
bash src-tauri/sidecar/build.sh    # freeze finrobot-server into src-tauri/binaries/

cargo tauri dev                    # run the desktop app (debug)
cargo tauri build                  # produce FinRobot.app + .dmg under src-tauri/target/release/bundle/
```

`build.sh` must be re-run whenever the Python backend changes, so the bundled sidecar reflects your edits. For a fast backend edit loop, run the server directly with hot-reload instead:

```bash
finrobot serve --reload            # live-reloading backend on :8321
```

CLI usage, the Python SDK, and the engine architecture / contracts are documented in the in-repo `CLAUDE.md` (developer reference).

## License

Apache 2.0
