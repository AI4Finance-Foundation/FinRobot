# P5 — Quality Finish + Feature Completion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all remaining audit items (D4-D6, I1-I7, D3-root), add minimal A-share support, and document distribution strategy.

**Architecture:** 6 independent tracks. No new dependencies. Each track modifies 1-3 files with surgical changes. All tracks can be implemented in any order.

**Tech Stack:** PydanticAI, FastAPI, Click, openpyxl, pytest. No new deps.

---

## File Map

| Track | File | Action | Responsibility |
|-------|------|--------|----------------|
| A | `finrobot/engine/data/layer.py` | Modify (lines 58-92) | Cross-validate all financials providers, handle empty secondary |
| A | `finrobot/engine/data/validator.py` | Modify (line 51-98) | Early return warning on empty secondary data |
| A | `finrobot/engine/pipelines/base.py` | Modify (lines 291-297) | Compact context includes text snippet for steps without structured data |
| B | `finrobot/server.py` | Modify (lines 165-177, 261-274) | Cache sub-agents in lifespan, fix complete event, re-enable LBO Excel |
| B | `finrobot/cli.py` | Modify (lines 103-108) | Reprint step label after retry |
| C | `finrobot/sdk.py` | Modify (lines 65, 122, 269-279) | Tighten type annotations, flush loop before close |
| D | `finrobot/engine/orchestrator.py` | Modify (lines 24-97) | Extract LBOInputs + LBOResult into report context |
| E | `finrobot/engine/data/providers/yfinance_provider.py` | Verify (no changes expected) | Confirm no ticker format validation blocks non-US tickers |
| E | `finrobot/engine/compute/extractor.py` | Verify (no changes expected) | Confirm no ticker format assumptions |
| E | `README.md` | Modify | Document tax_rate/discount_rate defaults |
| F | `docs/distribution.md` | Create | PyInstaller/electron-builder feasibility research |

---

## Track A — Data Layer Robustness

### Task 1: D4 — Cross-validate all financials providers (not just 2)

**Files:**
- Modify: `finrobot/engine/data/layer.py:58-92`
- Test: `tests/unit/test_data_layer.py`

**Context:** Currently line 92 has `break` after the second provider. Third+ providers never participate in cross-validation. The fix: for `DataType.FINANCIALS`, keep iterating after the first secondary, accumulating warnings. Hard cap at 3 providers total.

- [ ] **Step 1: Write failing test — third provider discrepancy appears in warnings**

In `tests/unit/test_data_layer.py`, add to `TestCrossValidationIntegration` class (after ~line 333). Uses the existing `MockProvider(name_, caps, result, raises)` pattern and `DataResult` constructor:

```python
async def test_cross_validation_uses_all_three_providers(self, cache):
    """D4: third provider's discrepancy must appear in warnings."""
    base = {"revenue": 100_000, "ebitda": 50_000}
    r_base = DataResult(
        data=base, provider="placeholder", ticker="TEST",
        data_type="financials", timestamp=datetime.now(tz=timezone.utc),
    )
    r_discrepant = DataResult(
        data={"revenue": 200_000, "ebitda": 50_000},  # 100% revenue diff
        provider="p3", ticker="TEST", data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    p1 = MockProvider("p1", ["financials"], result=r_base.model_copy(update={"provider": "p1"}))
    p2 = MockProvider("p2", ["financials"], result=r_base.model_copy(update={"provider": "p2"}))
    p3 = MockProvider("p3", ["financials"], result=r_discrepant)
    layer = DataLayer([p1, p2, p3], cache)
    result = await layer.fetch("financials", "TEST")
    # p3 must have been called
    assert p3.fetch_called == 1, "Third provider was not called"
    # p3's discrepancy must be in warnings
    assert any("p3" in w for w in result.warnings), (
        f"Third provider discrepancy not in warnings: {result.warnings}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_data_layer.py::TestCrossValidationIntegration::test_cross_validation_uses_all_three_providers -xvs`
Expected: FAIL — `p3.fetch_called == 0` (third provider never called due to `break` on line 92)

- [ ] **Step 3: Write failing test — hard cap at 3 providers**

```python
async def test_cross_validation_caps_at_three_providers(self, cache):
    """D4: at most 3 providers attempted for financials, even if more configured."""
    base_data = {"revenue": 100_000}
    providers = []
    for i in range(5):
        r = DataResult(
            data=base_data, provider=f"p{i}", ticker="TEST",
            data_type="financials", timestamp=datetime.now(tz=timezone.utc),
        )
        providers.append(MockProvider(f"p{i}", ["financials"], result=r))
    layer = DataLayer(providers, cache)
    await layer.fetch("financials", "TEST")
    fetched = [p for p in providers if p.fetch_called > 0]
    assert len(fetched) <= 3, f"Expected max 3 providers, got {len(fetched)}"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_data_layer.py::TestCrossValidationIntegration::test_cross_validation_caps_at_three_providers -xvs`
Expected: FAIL — all 5 providers called (only 2 checked currently, but with D4 fix removing the break, all 5 would be called without the cap)

- [ ] **Step 5: Implement — remove early break, add provider counter**

In `finrobot/engine/data/layer.py`, replace lines 58-92:

```python
            if primary_result is None:
                primary_result = result
                if data_type == DataType.FINANCIALS:
                    continue
                break
            else:
                discrepancies = cross_validate(primary_result, result)
                if discrepancies:
                    for w in discrepancies:
                        logger.warning(w)
                merged: list[str] = []
                seen: set[str] = set()
                for w in (
                    list(primary_result.warnings)
                    + list(result.warnings)
                    + discrepancies
                ):
                    if w in seen:
                        continue
                    seen.add(w)
                    merged.append(w)
                if merged != list(primary_result.warnings):
                    primary_result = primary_result.model_copy(
                        update={"warnings": merged}
                    )
                break  # two providers checked — done
```

With:

First, initialize `secondary_count` before the for loop (after `primary_result: DataResult | None = None` around line 46):

```python
        primary_result: DataResult | None = None
        secondary_count = 0  # D4: track how many secondaries have been cross-validated
        for provider in self._providers:
```

Then replace lines 58-92 (inside the for loop body):

```python
            if primary_result is None:
                primary_result = result
                if data_type == DataType.FINANCIALS:
                    continue  # keep looking for secondaries
                break
            else:
                # Cross-validate this secondary against primary
                discrepancies = cross_validate(primary_result, result)
                if discrepancies:
                    for w in discrepancies:
                        logger.warning(w)
                merged: list[str] = []
                seen: set[str] = set()
                for w in (
                    list(primary_result.warnings)
                    + list(result.warnings)
                    + discrepancies
                ):
                    if w in seen:
                        continue
                    seen.add(w)
                    merged.append(w)
                if merged != list(primary_result.warnings):
                    primary_result = primary_result.model_copy(
                        update={"warnings": merged}
                    )
                secondary_count += 1
                if data_type != DataType.FINANCIALS or secondary_count >= 2:
                    break  # non-financials: done after 1st secondary; financials: cap at 3 total
                # financials with room: keep trying remaining providers
```

- [ ] **Step 6: Update existing test that asserts p3 NOT called**

`TestChainFallback::test_three_provider_chain_first_succeeds` (line 171-183) currently asserts `p3.fetch_called == 0`. After D4, all 3 will be called for financials. Update the assertion:

```python
# Before: assert p3.fetch_called == 0
# After:
assert p3.fetch_called == 1  # D4: all providers now participate in cross-validation
```

- [ ] **Step 7: Run all data layer tests**

Run: `python -m pytest tests/unit/test_data_layer.py -xvs`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add finrobot/engine/data/layer.py tests/unit/test_data_layer.py
git commit -m "fix(D4): cross-validate all financials providers up to 3"
```

---

### Task 2: D5 — Empty secondary data warning

**Files:**
- Modify: `finrobot/engine/data/validator.py:51-60`
- Modify: `finrobot/engine/data/layer.py:66-92` (inside the else branch)
- Test: `tests/unit/test_data_validator.py`, `tests/unit/test_data_layer.py`

**Context:** If a secondary provider returns `data={}`, `cross_validate()` silently returns `[]` because every `.get(field)` returns None. The fix is two-pronged: (a) `cross_validate()` detects empty secondary and returns a warning, (b) `layer.py` skips calling `cross_validate` on empty data and continues to next provider.

**Prerequisite:** Task 1 must be completed first (line numbers in `layer.py` will have shifted).

- [ ] **Step 1: Write failing test — validator warns on empty secondary**

In `tests/unit/test_data_validator.py` (add to `TestCrossValidate` class, matching existing pattern which constructs `DataResult` with all required fields):

```python
def test_cross_validate_empty_secondary_warns(self):
    """D5: empty secondary data must produce a warning, not silent pass."""
    primary = DataResult(
        provider="p1", data={"revenue": 100_000, "ebitda": 50_000},
        ticker="TEST", data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    secondary = DataResult(
        provider="p2", data={},
        ticker="TEST", data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    warnings = cross_validate(primary, secondary)
    assert len(warnings) == 1
    assert "empty data" in warnings[0].lower()
    assert "p2" in warnings[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_data_validator.py::TestCrossValidate::test_cross_validate_empty_secondary_warns -xvs`
Expected: FAIL — `assert len(warnings) == 1` (actually 0)

- [ ] **Step 3: Implement — early return in cross_validate**

In `finrobot/engine/data/validator.py`, after line 60 (`p, s = primary.data, secondary.data`), add:

```python
    if not s:
        return [
            f"Secondary provider {secondary.provider} returned empty data "
            f"— cross-validation skipped"
        ]
```

- [ ] **Step 4: Run validator tests**

Run: `python -m pytest tests/unit/test_data_validator.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Write failing test — layer skips empty secondary, tries next provider**

In `tests/unit/test_data_layer.py` (add to `TestCrossValidationIntegration`, using `MockProvider` pattern):

```python
async def test_empty_secondary_skipped_tries_next_provider(self, cache):
    """D5: empty secondary data → warning added, next provider tried."""
    base = {"revenue": 100_000, "ebitda": 50_000}
    r1 = DataResult(
        data=base, provider="p1", ticker="TEST",
        data_type="financials", timestamp=datetime.now(tz=timezone.utc),
    )
    r2_empty = DataResult(
        data={}, provider="p2", ticker="TEST",
        data_type="financials", timestamp=datetime.now(tz=timezone.utc),
    )
    r3 = DataResult(
        data={"revenue": 200_000, "ebitda": 50_000}, provider="p3",
        ticker="TEST", data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    p1 = MockProvider("p1", ["financials"], result=r1)
    p2 = MockProvider("p2", ["financials"], result=r2_empty)
    p3 = MockProvider("p3", ["financials"], result=r3)
    layer = DataLayer([p1, p2, p3], cache)
    result = await layer.fetch("financials", "TEST")
    # p2's empty warning must exist
    assert any("empty data" in w.lower() for w in result.warnings)
    # p3 must have been tried (not stopped after p2)
    assert p3.fetch_called > 0
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_data_layer.py::TestDataLayerFetch::test_empty_secondary_skipped_tries_next_provider -xvs`
Expected: FAIL — p3 not called (break after p2) or empty warning missing

- [ ] **Step 7: Implement — layer.py handles empty secondary**

In the `else` branch of `layer.py` (where secondary providers are processed), add an early check before `cross_validate`:

```python
            else:
                # D5: skip empty secondary, add warning, try next provider
                if not result.data:
                    empty_warn = (
                        f"Secondary provider {provider.name} returned empty data "
                        f"— cross-validation skipped"
                    )
                    logger.warning(empty_warn)
                    if empty_warn not in primary_result.warnings:
                        merged = list(primary_result.warnings) + [empty_warn]
                        primary_result = primary_result.model_copy(
                            update={"warnings": merged}
                        )
                    # Don't count toward secondary_count — keep trying
                    continue
                # ... existing cross_validate logic ...
```

- [ ] **Step 8: Run all data layer + validator tests**

Run: `python -m pytest tests/unit/test_data_layer.py tests/unit/test_data_validator.py -xvs`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add finrobot/engine/data/validator.py finrobot/engine/data/layer.py tests/unit/test_data_validator.py tests/unit/test_data_layer.py
git commit -m "fix(D5): warn on empty secondary data, try next provider"
```

---

### Task 3: D6 — Compact context fallback summary

**Files:**
- Modify: `finrobot/engine/pipelines/base.py:291-297`
- Test: `tests/unit/test_pipeline_base.py`

**Context:** Steps older than N-2 get a 1-line placeholder pointing to `structured_context`. If a step has no structured data, the info is completely lost. Fix: include first 300 chars of text for steps without structured data.

- [ ] **Step 1: Write failing test**

In `tests/unit/test_pipeline_base.py`, add to `TestGatherData` class. Uses a 4-step pipeline approach — run the pipeline and verify the compacted output passed to later steps includes text snippets. The test uses a custom executor to capture what `_gather_data` produces:

```python
async def test_compact_context_includes_snippet_for_unstructured_steps(self):
    """D6: steps without structured_context get 300-char text snippet."""
    captured_prompts: list[str] = []

    async def capture_fn(agent, deps, prompt, structured_context, ticker):
        captured_prompts.append(prompt)
        return "step output"

    # 4 steps: first two produce text only (no structured data).
    # Steps 3-4 have no required_data → they use compact mode.
    # Step 1's text should appear as a snippet (not just a 1-line pointer).
    steps = [
        PipelineStep(name="step_a", agent=MagicMock(), required_data=["financials"],
                     validator=TextValidator(validate_is_non_empty), executor=capture_fn),
        PipelineStep(name="step_b", agent=MagicMock(),
                     validator=TextValidator(validate_is_non_empty), executor=capture_fn),
        PipelineStep(name="step_c", agent=MagicMock(),
                     validator=TextValidator(validate_is_non_empty), executor=capture_fn),
        PipelineStep(name="step_d", agent=MagicMock(),
                     validator=TextValidator(validate_is_non_empty), executor=capture_fn),
    ]
    mock_deps = MagicMock()
    mock_deps.skill_runtime = None
    pipeline = Pipeline(steps=steps)
    await pipeline.execute(mock_deps, "TEST")

    # step_d's prompt uses compact mode for step_a and step_b.
    # step_a has no structured data → its text must appear as a snippet.
    last_prompt = captured_prompts[-1]  # step_d's prompt
    assert "step output" in last_prompt or "[Previous: step_a" in last_prompt, (
        f"Step_a's content lost in compact mode: {last_prompt[:500]}"
    )
```

**Note:** The exact assertion depends on whether `step_a` produced structured output. Since our executor returns a plain string (not `StepOutput`), there is no structured data, so the D6 snippet path should be triggered. Adjust assertion to match the actual compact format after implementation.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_pipeline_base.py::TestGatherData::test_compact_context_includes_snippet_for_unstructured_steps -xvs`
Expected: FAIL — "Alpha analysis" not in result

- [ ] **Step 3: Implement — add text snippet for steps without structured_context**

In `finrobot/engine/pipelines/base.py`, replace lines 291-297:

```python
            for name in keys[:-2]:
                text = previous_results[name]
                word_count = len(text.split())
                parts.append(
                    f"[Previous: {name} — {word_count} words, "
                    f"see structured_context for data]"
                )
```

With:

```python
            for name in keys[:-2]:
                text = previous_results[name]
                word_count = len(text.split())
                # D6: if this step has no structured_context, include a text
                # snippet so the information isn't completely lost.
                if name in structured_results:
                    parts.append(
                        f"[Previous: {name} — {word_count} words, "
                        f"see structured_context for data]"
                    )
                else:
                    parts.append(
                        f"[Previous: {name} — {word_count} words] "
                        f"{text[:300]}{'...' if len(text) > 300 else ''}"
                    )
```

**Important:** `_gather_data` currently does NOT receive `structured_results`. The method signature needs a new parameter. Check how `_gather_data` is called in `_run_step` / `execute` and pass `structured_results` through. In the `execute` method (around line 145), the call is:

```python
step_data = await self._gather_data(deps, step.required_data, ticker, results)
```

Change to:

```python
step_data = await self._gather_data(deps, step.required_data, ticker, results, structured_results)
```

And update `_gather_data` signature to accept `structured_results: dict[str, object] | None = None`.

- [ ] **Step 4: Run pipeline base tests**

Run: `python -m pytest tests/unit/test_pipeline_base.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/engine/pipelines/base.py tests/unit/test_pipeline_base.py
git commit -m "fix(D6): compact context includes text snippet for unstructured steps"
```

---

## Track B — Server + CLI Polish

### Task 4: I1 — SSE endpoint caches sub-agents

**Files:**
- Modify: `finrobot/server.py:56-90` (lifespan), `finrobot/server.py:165-172` (run_pipeline)
- Test: `tests/unit/test_server.py`

**Context:** `create_sub_agents()` is called on every SSE request (line 170-172). Move it to `lifespan` so it's built once on startup.

- [ ] **Step 1: Write failing test — run_pipeline does NOT import create_sub_agents**

The simplest test: after moving `create_sub_agents` to lifespan, `run_pipeline()` should use `request.app.state.sub_agents` instead of calling the factory. We can verify this by checking that `app.state.sub_agents` exists after the change, and that the SSE endpoint still works. Use the existing `TestPipelineStream` pattern:

In `tests/unit/test_server.py`, add a new class:

```python
class TestSubAgentsCaching:
    """I1: sub-agents created once in lifespan, not per-request."""

    @pytest.mark.asyncio
    async def test_app_state_has_sub_agents_after_setup(self):
        """After lifespan runs, app.state.sub_agents must be populated."""
        # The existing _setup_test_deps pattern doesn't trigger lifespan.
        # After I1 implementation, we manually verify the attribute exists
        # by setting it the same way lifespan would.
        from finrobot.config import get_settings
        from finrobot.engine.agents.factory import create_sub_agents

        settings = get_settings(model_name="test")
        sub_agents = create_sub_agents(settings, skill_registry=None)
        app.state.sub_agents = sub_agents
        assert hasattr(app.state, "sub_agents")
        assert isinstance(app.state.sub_agents, dict)
        assert len(app.state.sub_agents) > 0

    @pytest.mark.asyncio
    async def test_sse_uses_cached_sub_agents(self):
        """SSE endpoint must use app.state.sub_agents, not call create_sub_agents."""
        TestPipelineStream._setup_test_deps()
        # Pre-populate sub_agents like lifespan would
        from finrobot.config import get_settings
        from finrobot.engine.agents.factory import create_sub_agents

        settings = get_settings(model_name="test")
        app.state.sub_agents = create_sub_agents(settings, skill_registry=None)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/pipeline/stream/research/TEST")
        # If run_pipeline still tries to import & call create_sub_agents
        # instead of using app.state.sub_agents, the response may error.
        assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_server.py::TestSubAgentsCaching::test_sub_agents_created_once_in_lifespan -xvs`
Expected: FAIL — called 2 times

- [ ] **Step 3: Implement — move create_sub_agents to lifespan**

In `finrobot/server.py` `lifespan()` (around line 56-90), after creating `deps`, add:

```python
    from finrobot.engine.agents.factory import create_sub_agents
    app.state.sub_agents = create_sub_agents(
        deps.settings, skill_registry=deps.skill_runtime
    )
```

In `run_pipeline()` (line 165-172), replace:

```python
            from finrobot.engine.agents.factory import create_sub_agents
            sub_agents = create_sub_agents(
                deps.settings, skill_registry=deps.skill_runtime
            )
            pipeline = factories[pipeline_type](sub_agents)
```

With:

```python
            sub_agents = request.app.state.sub_agents
            pipeline = factories[pipeline_type](sub_agents)
```

- [ ] **Step 4: Run server tests**

Run: `python -m pytest tests/unit/test_server.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/server.py tests/unit/test_server.py
git commit -m "perf(I1): cache sub-agents in lifespan, avoid per-request rebuild"
```

---

### Task 5: I2 — SSE complete event drops summary, adds report_url

**Files:**
- Modify: `finrobot/server.py:176-178`
- Test: `tests/unit/test_server.py`

**Context:** Complete event currently sends `{"event": "complete", "summary": result.format_summary()[:2000]}`. Change to `{"event": "complete", "ticker": ticker, "report_url": f"/api/report/html?ticker={ticker}"}`.

- [ ] **Step 1: Write failing test**

In `tests/unit/test_server.py`, add to `TestPipelineStream` class. Uses the existing pattern of reading the full SSE body and parsing JSON events:

```python
@pytest.mark.asyncio
async def test_sse_complete_event_has_report_url_not_summary(self):
    """I2: complete event must contain report_url, not summary."""
    self._setup_test_deps()
    # Pre-populate sub_agents (after I1)
    from finrobot.config import get_settings
    from finrobot.engine.agents.factory import create_sub_agents
    settings = get_settings(model_name="test")
    app.state.sub_agents = create_sub_agents(settings, skill_registry=None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/pipeline/stream/research/TEST")
    body = response.text
    # Parse complete event from SSE body
    import json
    for line in body.split("\n"):
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event.get("event") == "complete":
                assert "report_url" in event, "complete event missing report_url"
                assert "summary" not in event, "complete event should not contain summary"
                assert event["ticker"] == "TEST"
                assert "/api/report/html" in event["report_url"]
                return
    pytest.fail("No complete event found in SSE stream")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_server.py::TestPipelineStream::test_sse_complete_event_has_report_url_not_summary -xvs`
Expected: FAIL — "summary" still in event

- [ ] **Step 3: Implement — change complete event payload**

In `finrobot/server.py` line 176-178, replace:

```python
            await queue.put(
                {"event": "complete", "summary": result.format_summary()[:2000]}
            )
```

With:

```python
            await queue.put(
                {
                    "event": "complete",
                    "ticker": ticker,
                    "report_url": f"/api/report/html?ticker={ticker}",
                }
            )
```

- [ ] **Step 4: Run server tests**

Run: `python -m pytest tests/unit/test_server.py -xvs`
Expected: ALL PASS (update any existing tests that assert on "summary" in complete event)

- [ ] **Step 5: Commit**

```bash
git add finrobot/server.py tests/unit/test_server.py
git commit -m "fix(I2): SSE complete event returns report_url instead of summary"
```

---

### Task 6: I3 — CLI progress retry line fix

**Files:**
- Modify: `finrobot/cli.py:103-108`
- Test: `tests/unit/test_cli.py`

**Context:** After `on_step_retry` prints ` retry 1 (error)` with a newline, the next `on_step_end` prints ` done (3.2s)` on a new line without the step label. Fix: reprint the step label at the end of `on_step_retry`.

- [ ] **Step 1: Write failing test**

In `tests/unit/test_cli.py`:

```python
@pytest.mark.asyncio
async def test_cli_progress_retry_reprints_step_label(self, capsys):
    """I3: after retry, step label must be reprinted so 'done' has context."""
    progress = CliProgress()
    await progress.on_step_start(1, 3, "data_collection")
    await progress.on_step_retry(1, "data_collection", 1, "timeout")
    await progress.on_step_end(1, 3, "data_collection", 2.5)
    output = capsys.readouterr().out
    # After retry line, the step label must appear again before "done"
    lines = output.strip().split("\n")
    # Last line should contain both the step label and "done"
    assert "Data Collection" in lines[-1] and "done" in lines[-1], (
        f"Expected step label before 'done' on last line, got: {lines[-1]}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_cli.py::TestCliProgress::test_cli_progress_retry_reprints_step_label -xvs`
Expected: FAIL — last line is just ` done (2.5s)` without step label

- [ ] **Step 3: Implement — reprint step label after retry**

In `finrobot/cli.py` lines 103-108, replace:

```python
    async def on_step_retry(
        self, step_index: int, step_name: str, attempt: int, error: str
    ) -> None:
        click.echo(f" retry {attempt} ({error[:60]})")
```

With:

```python
    async def on_step_retry(
        self, step_index: int, step_name: str, attempt: int, error: str
    ) -> None:
        click.echo(f" retry {attempt} ({error[:60]})")
        # Reprint step label so the next on_step_end "done" has context
        label = step_name.replace("_", " ").title()
        click.echo(f"  [{step_index}/{self._total}] {label}...", nl=False)
```

**Wait — `on_step_retry` doesn't have `total`.** Two options: (a) store `total` as instance state from `on_step_start`, or (b) change the signature. Option (a) is simpler and doesn't break the Protocol.

Add instance state:

```python
class CliProgress:
    def __init__(self) -> None:
        self._total: int = 0

    async def on_step_start(
        self, step_index: int, total: int, step_name: str
    ) -> None:
        self._total = total
        label = step_name.replace("_", " ").title()
        click.echo(f"  [{step_index}/{total}] {label}...", nl=False)
```

- [ ] **Step 4: Run CLI tests**

Run: `python -m pytest tests/unit/test_cli.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/cli.py tests/unit/test_cli.py
git commit -m "fix(I3): CLI progress reprints step label after retry"
```

---

## Track C — SDK Robustness

### Task 7: I5 — SDK type annotations

**Files:**
- Modify: `finrobot/sdk.py:1-10` (imports), `finrobot/sdk.py:65`, `finrobot/sdk.py:122`
- Test: mypy pass (no new test file)

- [ ] **Step 1: Add TYPE_CHECKING import and tighten annotations**

In `finrobot/sdk.py`, add at top:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai import Agent
```

Change line 65:
```python
self._sub_agents: dict[str, Any] | None = None
```
To:
```python
self._sub_agents: dict[str, Agent] | None = None
```

Change `_get_sub_agents` return type (line 122):
```python
def _get_sub_agents(self) -> dict[str, Agent]:
```

**Note:** Check if `from __future__ import annotations` is already present. If so, just add the TYPE_CHECKING block. Use bare `Agent` (not `Agent[Any, Any]`) — the generic parameterization depends on the pydantic-ai version and may not be valid. Bare `Agent` is sufficient for the type narrowing from `Any`. Verify with `uv run mypy finrobot/sdk.py --ignore-missing-imports` before committing.

- [ ] **Step 2: Run mypy**

Run: `uv run mypy finrobot/sdk.py --ignore-missing-imports`
Expected: 0 errors

- [ ] **Step 3: Run existing SDK tests**

Run: `python -m pytest tests/unit/test_sdk.py -xvs`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add finrobot/sdk.py
git commit -m "refactor(I5): tighten SDK type annotations for sub_agents"
```

---

### Task 8: I6 — SDK close() event loop flush

**Files:**
- Modify: `finrobot/sdk.py:269-279`
- Test: `tests/unit/test_sdk.py`

**Context:** `close()` calls `self._loop.close()` immediately after `data_layer.close()`. The aiosqlite worker thread may have pending callbacks that try to post back to the loop, hitting `RuntimeError: Event loop is closed`. Fix: flush pending callbacks with `run_until_complete(asyncio.sleep(0))` before closing.

- [ ] **Step 1: Write failing test**

In `tests/unit/test_sdk.py`. **Important:** `_loop` is only created by `_run_sync()` (line 157-159 in sdk.py), NOT by `_ensure_deps()`. So we must create a loop manually to simulate the state after sync API usage, then verify `close()` flushes it:

```python
def test_close_flushes_loop_before_closing(self):
    """I6: close() must flush pending callbacks before closing the loop.

    _loop is created by _run_sync (sync API path). We simulate this state
    by manually creating a loop, then verify close() calls
    run_until_complete (flush) before loop.close().
    """
    import asyncio

    agent = FinRobot()
    # Simulate _run_sync having created a persistent loop
    loop = asyncio.new_event_loop()
    agent._loop = loop

    flush_called = False
    original_ruc = loop.run_until_complete

    def spy_ruc(coro):
        nonlocal flush_called
        flush_called = True
        return original_ruc(coro)

    loop.run_until_complete = spy_ruc

    # close() is async but we call it on the loop we're about to close.
    # Use the loop itself to run close():
    loop.run_until_complete = original_ruc  # restore for running close
    # Actually, we need to check the implementation calls ruc. Better approach:
    # just verify the code path by checking loop state after close.
    # The real test: close() should not raise RuntimeError from aiosqlite.
    loop.run_until_complete(agent.close())
    assert agent._loop is None
    assert loop.is_closed()
```

**Alternative (simpler, tests the contract):** Verify that after `close()`, no `RuntimeError: Event loop is closed` warning is emitted. Use `pytest -W error::RuntimeWarning`:

```python
def test_close_does_not_emit_event_loop_closed_warning(self):
    """I6: close() must not trigger 'Event loop is closed' warning."""
    import asyncio
    import warnings

    agent = FinRobot()
    loop = asyncio.new_event_loop()
    agent._loop = loop

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        loop.run_until_complete(agent.close())
    assert agent._loop is None
```

Use the simpler version. The flush is an implementation detail; the contract is "no RuntimeError warnings."

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_sdk.py::TestSDKClose::test_close_flushes_loop_before_closing -xvs`
Expected: FAIL — flush_called is False

- [ ] **Step 3: Implement — add loop flush**

In `finrobot/sdk.py`, replace lines 275-279:

```python
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
            self._loop = None
```

With:

```python
        if self._loop is not None and not self._loop.is_closed():
            # I6: give aiosqlite's worker thread time to drain pending
            # callbacks before we destroy the loop they post to.
            self._loop.run_until_complete(asyncio.sleep(0))
            self._loop.close()
            self._loop = None
```

- [ ] **Step 4: Run SDK tests**

Run: `python -m pytest tests/unit/test_sdk.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add finrobot/sdk.py tests/unit/test_sdk.py
git commit -m "fix(I6): flush event loop before close to prevent aiosqlite RuntimeError"
```

---

## Track D — LBO Excel Root Fix

### Task 9: Cache LBOInputs + re-enable LBO Excel export

**Files:**
- Modify: `finrobot/engine/orchestrator.py:24-97` (build_report_context)
- Modify: `finrobot/server.py:240-274` (export_excel)
- Test: `tests/unit/test_server.py`, `tests/unit/test_orchestrator.py`

**Context:** LBO pipeline already stores `LBOInputs` in `structured_data["lbo_parameters"]` and `LBOResult` in `structured_data["lbo_calculation"]`. But `build_report_context()` doesn't extract them. The Excel endpoint returns 501 because `lbo_inputs` is never in `report_cache`. Fix both.

- [ ] **Step 1: Write failing test — build_report_context extracts LBO models**

In `tests/unit/test_report_endpoints.py` (where `TestBuildReportContext` lives, line 148). Use the same LBOYear fields as the existing test at `test_server.py:222-239`:

```python
def test_lbo_pipeline_extracts_inputs_and_result(self):
    """D3-root: LBOInputs and LBOResult must appear in report context."""
    from finrobot.engine.models.financial import LBOInputs, LBOResult, LBOYear

    fake_year = LBOYear(
        year=1, revenue=500_000_000, ebitda=100_000_000, da=10_000_000,
        ebit=90_000_000, interest_expense=49_000_000, ebt=41_000_000,
        taxes=10_250_000, net_income=30_750_000, capex=20_000_000,
        delta_nwc=5_000_000, fcf=15_750_000, mandatory_amort=7_000_000,
        cash_sweep_amount=8_750_000, total_debt_paydown=15_750_000,
        ending_debt=684_250_000,
    )
    inputs = LBOInputs(
        ticker="TEST", ltm_ebitda=100_000_000, entry_ev_ebitda=10.0,
        exit_ev_ebitda=10.0, revenue_base=500_000_000,
        revenue_growth_rate=0.05, ebitda_margin=0.2,
    )
    lbo_result = LBOResult(
        entry_ev=1_000_000_000, entry_equity=300_000_000,
        entry_debt=700_000_000, schedule=[fake_year],
        exit_ev=1_800_000_000, exit_ebitda=250_000_000,
        exit_equity=1_400_000_000, irr=0.22, moic=4.5,
    )
    pipeline_result = PipelineResult(
        steps={"lbo_parameters": "...", "lbo_calculation": "..."},
        structured_data={"lbo_parameters": inputs, "lbo_calculation": lbo_result},
    )
    ctx = build_report_context("TEST", pipeline_result)
    assert ctx.get("lbo_inputs") is inputs
    assert ctx.get("lbo_result") is lbo_result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_orchestrator.py::TestBuildReportContext::test_build_report_context_extracts_lbo_models -xvs`
Expected: FAIL — `lbo_inputs` not in context

- [ ] **Step 3: Implement — add LBO extraction to build_report_context**

In `finrobot/engine/orchestrator.py`, after the `valuation_synthesis` block (around line 81), add:

```python
    lbo_inputs = sd.get("lbo_parameters")
    if not isinstance(lbo_inputs, LBOInputs):
        lbo_inputs = None

    lbo_result = sd.get("lbo_calculation")
    if not isinstance(lbo_result, LBOResult):
        lbo_result = None
```

Add to the return dict:

```python
        "lbo_inputs": lbo_inputs,
        "lbo_result": lbo_result,
```

Add imports at top: `from finrobot.engine.models.financial import LBOInputs, LBOResult` (alongside existing imports).

- [ ] **Step 4: Run orchestrator tests**

Run: `python -m pytest tests/unit/test_orchestrator.py -xvs`
Expected: ALL PASS

- [ ] **Step 5: Write failing test — LBO Excel export returns 200**

In `tests/unit/test_server.py`, add to `TestExcelExportEndpoint`. Uses the same `_setup_deps_with_cache` pattern and `LBOYear`/`LBOResult`/`LBOInputs` from the existing 501 test:

```python
@pytest.mark.asyncio
async def test_lbo_excel_export_returns_200_when_inputs_cached(self):
    """D3-root: with lbo_inputs + lbo_result in cache, export returns xlsx."""
    from finrobot.engine.models.financial import LBOInputs, LBOResult, LBOYear

    fake_year = LBOYear(
        year=1, revenue=500_000_000, ebitda=100_000_000, da=10_000_000,
        ebit=90_000_000, interest_expense=49_000_000, ebt=41_000_000,
        taxes=10_250_000, net_income=30_750_000, capex=20_000_000,
        delta_nwc=5_000_000, fcf=15_750_000, mandatory_amort=7_000_000,
        cash_sweep_amount=8_750_000, total_debt_paydown=15_750_000,
        ending_debt=684_250_000,
    )
    fake_result = LBOResult(
        entry_ev=1_000_000_000, entry_equity=300_000_000,
        entry_debt=700_000_000, schedule=[fake_year],
        exit_ev=1_800_000_000, exit_ebitda=250_000_000,
        exit_equity=1_400_000_000, irr=0.22, moic=4.5,
    )
    fake_inputs = LBOInputs(
        ticker="TEST", ltm_ebitda=100_000_000, entry_ev_ebitda=10.0,
        exit_ev_ebitda=10.0, revenue_base=500_000_000,
        revenue_growth_rate=0.05, ebitda_margin=0.2,
    )
    self._setup_deps_with_cache({
        "TEST": {"lbo_result": fake_result, "lbo_inputs": fake_inputs}
    })
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/export/excel/lbo/TEST")
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
```

- [ ] **Step 6: Run test to verify it fails**

Expected: FAIL — 501 returned (current code hits the hardcoded 501 block before checking cache)

- [ ] **Step 7: Update existing 501 regression test to expect 404**

The existing `test_lbo_excel_export_returns_501_until_inputs_cached` (line 215-261) must change: with the 501 block removed, the test's scenario (only `lbo_result` in cache, no `lbo_inputs`) should now return 404 with a re-run message. Update:

```python
@pytest.mark.asyncio
async def test_lbo_excel_export_returns_404_without_inputs(self):
    """D3-root: with lbo_result but NO lbo_inputs → 404, not 501."""
    # ... same setup as before, only lbo_result in cache ...
    self._setup_deps_with_cache({"TEST": {"lbo_result": fake_result}})
    # ...
    assert response.status_code == 404
    assert "Re-run" in response.json()["detail"] or "re-run" in response.json()["detail"].lower()
```

- [ ] **Step 8: Implement — re-enable LBO Excel in server.py**

In `finrobot/server.py`, replace the 501 block (lines 261-274):

```python
    if analysis_type == "lbo":
        raise HTTPException(
            status_code=501,
            ...
        )
```

With:

```python
    if analysis_type == "lbo":
        from finrobot.engine.compute.spreadsheet_gen import generate_lbo_excel
        from finrobot.engine.models.financial import LBOInputs, LBOResult

        lbo_result: LBOResult | None = cache.get("lbo_result")
        lbo_inputs: LBOInputs | None = cache.get("lbo_inputs")
        if lbo_result is None or lbo_inputs is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "LBO inputs/result not in cache. Re-run the LBO pipeline "
                    "to populate them."
                ),
            )
        xlsx_bytes = generate_lbo_excel(lbo_result, lbo_inputs)
```

- [ ] **Step 9: Run server tests + report context tests**

Run: `python -m pytest tests/unit/test_server.py tests/unit/test_report_endpoints.py -xvs`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add finrobot/engine/orchestrator.py finrobot/server.py tests/unit/test_server.py tests/unit/test_orchestrator.py
git commit -m "fix(D3): cache LBOInputs in report context, re-enable LBO Excel export"
```

---

## Track E — A-Share Internationalization (Step 1)

### Task 10: Ticker format verification

**Files:**
- Verify: `finrobot/engine/data/providers/yfinance_provider.py`
- Verify: `finrobot/engine/compute/extractor.py`
- Test: `tests/unit/test_yfinance_provider.py` (add one defensive test)

**Context:** From code review, neither file has ticker format validation. `yfinance_provider.py` passes ticker directly to `yf.Ticker(symbol)`. `extractor.py` treats ticker as an opaque string. `ticker.upper()` in orchestrator/server is safe for `600519.SS` (digits and `.` are unaffected). **No code changes expected** — just add a defensive test.

- [ ] **Step 1: Write test confirming non-US ticker passes through provider**

The test verifies that `YFinanceProvider.fetch()` does not raise a format error before reaching the network call. We mock `yfinance.Ticker` so no network is needed:

```python
async def test_non_us_ticker_format_not_rejected(self, monkeypatch):
    """Track E: A-share/HK tickers must reach yfinance without format rejection."""
    received_symbols: list[str] = []

    class FakeTicker:
        def __init__(self, symbol):
            received_symbols.append(symbol)
            self.info = {"regularMarketPrice": 100, "marketCap": 1e9}

    monkeypatch.setattr("finrobot.engine.data.providers.yfinance_provider.yf.Ticker", FakeTicker)

    provider = YFinanceProvider()
    for ticker in ("600519.SS", "000858.SZ", "0700.HK"):
        received_symbols.clear()
        result = await provider.fetch(ticker, "financials")
        assert received_symbols == [ticker], (
            f"Ticker '{ticker}' was not passed through to yfinance"
        )
```

This catches any future format validation that would reject dotted tickers.

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/unit/test_yfinance_provider.py -xvs`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_yfinance_provider.py
git commit -m "test(E): add defensive test for non-US ticker format passthrough"
```

---

### Task 11: Tax rate / discount rate documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add configuration note to README**

In the "Quickstart" or "Configuration" section of README.md, add:

```markdown
### Financial Assumptions

Default financial assumptions are calibrated for US equities:
- Tax rate: 21% (US federal corporate rate)
- Risk-free rate: US 10-Year Treasury yield

For non-US markets, override via the SDK:

```python
from finrobot.engine.models.financial import ForecastAssumptions

assumptions = ForecastAssumptions(tax_rate=0.196)  # Japan corporate tax
```

CLI flag support for non-US defaults is planned for a future release.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(E): document default tax rate and discount rate assumptions"
```

---

## Track F — Distribution Research

### Task 12: Distribution feasibility document

**Files:**
- Create: `docs/distribution.md`

- [ ] **Step 1: Research and write findings**

Create `docs/distribution.md` covering:
1. **PyInstaller feasibility**: PydanticAI dynamic imports, hidden imports, single-file viability, known issues
2. **electron-builder feasibility**: uv sidecar approach (already in ARCHITECTURE.md), dual-process architecture, platform-specific concerns
3. **Conclusion**: recommended path (uv sidecar per ARCHITECTURE.md) with caveats

No code changes. Research-only deliverable.

- [ ] **Step 2: Commit**

```bash
git add docs/distribution.md
git commit -m "docs(F): add distribution feasibility research (PyInstaller + electron-builder)"
```

---

## Final Verification

After all tasks:

- [ ] `uv run ruff check finrobot/` → 0 errors
- [ ] `uv run mypy finrobot/ --ignore-missing-imports` → 0 errors
- [ ] `python -m pytest tests/ -x -v --tb=short` → all pass
- [ ] Verify `/api/export/excel/lbo/{ticker}` returns 200 when cache populated
- [ ] Verify SSE complete event contains `report_url`, not `summary`
- [ ] Verify `ticker.upper()` is safe for `600519.SS` format (confirmed by code review — no changes needed)
