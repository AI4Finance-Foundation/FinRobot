"""Deterministic reference scan for a code symbol — no LSP warmth race.

Why this exists: pyright-as-LSP's findReferences only walks files already
loaded into its program, so a query during cold start silently returns a
partial subset (e.g. 2 refs instead of 100) with no error. This tool uses
rope as a batch indexer: it either returns the complete static reference set
or fails — never a silent partial. Verified to match warm-pyright exactly
(calculate_dcf -> 100 occ / 18 files; create_dcf_pipeline -> 14 occ / 3 files).

Two legs, because no single tool is complete:
  STATIC  — rope find_occurrences: complete + precise (distinguishes same-named
            symbols; excludes name-collision locals that grep would falsely
            include). This is the trustworthy reference set.
  REVIEW  — `grep - rope` delta: bare-name hits rope cannot see. This surfaces
            the dynamic/string/cross-language edges static analysis is blind to
            (e.g. a pipeline reached only via importlib string + getattr), mixed
            with noise (comments, same-name locals). Every line here needs a
            human eye — that is the point.

Usage:
    python scripts/find_refs.py <symbol> [--def-file path/to/def.py]

If --def-file is omitted, the tool locates the unique `def <symbol>` /
`class <symbol>` site itself and errors if there is more than one.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from rope.base.project import Project
from rope.contrib.findit import find_occurrences

ROOT = Path(__file__).resolve().parent.parent
# Directories rope must not crawl (speed) and grep must not scan (noise).
IGNORED = [
    ".venv",
    "node_modules",
    ".git",
    "desktop/node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
]
# Where a definition might live, and where references might appear.
GREP_GLOBS = ["*.py", "*.ts", "*.tsx", "*.md", "*.json", "*.toml"]
GREP_ROOTS = ["finrobot", "tests", "scripts", "desktop/src"]


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_def_site(symbol: str) -> str:
    """Return the single repo-relative file that defines `symbol`, or exit."""
    literal = re.escape(symbol)
    out = subprocess.run(
        ["grep", "-rlE", rf"^\s*(def|class)\s+{literal}\b", "--include=*.py", *GREP_ROOTS],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()
    if not out:
        sys.exit(f"error: no `def {symbol}` / `class {symbol}` found in {GREP_ROOTS}")
    if len(out) > 1:
        sys.exit(
            f"error: {symbol} is defined in {len(out)} files; pass --def-file:\n  "
            + "\n  ".join(out)
        )
    return out[0]


def _rope_occurrences(symbol: str, def_file: str) -> list[tuple[str, int, bool]]:
    proj = Project(str(ROOT), ignored_resources=IGNORED)
    try:
        res = proj.get_resource(def_file)
        src = res.read()
        marker = f"def {symbol}" if f"def {symbol}" in src else f"class {symbol}"
        offset = src.index(marker) + len(marker) - len(symbol)
        occs = find_occurrences(proj, res, offset, unsure=True)
        rows = [(o.resource.path, _line_of(o.resource.read(), o.offset), o.unsure) for o in occs]
    finally:
        proj.close()
    return sorted(set(rows))


def _grep_hits(symbol: str) -> set[tuple[str, int]]:
    includes = [f"--include={g}" for g in GREP_GLOBS]
    excludes = [f"--exclude-dir={d.split('/')[-1]}" for d in IGNORED]
    out = subprocess.run(
        ["grep", "-rwnF", symbol, *includes, *excludes, *GREP_ROOTS],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    hits: set[tuple[str, int]] = set()
    for line in out:
        parts = line.split(":", 2)
        if len(parts) >= 2 and parts[1].isdigit():
            hits.add((parts[0], int(parts[1])))
    return hits


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic reference scan (rope + grep delta).")
    ap.add_argument("symbol")
    ap.add_argument(
        "--def-file", help="repo-relative file defining the symbol (auto-detected if unique)"
    )
    args = ap.parse_args()

    def_file = args.def_file or _find_def_site(args.symbol)
    static = _rope_occurrences(args.symbol, def_file)
    static_keys = {(p, ln) for p, ln, _ in static}
    delta = sorted(_grep_hits(args.symbol) - static_keys)

    files = sorted({p for p, _, _ in static})
    print(f"\n=== STATIC (rope, trustworthy complete) — {args.symbol} ===")
    print(f"    {len(static)} occurrences across {len(files)} files\n")
    for path, ln, unsure in static:
        print(f"  {path}:{ln}{'  [UNSURE]' if unsure else ''}")

    print(f"\n=== REVIEW (grep − rope) — {len(delta)} lines static analysis cannot see ===")
    print(
        "    dynamic/string/cross-lang edges + noise (comments, same-name locals) — eyeball each\n"
    )
    for path, ln in delta:
        print(f"  {path}:{ln}")
    if not delta:
        print("  (none)")
    print()


if __name__ == "__main__":
    main()
