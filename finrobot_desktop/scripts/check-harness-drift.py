#!/usr/bin/env python3
"""Harness-drift sentinel.

The AI coding harness (root CLAUDE.md ≡ AGENTS.md, hook configs in
.claude/settings.json + .claude/hooks/*.sh + .codex/hooks.json, and any agent
files under .claude/agents/ with .codex/agents/ mirrors) hard-codes file paths
and references. When the codebase moves, those references silently rot: a grep
against a renamed directory emits a warning and returns nothing, so an agent
pastes "no findings" and the red-line scan is dead. This script makes that rot
loud.

Checks:
  1. No harness or active knowledge file references legacy live-code roots
     such as `finagent/` or `ui/src/`
     (the real package is `finrobot/`).
  2. Every fully-qualified path token (finrobot/ specs/ docs/ project-memory/
     tests/ desktop/ scripts/) referenced in the harness actually exists on disk.
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
    *sorted((ROOT / ".claude/hooks").glob("*.sh")),
    ROOT / ".claude/settings.json",
    ROOT / ".codex/hooks.json",
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
]

KNOWLEDGE_ROOTS = ("project-memory", "docs", "specs")
KNOWLEDGE_EXCLUDE_PARTS = {
    "project-memory/飞轮/快照",
    "project-memory/飞轮/变更日志.md",
    "project-memory/飞轮/复发台账.md",
    "specs/research/归档",
}
LEGACY_LIVE_ROOTS = {
    "finagent/": "finrobot/",
    "ui/src/": "desktop/src/",
}

# Roots whose fully-qualified references we verify exist on disk.
PATH_ROOTS = (
    "finrobot/",
    "specs/",
    "docs/",
    "project-memory/",
    "tests/",
    "desktop/",
    "scripts/",
)
# A path token = one of the roots followed by path chars (incl. CJK for 中文 filenames),
# stopping at whitespace, quotes, backticks, parens (half/full width), template <...>,
# and prose punctuation in both widths (, ; : ! ? em-dash interpunct ellipsis) — repo
# filenames never contain these, but hook/instruction prose right after a path does.
TOKEN_RE = re.compile(
    r"(?:" + "|".join(re.escape(r) for r in PATH_ROOTS) + r")"
    r"[^\s`'\"\\，。、；：！？（）()<>|\[\],;:!?—·…]+"
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
        return [p for a in alts for p in candidate_paths(token[: m.start()] + a + token[m.end() :])]
    if "*" in token:  # wildcard -> verify the directory that should contain the matches
        head = token[: token.index("*")]
        token = head.rsplit("/", 1)[0] if "/" in head else head
    return [token] if token else []


def active_knowledge_files() -> list[Path]:
    files: list[Path] = []
    for root in KNOWLEDGE_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = path.relative_to(ROOT).as_posix()
            if any(rel == part or rel.startswith(f"{part}/") for part in KNOWLEDGE_EXCLUDE_PARTS):
                continue
            files.append(path)
    return files


def check_legacy_live_roots(files: list[Path], violations: list[str]) -> None:
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(ROOT)
        for ln, line in enumerate(text.splitlines(), 1):
            for legacy, current in LEGACY_LIVE_ROOTS.items():
                if legacy in line:
                    violations.append(
                        f"{rel}:{ln}: references legacy `{legacy}` live-code root; use `{current}`"
                    )


def main() -> int:
    violations: list[str] = []
    knowledge_files = active_knowledge_files()

    check_legacy_live_roots([*HARNESS_FILES, *knowledge_files], violations)

    for f in HARNESS_FILES:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(ROOT)

        seen: set[str] = set()
        for raw in TOKEN_RE.findall(text):
            for cand in candidate_paths(raw):
                if cand in seen:
                    continue
                seen.add(cand)
                if not (ROOT / cand).exists():
                    violations.append(
                        f"{rel}: references missing path `{cand}` (from token `{raw}`)"
                    )

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
        print(
            f"\n{len(violations)} issue(s). Fix the reference (or restore the path) before committing."
        )
        return 1

    present = sum(1 for f in HARNESS_FILES if f.exists())
    if present == 0:
        print(
            "harness drift check: no local harness files present (gitignored / fresh checkout) — nothing to validate"
        )
        return 0
    print(
        f"harness drift check: OK ({present} harness files, {len(knowledge_files)} active knowledge files)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
