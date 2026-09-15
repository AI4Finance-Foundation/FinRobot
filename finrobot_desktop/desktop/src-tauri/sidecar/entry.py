"""PyInstaller entry point for the FinRobot desktop sidecar.

The Tauri shell spawns this frozen binary with ``--host 127.0.0.1 --port 8321``
(see desktop/src-tauri/src/sidecar.rs). We inject the ``serve`` subcommand and hand off
to the existing Click CLI, so the bundled server runs the byte-for-byte same
code path as ``finrobot serve`` does in development — no parallel entrypoint to
drift out of sync.
"""

from __future__ import annotations

import multiprocessing
import os
import sys

# Disable pydantic plugins BEFORE pydantic/pydantic-ai is imported anywhere.
# logfire (a transitive dep of pydantic-ai) registers a pydantic plugin whose
# import-time patch calls inspect.getsource() — which raises OSError("could not
# get source code") inside a frozen PyInstaller binary, because the bundle ships
# bytecode, not .py source. We don't use logfire instrumentation, so disabling
# all pydantic plugins is both the fix and a small startup win. Set as a module
# side effect (not in main()) so it lands before the first transitive import.
os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")


def main() -> None:
    # PyInstaller + any library that uses multiprocessing (uvicorn workers,
    # some yfinance paths) needs this guard so the frozen binary does not
    # re-exec itself as a runaway fork bomb when a child process starts.
    multiprocessing.freeze_support()

    from finrobot.cli import cli

    # Prepend the `serve` subcommand; everything Tauri passes (--host/--port)
    # flows through unchanged as serve options.
    sys.argv = [sys.argv[0], "serve", *sys.argv[1:]]
    cli()


if __name__ == "__main__":
    main()
