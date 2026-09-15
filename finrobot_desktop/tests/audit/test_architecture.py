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
FINROBOT = ROOT / "finrobot"
COMPUTE = FINROBOT / "engine" / "compute"
MODELS = FINROBOT / "engine" / "models"
PRIMITIVES = FINROBOT / "engine" / "primitives"
PIPELINES = FINROBOT / "engine" / "pipelines"
CONTRACT = FINROBOT / "artifact" / "contract.py"


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
    """compute/, models/ and primitives/ must not import upper layers or LLM libs."""

    @pytest.mark.parametrize(
        "leaf", [COMPUTE, MODELS, PRIMITIVES], ids=["compute", "models", "primitives"]
    )
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
            f"Leaf layer {leaf.name}/ has forbidden upward imports:\n" + "\n".join(violations)
        )

    @pytest.mark.parametrize(
        "leaf", [COMPUTE, MODELS, PRIMITIVES], ids=["compute", "models", "primitives"]
    )
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
        assert not violations, f"Leaf layer {leaf.name}/ imports LLM libraries:\n" + "\n".join(
            violations
        )

    def test_primitives_never_import_data_or_compute(self) -> None:
        """primitives/ is the shared floor BELOW both data/ and compute/.

        It must depend only on stdlib / third-party math + models/. The moment a
        primitive imports data/ or compute/, the data→compute→data cycle ADR-0005
        §2.2 removed comes back silently (the providers reuse these primitives).
        """
        forbidden = ("finrobot.engine.data", "finrobot.engine.compute")
        violations: list[str] = []
        for py in _py_files(PRIMITIVES):
            for lineno, module in _all_imports(py):
                if any(module == f or module.startswith(f + ".") for f in forbidden):
                    violations.append(f"  {py.relative_to(ROOT)}:{lineno} imports {module}")
        assert not violations, (
            "primitives/ must not import data/ or compute/ (would re-create the "
            "data→compute cycle, ADR-0005 §2.2):\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Red line 2: Pipeline steps not exposed as individual tools
# ---------------------------------------------------------------------------


class TestPipelineEncapsulation:
    """Orchestrator tools must wrap whole pipelines, never individual steps."""

    def test_no_step_tools_in_orchestrator(self) -> None:
        orch = FINROBOT / "engine" / "orchestrator.py"
        if not orch.exists():
            pytest.skip("orchestrator.py not found")
        source = orch.read_text()
        # Tool functions should be run_* (whole pipeline), not step-level names
        tool_funcs = re.findall(r"@agent\.tool\s+async def (\w+)", source)
        step_patterns = [
            "validate_",
            "collect_data",
            "build_thesis",
            "financial_modeling",
            "generate_report",
        ]
        violations = [f for f in tool_funcs if any(f.startswith(p) for p in step_patterns)]
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
        assert not violations, "Pipelines import provider SDKs directly:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Red line 4: Dependency blacklist
# ---------------------------------------------------------------------------

BANNED_DEPS = ["langchain", "langgraph", "autogen", "litellm"]


class TestDependencyBlacklist:
    """Banned frameworks must not appear anywhere in finrobot/."""

    def test_no_banned_imports(self) -> None:
        violations: list[str] = []
        for py in _py_files(FINROBOT):
            for lineno, module in _all_imports(py):
                for banned in BANNED_DEPS:
                    if module == banned or module.startswith(banned + "."):
                        rel = py.relative_to(ROOT)
                        violations.append(
                            f"  {rel}:{lineno} imports {module}\n"
                            f"  FIX: {banned} is banned. Use PydanticAI. "
                            f"Need exception? Write an ADR in docs/cc-pillars/adrs/."
                        )
        assert not violations, "Banned dependencies found:\n" + "\n".join(violations)


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
        for py in _py_files(FINROBOT):
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
        for py in _py_files(FINROBOT):
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
            "print() calls found in finrobot/ (use logging instead):\n" + "\n".join(violations)
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
        for py in _py_files(FINROBOT):
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
        assert not violations, "os.environ used outside config.py:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Red line 8: heavy sync-bound coroutines must not block the server event loop
# ---------------------------------------------------------------------------

SERVER = FINROBOT / "server.py"

# Coroutines whose body is dominated by *synchronous* CPU/IO work (so awaiting
# them directly on the request/lifespan loop freezes every concurrent request).
# They must be offloaded — asyncio.to_thread / run_in_executor / a subprocess —
# never `await`ed inline. Add a name here whenever a coroutine wraps a heavy
# synchronous library call.
BLOCKING_COROUTINES = frozenset({"_refresh_quarter"})


def _await_call_names(filepath: Path) -> list[tuple[int, str]]:
    """(lineno, callee) for every ``await <callee>(...)`` directly awaited."""
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Name):
            found.append((node.lineno, func.id))
        elif isinstance(func, ast.Attribute):
            found.append((node.lineno, func.attr))
    return found


class TestEventLoopNotBlocked:
    """Synchronous-heavy coroutines must be offloaded, not awaited inline.

    Regression guard: the SEC 13F background refresh once awaited
    ``_refresh_quarter`` directly inside the FastAPI lifespan, which parsed an
    entire quarter of 13F filings on the server event loop and froze the
    dashboard endpoints. The fix offloads it via ``asyncio.to_thread`` — when
    that happens the coroutine is an *argument* to ``asyncio.run`` and is no
    longer the thing being awaited, so this scan stays green.
    """

    def test_no_blocking_coroutine_awaited_inline(self) -> None:
        violations = [
            f"  server.py:{lineno} — `await {name}(...)` blocks the event loop; "
            f"offload via asyncio.to_thread / run_in_executor"
            for lineno, name in _await_call_names(SERVER)
            if name in BLOCKING_COROUTINES
        ]
        assert not violations, (
            "heavy synchronous coroutine awaited directly on the server loop:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Red line 9: the output contract (artifact/contract.py) stays a "dumb" gate
# (spec 输出合同总闸-质量harness.md §7 Q4)
# ---------------------------------------------------------------------------

# contract.py may import ONLY these finrobot modules (Q4 "只许 engine/models 叶子 +
# summary_extractor + stdlib"; plus the Artifact type it operates on, in its own
# package under TYPE_CHECKING). Anything under compute/ data/ pipelines/ would mean
# the gate RE-RUNS computation instead of verifying the already-assembled result.
_CONTRACT_ALLOWED_FINROBOT_IMPORTS = (
    "finrobot.engine.models",  # leaf constants/ledger: numeric_claim, valuation_thresholds, reconcile_tolerances
    "finrobot.artifact.summary_extractor",
    "finrobot.artifact.models",  # the Artifact type the clauses operate on
)

# Numeric literals a clause body may compare against directly (Q4 ③ whitelist
# 0/1/-1/None, plus the 1.0 reciprocal unit). A real threshold must be imported
# from a leaf constant, never inlined as `ratio > 2.0`.
_CONTRACT_COMPARE_LITERAL_WHITELIST: frozenset[float] = frozenset({-1.0, 0.0, 1.0})


def _numeric_compare_literals(filepath: Path) -> list[tuple[int, float]]:
    """(lineno, value) for every numeric literal used as an operand of an
    ``ast.Compare`` — the bare-threshold smell the red line forbids. Resolves a
    leading unary minus so ``x < -1`` reads as -1. Booleans are not numbers here."""

    def _literal(node: ast.expr) -> float | None:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = _literal(node.operand)
            return -inner if inner is not None else None
        return None

    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    found: list[tuple[int, float]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for operand in [node.left, *node.comparators]:
            value = _literal(operand)
            if value is not None:
                found.append((node.lineno, value))
    return found


class TestArtifactContractStaysDumb:
    """The output contract is an end-to-end invariant assertion, NOT a second
    compute path (spec §7 Q4). It verifies the RESULT of a fully-assembled
    artifact without re-running / re-calibrating anything: zero I/O, no
    compute/data/pipelines imports, no inlined thresholds. These checks let the
    contract grow new clauses without silently drifting back into a compute path."""

    def test_imports_only_leaves_and_summary_extractor(self) -> None:
        violations: list[str] = []
        for lineno, module in _all_imports(CONTRACT):
            if not module.startswith("finrobot."):
                continue  # stdlib / third-party is fine
            if not any(
                module == allowed or module.startswith(allowed + ".")
                for allowed in _CONTRACT_ALLOWED_FINROBOT_IMPORTS
            ):
                violations.append(
                    f"  contract.py:{lineno} imports {module}\n"
                    f"  FIX: the contract may import ONLY engine/models leaves + "
                    f"artifact.summary_extractor + the Artifact type + stdlib. "
                    f"compute/ data/ pipelines/ would make it re-run computation."
                )
        assert not violations, (
            "ArtifactContract imports outside its allowed set (Q4 red line):\n"
            + "\n".join(violations)
        )

    def test_has_no_io(self) -> None:
        """Zero I/O: a clause is a pure sync ``check(artifact)->Finding|None``. No
        ``async def`` / ``await`` anywhere — those imply awaiting a provider/db."""
        tree = ast.parse(CONTRACT.read_text(), filename=str(CONTRACT))
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                violations.append(f"  contract.py:{node.lineno} — async def {node.name}")
            elif isinstance(node, ast.Await):
                violations.append(f"  contract.py:{node.lineno} — await expression")
        assert not violations, (
            "ArtifactContract must be zero-I/O (no async/await) — Q4 red line:\n"
            + "\n".join(violations)
        )

    def test_holds_no_bare_threshold_literals(self) -> None:
        """No clause compares against a bare numeric threshold (e.g. ``ratio > 2``).
        Thresholds must be imported leaf constants; only 0/1/-1/1.0 are allowed as
        structural literals (None/sign/reciprocal)."""
        violations = [
            f"  contract.py:{lineno} — compares against bare literal {value!r}\n"
            f"  FIX: import the calibrated threshold from an engine/models leaf "
            f"(valuation_thresholds / reconcile_tolerances)."
            for lineno, value in _numeric_compare_literals(CONTRACT)
            if value not in _CONTRACT_COMPARE_LITERAL_WHITELIST
        ]
        assert not violations, (
            "ArtifactContract inlines a bare threshold literal (Q4 ③ red line):\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Red line 10: compute/ must not import artifact/ (keeps the contract acyclic)
# ---------------------------------------------------------------------------


class TestComputeNeverImportsArtifact:
    """``artifact/`` depends on ``compute/`` (builders, models import operators) —
    a one-way edge. If ``compute/`` ever imported ``artifact/`` that edge becomes a
    cycle, and the output contract (which lives in artifact/ and imports
    engine/models leaves) could no longer sit safely below compute. This locks the
    precondition that put the contract in artifact/ in the first place (spec §4.1
    ⟦复核⟧ + §7 Q4)."""

    def test_compute_does_not_import_artifact(self) -> None:
        violations: list[str] = []
        for py in _py_files(COMPUTE):
            for lineno, module in _all_imports(py):
                if module == "finrobot.artifact" or module.startswith("finrobot.artifact."):
                    violations.append(f"  {py.relative_to(ROOT)}:{lineno} imports {module}")
        assert not violations, (
            "compute/ must not import artifact/ (would cycle artifact↔compute, "
            "ADR-0005 + spec Q4):\n" + "\n".join(violations)
        )
