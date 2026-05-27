"""Architecture invariant tests — CLAUDE.md red lines enforced as code.

These tests replace the manual "改动前必扫" grep commands.
If any of these fail, the architecture has been violated.
Fix the violation, don't skip the test.

Red lines tested:
  1. compute/ and models/ are leaf layers (no upward imports)
  2. Pipeline steps not exposed as individual orchestrator tools
  3. Pipelines don't directly import provider SDKs
  4. Dependency blacklist (no LangChain/AutoGen/LiteLLM)
  5. No bare `except Exception:` in finrobot/
  6. No `print(` in finrobot/ (use logging)
  7. No `os.environ` outside config.py (use dependency injection)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FINAGENT = ROOT / "finrobot"
COMPUTE = FINAGENT / "engine" / "compute"
MODELS = FINAGENT / "engine" / "models"
PIPELINES = FINAGENT / "engine" / "pipelines"


def _py_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py")


def _all_imports(filepath: Path) -> list[tuple[int, str]]:
    """Return (line_number, module_string) for every import in a file."""
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            results.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
    return results


# ---------------------------------------------------------------------------
# Red line 1: compute/ and models/ are leaf layers
# ---------------------------------------------------------------------------

FORBIDDEN_UPWARD = [
    "finrobot.engine.pipelines",
    "finrobot.engine.agents",
    "finrobot.engine.orchestrator",
]

FORBIDDEN_LLM = [
    "pydantic_ai",
    "openai",
    "anthropic",
    "litellm",
]


class TestLeafLayerIsolation:
    """compute/ and models/ must not import from upper layers or LLM libraries."""

    @pytest.mark.parametrize("leaf", [COMPUTE, MODELS], ids=["compute", "models"])
    def test_no_upward_imports(self, leaf: Path) -> None:
        violations: list[str] = []
        for py in _py_files(leaf):
            for lineno, module in _all_imports(py):
                for forbidden in FORBIDDEN_UPWARD:
                    if module.startswith(forbidden):
                        rel = py.relative_to(ROOT)
                        violations.append(
                            f"  {rel}:{lineno} imports {module}\n"
                            f"  FIX: {leaf.name}/ is a leaf layer. "
                            f"Move dependency to pipeline level or pass as parameter."
                        )
        assert not violations, (
            f"Leaf layer {leaf.name}/ has forbidden upward imports:\n"
            + "\n".join(violations)
        )

    @pytest.mark.parametrize("leaf", [COMPUTE, MODELS], ids=["compute", "models"])
    def test_no_llm_imports(self, leaf: Path) -> None:
        violations: list[str] = []
        for py in _py_files(leaf):
            for lineno, module in _all_imports(py):
                for forbidden in FORBIDDEN_LLM:
                    if module == forbidden or module.startswith(forbidden + "."):
                        rel = py.relative_to(ROOT)
                        violations.append(
                            f"  {rel}:{lineno} imports {module}\n"
                            f"  FIX: {leaf.name}/ must be pure deterministic code. "
                            f"No LLM library imports allowed."
                        )
        assert not violations, (
            f"Leaf layer {leaf.name}/ imports LLM libraries:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Red line 2: Pipeline steps not exposed as individual tools
# ---------------------------------------------------------------------------

class TestPipelineEncapsulation:
    """Orchestrator tools must wrap whole pipelines, never individual steps."""

    def test_no_step_tools_in_orchestrator(self) -> None:
        orch = FINAGENT / "engine" / "orchestrator.py"
        if not orch.exists():
            pytest.skip("orchestrator.py not found")
        source = orch.read_text()
        # Tool functions should be run_* (whole pipeline), not step-level names
        tool_funcs = re.findall(r"@agent\.tool\s+async def (\w+)", source)
        step_patterns = [
            "validate_", "collect_data", "build_thesis",
            "financial_modeling", "generate_report",
        ]
        violations = [
            f for f in tool_funcs
            if any(f.startswith(p) for p in step_patterns)
        ]
        assert not violations, (
            f"Orchestrator exposes individual pipeline steps as tools: {violations}\n"
            f"FIX: Tools must wrap whole pipelines (run_*), not individual steps."
        )


# ---------------------------------------------------------------------------
# Red line 3: Pipelines don't directly import provider SDKs
# ---------------------------------------------------------------------------

PROVIDER_SDKS = ["yfinance", "finnhub", "fmpsdk", "requests_html"]


class TestProviderAbstraction:
    """Pipelines must go through DataLayer, not import provider SDKs directly."""

    def test_pipelines_no_direct_provider_imports(self) -> None:
        violations: list[str] = []
        for py in _py_files(PIPELINES):
            for lineno, module in _all_imports(py):
                for sdk in PROVIDER_SDKS:
                    if module == sdk or module.startswith(sdk + "."):
                        rel = py.relative_to(ROOT)
                        violations.append(
                            f"  {rel}:{lineno} imports {module}\n"
                            f"  FIX: Use DataLayer.fetch() instead of calling {sdk} directly."
                        )
        assert not violations, (
            "Pipelines import provider SDKs directly:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Red line 4: Dependency blacklist
# ---------------------------------------------------------------------------

BANNED_DEPS = ["langchain", "langgraph", "autogen", "litellm"]


class TestDependencyBlacklist:
    """Banned frameworks must not appear anywhere in finrobot/."""

    def test_no_banned_imports(self) -> None:
        violations: list[str] = []
        for py in _py_files(FINAGENT):
            for lineno, module in _all_imports(py):
                for banned in BANNED_DEPS:
                    if module == banned or module.startswith(banned + "."):
                        rel = py.relative_to(ROOT)
                        violations.append(
                            f"  {rel}:{lineno} imports {module}\n"
                            f"  FIX: {banned} is banned. Use PydanticAI. "
                            f"Need exception? Write an ADR in docs/cc-pillars/adrs/."
                        )
        assert not violations, (
            "Banned dependencies found:\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Coding discipline: no bare except Exception
# ---------------------------------------------------------------------------

# Regex matches `except Exception:` or `except Exception as e:` but NOT
# `except (SpecificError, Exception)` which is weird but intentional.
_BARE_EXCEPT_RE = re.compile(r"^\s*except\s+Exception\s*(as\s+\w+\s*)?:", re.MULTILINE)


class TestExceptionHygiene:
    """No bare `except Exception:` — catch specific exceptions."""

    def test_no_bare_except_exception(self) -> None:
        violations: list[str] = []
        for py in _py_files(FINAGENT):
            text = py.read_text()
            for match in _BARE_EXCEPT_RE.finditer(text):
                lineno = text[: match.start()].count("\n") + 1
                rel = py.relative_to(ROOT)
                violations.append(
                    f"  {rel}:{lineno} — bare `except Exception:`\n"
                    f"  FIX: Catch specific exceptions like (httpx.HTTPError, asyncio.TimeoutError)."
                )
        # Allow up to 0 — any bare except Exception is a violation
        assert not violations, (
            f"Bare `except Exception:` found ({len(violations)} occurrences):\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Coding discipline: no print() in finrobot/
# ---------------------------------------------------------------------------

class TestNoPrint:
    """finrobot/ must use logging, not print(). Docstring examples are OK."""

    def test_no_print_in_finrobot(self) -> None:
        violations: list[str] = []
        for py in _py_files(FINAGENT):
            tree = ast.parse(py.read_text(), filename=str(py))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                ):
                    rel = py.relative_to(ROOT)
                    violations.append(f"  {rel}:{node.lineno}")
        assert not violations, (
            "print() calls found in finrobot/ (use logging instead):\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Coding discipline: no os.environ outside config.py
# ---------------------------------------------------------------------------

_ENVIRON_RE = re.compile(r"os\.environ")


class TestNoOsEnviron:
    """Configuration must go through config.py, not os.environ directly."""

    def test_no_os_environ_outside_config(self) -> None:
        # config.py: settings source of truth; secret_store.py: bootstrap before config
        allowed = {"config.py", "secret_store.py"}
        violations: list[str] = []
        for py in _py_files(FINAGENT):
            if py.name in allowed:
                continue
            text = py.read_text()
            for match in _ENVIRON_RE.finditer(text):
                lineno = text[: match.start()].count("\n") + 1
                rel = py.relative_to(ROOT)
                violations.append(
                    f"  {rel}:{lineno} — os.environ usage\n"
                    f"  FIX: Use FinRobotSettings (finrobot/config.py) + dependency injection."
                )
        assert not violations, (
            "os.environ used outside config.py:\n" + "\n".join(violations)
        )
