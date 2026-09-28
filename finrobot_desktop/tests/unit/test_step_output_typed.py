from pydantic import BaseModel
from finrobot.engine.models.financial import StepOutput


class _FakeModel(BaseModel):
    value: float


def test_step_output_accepts_none():
    so = StepOutput(text="x")
    assert so.structured is None


def test_step_output_accepts_dict():
    so = StepOutput(text="x", structured={"key": "value"})
    assert so.structured == {"key": "value"}


def test_step_output_accepts_base_model():
    model = _FakeModel(value=42.0)
    so = StepOutput(text="x", structured=model)
    assert so.structured.value == 42.0


def test_step_output_structured_not_any():
    from typing import get_type_hints, Any

    hints = get_type_hints(StepOutput)
    # Should not be bare Any
    assert hints["structured"] is not Any
    # Should support object | None (our compromise to prevent Pydantic coercion)
    assert "object" in str(hints["structured"]) or "BaseModel" in str(hints["structured"])
