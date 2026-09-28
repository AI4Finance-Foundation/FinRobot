"""Tests for Pipeline._gather_data compact-context mode (Track 5 Task 13).

When required_data is empty, _gather_data should pass the last 2 steps' full
text + 1-line summaries of earlier steps. This reduces prompt size by 40-60%
for 5+ step pipelines while preserving enough context for common downstream
patterns (step N often reads from step N-1 and N-2).
"""

from finrobot.engine.pipelines.base import Pipeline


async def test_gather_data_last_two_steps():
    """With 4 completed steps, _gather_data returns last 2 full + 2 summaries."""
    pipeline = Pipeline(steps=[])
    results = {
        "step1": "output1 body text",
        "step2": "output2 body text",
        "step3": "output3 body text",
        "step4": "output4 body text",
    }
    # deps unused when required_data=[]; None is fine
    gathered = await pipeline._gather_data(None, [], "TEST", results)

    # Last 2 steps: full text
    assert "step3" in gathered and "output3 body text" in gathered
    assert "step4" in gathered and "output4 body text" in gathered
    # Earlier steps: summary lines with text snippet (D6: steps without
    # structured data include first 300 chars so info isn't lost)
    assert "[Previous: step1" in gathered
    assert "[Previous: step2" in gathered
    # D6: text snippet IS included for steps without structured data
    assert "output1 body text" in gathered
    assert "output2 body text" in gathered


async def test_gather_data_two_steps_both_full():
    """With exactly 2 steps, both are included in full."""
    pipeline = Pipeline(steps=[])
    results = {"step1": "output1 body", "step2": "output2 body"}
    gathered = await pipeline._gather_data(None, [], "TEST", results)
    assert "output1 body" in gathered
    assert "output2 body" in gathered
    # No summary line since nothing was elided
    assert "[Previous: step1" not in gathered
    assert "[Previous: step2" not in gathered


async def test_gather_data_one_step_full():
    """With 1 step, it's included in full."""
    pipeline = Pipeline(steps=[])
    results = {"step1": "only output body"}
    gathered = await pipeline._gather_data(None, [], "TEST", results)
    assert "only output body" in gathered
    assert "step1" in gathered
