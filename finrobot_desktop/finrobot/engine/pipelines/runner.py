from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finrobot.engine.deps import FinRobotDeps

import httpx
from pydantic import BaseModel
from pydantic_ai.exceptions import AgentRunError

from finrobot.artifact.contract import enforce_artifact_contract
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import StepOutput
from finrobot.engine.pipelines.protocols import ArtifactBuilder, ProgressCallback
from finrobot.engine.pipelines.result import PipelineResult
from finrobot.engine.pipelines.step import PipelineStep, PipelineStepError
from finrobot.engine.pipelines.validators import ValidationResult

# Seconds to wait before each executor-exception retry (index = attempt number).
_RETRY_DELAYS = [2, 5, 10]

# Substrings that mark an exception as recoverable (rate-limit / transient).
# All comparisons are lower-cased.
_RECOVERABLE_SUBSTRINGS = ("429", "rate limit", "too many requests", "timeout")

# Substrings that mark an exception as a non-recoverable error that must NOT be
# retried. Two classes:
#   - billing / auth ("insufficient balance"): retrying can never succeed.
#   - context-length overflow: the prompt deterministically exceeds the model's
#     window, so re-sending the identical prompt fails identically. Without a
#     fail-fast here, an oversized prompt burns every retry, then the
#     "best-effort continue" policy lets the run proceed with NO FinancialData —
#     a green ✓ on the step followed by a confusing crash downstream at
#     peer_analysis ("target FinancialData not available"). Aborting now surfaces
#     the real context-length message instead.
_FATAL_SUBSTRINGS = (
    "insufficient balance",
    "maximum context length",
    "context_length_exceeded",
    "reduce the length of the messages",
    # Auth / bad-request errors are NOT transient — retrying just burns quota and
    # delays a clear failure. A wrong API key, an unknown model id, or a 4xx are
    # the user's config to fix, not something a retry will heal.
    "invalid api key",
    "incorrect api key",
    "authentication",
    "unauthorized",
    "invalid_api_key",
    "permission",
    "model not found",
    "does not exist",
)

_PROMPT_MAX_STRING_CHARS = 1200
_PROMPT_MAX_LIST_ITEMS = 8
_PROMPT_MAX_DICT_KEYS = 30
_PROMPT_MAX_DEPTH = 6
_PROMPT_MAX_STRUCTURED_CHARS = 16_000

# Per-item cap for raw ``required_data`` text dumped into a step prompt by
# _gather_data. Structured context already had a 16k/item cap; required_data did
# NOT, which let a 10-K's full section text (tripled across items/sections/
# mdna_text) flood the data_collection prompt to 146k tokens and 400 gpt-4o.
# FINANCIALS/PRICE renders are a few KB, so legit data is never truncated; this
# only fires on pathological payloads, and always leaves a visible marker so no
# number is ever silently dropped.
_PROMPT_MAX_STEP_DATA_CHARS = 12_000

# Soft ceiling for the WHOLE assembled prompt. Crossing it is not fatal (the
# per-item caps above already bound inputs, and a true model overflow fails fast
# via _FATAL_SUBSTRINGS) — it is a loud regression signal that some new section
# is bloating prompts. Char-based on purpose: model-agnostic and free, unlike a
# per-model token window that would rot as models change.
_PROMPT_WARN_TOTAL_CHARS = 200_000


def _truncate_for_prompt(text: str, cap: int) -> str:
    """Cap *text* at *cap* chars, appending a visible truncation marker so a
    shortened payload can never be mistaken for the complete one."""
    if len(text) <= cap:
        return text
    return f"{text[:cap]}\n... [truncated {len(text) - cap} chars to fit prompt budget]"


def _is_recoverable_exception(exc: BaseException) -> bool:
    """Return True when *exc* is a transient / rate-limit error worth retrying.

    Rules (applied in order):
    1. If the message contains a fatal substring → NOT recoverable (return False).
    2. If it is one of the typed recoverable classes → recoverable.
    3. If the message contains a recoverable substring → recoverable.
    4. Otherwise → NOT recoverable.
    """
    msg = str(exc).lower()
    if any(s in msg for s in _FATAL_SUBSTRINGS):
        return False
    if isinstance(exc, (AgentRunError, ProviderError, httpx.TimeoutException, httpx.ConnectError)):
        return True
    return any(s in msg for s in _RECOVERABLE_SUBSTRINGS)


logger = logging.getLogger(__name__)


def _compact_for_prompt(value: object, depth: int = 0) -> object:
    """Return a JSON-safe bounded representation for LLM prompt context."""
    if depth >= _PROMPT_MAX_DEPTH:
        return f"[{type(value).__name__} omitted at depth {_PROMPT_MAX_DEPTH}]"

    if isinstance(value, BaseModel):
        return _compact_for_prompt(value.model_dump(mode="json"), depth)

    # Duck-typed objects exposing ``model_dump_json`` (Pydantic-shaped without
    # subclassing BaseModel, e.g. test doubles or proxy wrappers). Try parsing
    # the JSON back into a dict so it nests cleanly; fall back to the raw
    # string on parse failure.
    if hasattr(value, "model_dump_json") and callable(value.model_dump_json):
        try:
            return _compact_for_prompt(json.loads(value.model_dump_json()), depth)
        except (ValueError, TypeError):
            return str(value)

    if isinstance(value, dict):
        out: dict[str, object] = {}
        items = list(value.items())
        for key, item in items[:_PROMPT_MAX_DICT_KEYS]:
            out[str(key)] = _compact_for_prompt(item, depth + 1)
        if len(items) > _PROMPT_MAX_DICT_KEYS:
            out["_omitted_keys"] = len(items) - _PROMPT_MAX_DICT_KEYS
        return out

    if isinstance(value, (list, tuple)):
        list_out = [_compact_for_prompt(item, depth + 1) for item in value[:_PROMPT_MAX_LIST_ITEMS]]
        if len(value) > _PROMPT_MAX_LIST_ITEMS:
            list_out.append({"_omitted_items": len(value) - _PROMPT_MAX_LIST_ITEMS})
        return list_out

    if isinstance(value, str):
        if len(value) <= _PROMPT_MAX_STRING_CHARS:
            return value
        omitted = len(value) - _PROMPT_MAX_STRING_CHARS
        return f"{value[:_PROMPT_MAX_STRING_CHARS]}... [truncated {omitted} chars]"

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return str(value)


def _render_structured_prompt_value(value: object) -> str:
    compacted = _compact_for_prompt(value)
    rendered = json.dumps(compacted, ensure_ascii=False, indent=2, default=str)
    if len(rendered) <= _PROMPT_MAX_STRUCTURED_CHARS:
        return rendered
    omitted = len(rendered) - _PROMPT_MAX_STRUCTURED_CHARS
    return f"{rendered[:_PROMPT_MAX_STRUCTURED_CHARS]}\n... [structured item truncated {omitted} chars]"


def _data_type_or_none(data_type: str | DataType) -> DataType | None:
    try:
        return DataType(data_type)
    except ValueError:
        return None


def _canonical_context_string(data_type: DataType, value: object) -> str:
    """Render normalized PRICE / FINANCIALS for prompt use.

    The pipeline step prompt is a rendering port over the deterministic data
    contract; it must not see raw provider dicts for the two numeric bedrock
    payloads. The JSON below includes provenance/degraded markers, currencies,
    period basis, and warnings exactly as the canonical DTO exposes them.
    """

    rendered = _render_structured_prompt_value(value)
    return f"[canonical] {data_type.value} (normalized contract)\n```json\n{rendered}\n```"


@dataclass
class Pipeline:
    """Code-enforced sequence of analysis steps."""

    steps: list[PipelineStep]
    max_retries: int = 3
    artifact_builder: ArtifactBuilder | None = None
    """Optional callable that converts a PipelineResult into an Artifact.

    When set and deps.artifact_store is not None, execute() will call
    artifact_builder(result, ticker, deps) after all steps complete and
    persist the returned Artifact via artifact_store.save().

    Pipeline factory functions (create_dcf_pipeline etc.) set this to their
    respective _build_artifact_* functions.
    """

    async def execute(
        self,
        deps: "FinRobotDeps",
        ticker: str,
        progress: ProgressCallback | None = None,
        lang: str | None = None,
        source_artifact_id: str | None = None,
        **kwargs: object,
    ) -> "PipelineResult":
        # Gate the WHOLE run on the app-wide concurrency cap when deps carries
        # one (BUG-017). Acquiring here — not in routes/runs.py — means EVERY
        # caller that passes deps with a semaphore is capped: the REST runner,
        # the chat orchestrator (ctx.deps), and the Coverage batch all funnel
        # through this single acquire, and each run acquires exactly once (no
        # double-acquire / deadlock risk). deps.run_semaphore is None for
        # single-invocation CLI/SDK processes → nullcontext → no cap.
        semaphore = getattr(deps, "run_semaphore", None)
        async with semaphore if semaphore is not None else contextlib.nullcontext():
            return await self._execute_steps(
                deps,
                ticker,
                progress=progress,
                lang=lang,
                source_artifact_id=source_artifact_id,
                **kwargs,
            )

    async def _execute_steps(
        self,
        deps: "FinRobotDeps",
        ticker: str,
        progress: ProgressCallback | None = None,
        lang: str | None = None,
        source_artifact_id: str | None = None,
        **kwargs: object,
    ) -> "PipelineResult":
        results: dict[str, str] = {}
        structured_results: dict[str, object] = {}
        failed_validations: list[dict[str, str]] = []
        total = len(self.steps)

        # Resolve output language: explicit arg > settings > default "en"
        _settings = getattr(deps, "settings", None)
        settings_lang = getattr(_settings, "language", None)
        effective_lang: str = lang or (settings_lang if isinstance(settings_lang, str) else "en")
        step_kwargs = dict(kwargs)
        if source_artifact_id is not None:
            step_kwargs["source_artifact_id"] = source_artifact_id

        for i, step in enumerate(self.steps, start=1):
            logger.info(f"Step {i}/{total}: {step.name}...")
            if progress is not None:
                await progress.on_step_start(i, total, step.name)

            step_data = await self._gather_data(
                deps,
                step.required_data,
                ticker,
                results,
                structured_results=structured_results,
            )

            methodology = ""
            if step.skill_section and deps.skill_runtime:
                skill = deps.skill_runtime.get(step.skill_section)
                if skill:
                    methodology = skill.full_content

            prompt = self._build_step_prompt(
                step,
                step_data,
                methodology,
                structured_results,
                lang=effective_lang,
            )

            t0 = time.monotonic()
            validation_error = await self._run_step(
                step,
                deps,
                prompt,
                ticker,
                results,
                structured_results,
                step_index=i,
                progress=progress,
                step_kwargs=step_kwargs,
            )
            elapsed = time.monotonic() - t0
            if validation_error:
                failed_validations.append({"step": step.name, "error": validation_error})
                # A critical step is a hard prerequisite — continuing past its
                # failure only produces a confusing crash several steps later
                # (and, worse, a green ✓ on this step because on_step_end fires
                # regardless). Abort now with a clear message naming THIS step.
                # We raise BEFORE on_step_end so no misleading "completed" event
                # is emitted for the step that actually failed.
                if step.critical:
                    logger.error(
                        "Critical step '%s' failed after retries — aborting run: %s",
                        step.name,
                        validation_error,
                    )
                    raise PipelineStepError(step.name, validation_error)

            if progress is not None:
                # Pass validation_error through so a degraded (non-critical,
                # failed-after-retries) step emits an amber "degraded" marker
                # instead of a misleading green ✓ (BUG-058). None on a clean
                # pass keeps the event identical to before.
                await progress.on_step_end(i, total, step.name, elapsed, validation_error)

            if validation_error:
                logger.info(f"Step {i}/{total}: {step.name} ⚠ degraded")
            else:
                logger.info(f"Step {i}/{total}: {step.name} ✓")

        pipeline_result = PipelineResult(
            steps=results, structured_data=structured_results, failed_validations=failed_validations
        )

        # Auto-persist artifact if store is available (non-blocking on failure)
        _artifact_store = getattr(deps, "artifact_store", None)
        if _artifact_store is not None and self.artifact_builder is not None:
            try:
                artifact = self.artifact_builder(pipeline_result, ticker, deps)
                # Stamp the prose language onto the artifact so the UI renders the
                # body in the language it was actually generated in, independent of
                # the viewer's current UI locale. Single write point: effective_lang
                # already resolved above (explicit arg > settings > "en").
                artifact.meta.language = "zh" if effective_lang == "zh" else "en"
                # Record version lineage when this run was triggered as a re-run
                # from an existing artifact. The diff view's default "compare vs
                # previous" walks meta.parent_artifact_id; created_at adjacency is
                # only the fallback when the chain is absent (legacy / fresh runs).
                if source_artifact_id is not None:
                    artifact.meta.parent_artifact_id = source_artifact_id
                # Output-contract total gate: the single persist boundary every
                # artifact type converges on. Whole-artifact invariants the
                # upstream fragment gates are structurally blind to (headline
                # upside band, narrative malformation). Pure, zero-I/O, degrades
                # in place (withhold/REVIEW) and never raises — same "log, don't
                # blank the run" contract as the persist try-block below.
                artifact = enforce_artifact_contract(artifact)
                artifact_id = await _artifact_store.save(artifact)
                pipeline_result.artifact_id = artifact_id
                logger.info("Artifact persisted: %s", artifact_id)
            except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError):
                logger.exception(
                    "Failed to persist artifact for %s — result still returned",
                    ticker,
                )

        return pipeline_result

    async def _attempt(
        self,
        step: PipelineStep,
        deps: "FinRobotDeps",
        prompt: str,
        ticker: str,
        results: dict[str, str],
        structured_results: dict[str, object],
        step_kwargs: dict[str, object] | None = None,
    ) -> ValidationResult:
        """Run executor + store output + validate. Returns the validation result.

        Used by both the first attempt and each retry inside _run_step, so the
        execute → store → validate triple lives in exactly one place.
        ``step_kwargs`` are the per-run overrides forwarded to the executor.
        """
        output = await step.executor(
            step.agent, deps, prompt, structured_results, ticker, **(step_kwargs or {})
        )
        self._store_output(step.name, output, results, structured_results)
        return self._validate_step(step, step.name, results, structured_results)

    @staticmethod
    def _store_output(
        step_name: str,
        output: StepOutput | str,
        results: dict[str, str],
        structured_results: dict[str, object],
    ) -> None:
        """Parse step output and store text/structured data into the result dicts."""
        if isinstance(output, StepOutput):
            results[step_name] = output.text
            if output.structured is not None:
                structured_results[step_name] = output.structured
                logger.info(
                    f"Step '{step_name}' produced structured data: "
                    f"{type(output.structured).__name__}"
                )
        elif isinstance(output, str):
            results[step_name] = output
        else:
            results[step_name] = str(output)

    @staticmethod
    def _validate_step(
        step: PipelineStep,
        step_name: str,
        results: dict[str, str],
        structured_results: dict[str, object],
    ) -> "ValidationResult":
        """Delegate to step.validator with the best available output."""
        output: str | object = structured_results.get(step_name, results[step_name])
        return step.validator(output)

    async def _run_step(
        self,
        step: PipelineStep,
        deps: "FinRobotDeps",
        prompt: str,
        ticker: str,
        results: dict[str, str],
        structured_results: dict[str, object],
        step_index: int = 0,
        progress: ProgressCallback | None = None,
        step_kwargs: dict[str, object] | None = None,
    ) -> str | None:
        """Execute a single pipeline step with retry logic.

        Encapsulates: execution -> output storage -> validation -> retry loop.

        Two retry triggers share the same loop:
        - Validation failure (original behaviour): ``validation.passed == False``.
        - Recoverable executor exception: ``AgentRunError``, ``ProviderError``,
          ``httpx.TimeoutException / ConnectError``, or any exception whose
          message contains "429" / "rate limit" / "too many requests" / "timeout".

        Non-recoverable exceptions (e.g. "Insufficient Balance" 402) propagate
        immediately without consuming any retry budget.

        Returns the validation error string if the step failed after all retries,
        or None if the step succeeded.
        """
        # ── helpers ────────────────────────────────────────────────────────────

        async def _attempt_with_exc_retry(
            current_prompt: str, budget: int
        ) -> tuple["ValidationResult | None", str | None, int]:
            """Run _attempt, catching recoverable exceptions as retry signals.

            Returns (validation_result, exc_error_str, remaining_budget).
            - If the attempt succeeds or fails validation normally, exc_error_str is None.
            - If a recoverable exception fires, validation_result is None and
              exc_error_str carries the error message.
            - A non-recoverable exception propagates immediately (budget is not
              consumed).
            """
            try:
                val = await self._attempt(
                    step, deps, current_prompt, ticker, results, structured_results, step_kwargs
                )
                return val, None, budget
            except BaseException as exc:
                if not _is_recoverable_exception(exc):
                    raise
                return None, str(exc), budget

        # ── first attempt ──────────────────────────────────────────────────────
        validation, exc_err, _ = await _attempt_with_exc_retry(prompt, self.max_retries)

        # Fast path: first attempt succeeded with valid output.
        if validation is not None and validation.passed:
            return None

        # ── deterministic short-circuit (BUG-059) ──────────────────────────────
        # A deterministic executor ignores the re-prompt and recomputes purely
        # from structured_context + data_layer, so a VALIDATION failure
        # (exc_err is None) re-produces byte-identical failing output on every
        # retry — burning the whole budget (and re-fetching every input) for no
        # chance of a different result. Degrade immediately. The EXCEPTION path
        # (exc_err set) still loops below: a transient provider/FX error may
        # recover on back-off even for a deterministic step.
        if step.deterministic and exc_err is None:
            assert validation is not None  # one of the two is always set
            logger.warning(
                "Pipeline step '%s' (deterministic) failed validation: %s. "
                "Skipping retries — re-running cannot change the output. "
                "Continuing with best-effort output.",
                step.name,
                validation.error,
            )
            return validation.error

        # ── unified retry loop ─────────────────────────────────────────────────
        for attempt in range(self.max_retries):
            # Determine the error label and the prompt to use on the next attempt.
            if exc_err is not None:
                error_label = exc_err
                retry_prompt = prompt  # re-run with original prompt on exc retry
            else:
                assert validation is not None  # invariant: one of the two is set
                error_label = validation.error or ""
                retry_prompt = (
                    f"Previous output failed validation: {validation.error}\n"
                    f"Fix the issues and try again.\n\n{results.get(step.name, '')}"
                )

            logger.warning(
                "Step '%s' retry %d/%d: %s",
                step.name,
                attempt + 1,
                self.max_retries,
                error_label,
            )
            if progress is not None:
                await progress.on_step_retry(step_index, step.name, attempt + 1, error_label)

            # Back-off only for executor exceptions (not for validation failures,
            # which benefit from an immediate re-prompt rather than sleeping).
            if exc_err is not None and attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])

            validation, exc_err, _ = await _attempt_with_exc_retry(
                retry_prompt, self.max_retries - attempt - 1
            )

            if validation is not None and validation.passed:
                return None

        # ── all retries exhausted ──────────────────────────────────────────────
        if exc_err is not None:
            final_error = f"executor error after {self.max_retries} retries: {exc_err}"
            logger.warning(
                "Pipeline step '%s' executor failed after %d retries: %s. "
                "Continuing with best-effort output.",
                step.name,
                self.max_retries,
                exc_err,
            )
            return final_error

        assert validation is not None
        logger.warning(
            "Pipeline step '%s' failed validation after %d retries: %s. "
            "Continuing with best-effort output.",
            step.name,
            self.max_retries,
            validation.error,
        )
        return validation.error

    async def _gather_data(
        self,
        deps: "FinRobotDeps",
        required_data: "list[str | DataType]",
        ticker: str,
        previous_results: dict[str, str],
        *,
        structured_results: dict[str, object] | None = None,
    ) -> str:
        if not required_data:
            if not previous_results:
                return ""
            # Compact mode: pass the last 2 steps' full text + 1-line summaries of
            # everything before them. Step N often needs both step N-1 and N-2
            # (e.g., thesis reads financial_modeling AND peer_analysis), so 2 is
            # the sweet spot between context completeness and prompt size. Structured
            # data from earlier steps is still available via structured_context.
            sr = structured_results or {}
            keys = list(previous_results.keys())
            parts: list[str] = []
            for name in keys[:-2]:
                text = previous_results[name]
                word_count = len(text.split())
                if name in sr:
                    # Step has structured data available via structured_context
                    parts.append(
                        f"[Previous: {name} — {word_count} words, see structured_context for data]"
                    )
                else:
                    # D6: no structured data — include first 300 chars so
                    # information is not completely lost in compact mode.
                    snippet = text[:300]
                    ellipsis = "..." if len(text) > 300 else ""
                    parts.append(f"[Previous: {name} — {word_count} words] {snippet}{ellipsis}")
            for name in keys[-2:]:
                parts.append(f"=== {name} ===\n{previous_results[name]}")
            return "\n\n".join(parts)

        parts = []
        for data_type in required_data:
            try:
                canonical_type = _data_type_or_none(data_type)
                if canonical_type in (DataType.FINANCIALS, DataType.PRICE):
                    normalized = await deps.data_layer.fetch_canonical(canonical_type, ticker)
                    rendered = _canonical_context_string(canonical_type, normalized)
                else:
                    result = await deps.data_layer.fetch(data_type, ticker)
                    rendered = result.to_context_string()
                parts.append(_truncate_for_prompt(rendered, _PROMPT_MAX_STEP_DATA_CHARS))
            except (ProviderError, ValueError, KeyError) as e:
                logger.warning(f"Failed to fetch {data_type} for {ticker}: {e}")
                parts.append(f"[{data_type}: data unavailable — {e}]")
        return "\n\n".join(parts)

    def _build_step_prompt(
        self,
        step: PipelineStep,
        step_data: str,
        methodology: str,
        structured_context: dict[str, object],
        *,
        lang: str = "en",
    ) -> str:
        parts = [f"Step: {step.name}"]
        if step_data:
            parts.append(f"Data:\n{step_data}")
        if methodology:
            parts.append(f"Methodology:\n{methodology}")
        if structured_context:
            sc_parts = ["Structured Data from Previous Steps:"]
            for name, model in structured_context.items():
                sc_parts.append(
                    f"### {name}:\n```json\n{_render_structured_prompt_value(model)}\n```"
                )
            parts.append("\n".join(sc_parts))
        parts.append("Produce a detailed, structured analysis for this step.")

        # Language instruction — injected at the end so it takes precedence over
        # any language cue the agent might pick up from mixed-language evidence.
        # Both branches are explicit: the agent .md files are language-neutral
        # (no hardcoded "中文"/"English") so prose language is decided HERE, the
        # single source of truth, driven by the per-run effective_lang.
        if lang == "zh":
            parts.append(
                "IMPORTANT: Respond in Chinese (简体中文). "
                "Use standard Chinese financial terminology (e.g. 营业收入, 息税折旧摊销前利润, "
                "加权平均资本成本, 自由现金流, 企业价值, 终值). "
                "Keep all numerical values, ticker symbols, and financial acronyms "
                "(WACC, DCF, EV, EBITDA, FCF, P/E) in English. "
                "Tables and section headers should be in Chinese."
            )
        else:
            parts.append(
                "IMPORTANT: Respond in English. Use standard English financial "
                "terminology and keep all numerical values, ticker symbols, and "
                "acronyms (WACC, DCF, EV, EBITDA, FCF, P/E) as-is. Do not switch "
                "to another language even if some source evidence is non-English."
            )

        prompt = "\n\n".join(parts)
        if len(prompt) > _PROMPT_WARN_TOTAL_CHARS:
            logger.warning(
                "Step '%s' prompt is %d chars (> %d soft ceiling) — a section is "
                "bloating the prompt and may approach the model's context window. "
                "Check what this step injects into required_data / structured_context.",
                step.name,
                len(prompt),
                _PROMPT_WARN_TOTAL_CHARS,
            )
        return prompt
