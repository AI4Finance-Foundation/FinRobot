#!/usr/bin/env python3
"""Harness-drift sentinel.

The AI coding harness (root CLAUDE.md ≡ AGENTS.md + the finagent-* sub-agents in
.claude/agents/ and their .codex/agents/ mirrors) hard-codes file paths and
references. When the codebase moves, those references silently rot: a grep against
a renamed directory emits a warning and returns nothing, so an agent pastes
"no findings" and the red-line scan is dead. This script makes that rot loud.

Checks:
  1. No agent/instruction file references the non-existent `finagent/` package
     (the real package is `finrobot/`).
  2. Every fully-qualified path token (finrobot/ specs/ docs/ project-memory/
     tests/ ui/ src-tauri/) referenced in the harness actually exists on disk.
  3. Every .claude/agents/<name>.md has a .codex/agents/<name>.toml mirror, and
     vice versa.
  4. CLAUDE.md and AGENTS.md are byte-identical.

Exit 0 if clean, 1 if any drift. No third-party deps; runs anywhere.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HARNESS_FILES = [
    *sorted((ROOT / ".claude/agents").glob("*.md")),
    *sorted((ROOT / ".codex/agents").glob("*.toml")),
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
]

# Roots whose fully-qualified references we verify exist on disk.
PATH_ROOTS = ("finrobot/", "specs/", "docs/", "project-memory/", "tests/", "ui/", "src-tauri/")
# A path token = one of the roots followed by path chars (incl. CJK for 中文 filenames),
# stopping at whitespace, quotes, backticks, parens (half/full width) and template <...>.
TOKEN_RE = re.compile(
    r"(?:" + "|".join(re.escape(r) for r in PATH_ROOTS) + r")"
    r"[^\s`'\"，。、；：！？（）()<>|\[\]]+"
)


def candidate_paths(token: str) -> list[str]:
    """Expand a raw token into concrete paths to existence-check.

    - drop trailing punctuation/slashes
    - {a,b,c} brace groups -> one path per alternative
    - a `*` wildcard segment -> check the parent directory instead
    - skip template placeholders containing `<`
    """
    token = token.rstrip("/.,:;")
    if "<" in token or "*" in token.split("/")[0]:
        return []
    # brace expansion (single group, which is all the harness uses)
    m = re.search(r"\{([^}]*)\}", token)
    if m:
        alts = [a.strip() for a in m.group(1).split(",") if a.strip()]
        return [p for a in alts for p in candidate_paths(token[: m.start()] + a + token[m.end():])]
    if "*" in token:  # wildcard -> verify the directory that should contain the matches
        head = token[: token.index("*")]
        token = head.rsplit("/", 1)[0] if "/" in head else head
    return [token] if token else []


def main() -> int:
    violations: list[str] = []

    for f in HARNESS_FILES:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(ROOT)

        for ln, line in enumerate(text.splitlines(), 1):
            if "finagent/" in line:
                violations.append(f"{rel}:{ln}: references non-existent `finagent/` (package is `finrobot/`)")

        seen: set[str] = set()
        for raw in TOKEN_RE.findall(text):
            for cand in candidate_paths(raw):
                if cand in seen:
                    continue
                seen.add(cand)
                if not (ROOT / cand).exists():
                    violations.append(f"{rel}: references missing path `{cand}` (from token `{raw}`)")

    # .md <-> .toml mirror parity
    md = {p.stem for p in (ROOT / ".claude/agents").glob("*.md")}
    toml = {p.stem for p in (ROOT / ".codex/agents").glob("*.toml")}
    for name in sorted(md - toml):
        violations.append(f".claude/agents/{name}.md has no .codex/agents/{name}.toml mirror")
    for name in sorted(toml - md):
        violations.append(f".codex/agents/{name}.toml has no .claude/agents/{name}.md mirror")

    # CLAUDE.md == AGENTS.md
    claude, agents = ROOT / "CLAUDE.md", ROOT / "AGENTS.md"
    if claude.exists() and agents.exists():
        if claude.read_bytes() != agents.read_bytes():
            violations.append("CLAUDE.md and AGENTS.md are not byte-identical (mirror drift)")

    if violations:
        print("HARNESS DRIFT — the AI coding harness references reality that no longer exists:\n")
        for v in violations:
            print(f"  ✗ {v}")
        print(f"\n{len(violations)} issue(s). Fix the reference (or restore the path) before committing.")
        return 1

    present = sum(1 for f in HARNESS_FILES if f.exists())
    if present == 0:
        print("harness drift check: no local harness files present (gitignored / fresh checkout) — nothing to validate")
        return 0
    print(f"harness drift check: OK ({present} files, all referenced paths exist)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
