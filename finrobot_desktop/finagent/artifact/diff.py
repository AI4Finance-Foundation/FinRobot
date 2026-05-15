"""Field-level diff between two Artifacts.

Recursively walks the assumption + output + compute_version sections,
skipping meta (timestamps/ids differ by design) and inputs.raw_data
(too large; raw diff is a separate concern).

Numeric diffs carry both absolute change and percentage change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from finagent.artifact.models import Artifact

# Sections to skip entirely (always differ or too large to diff usefully)
_SKIP_TOP_LEVEL = {"meta", "id"}
_SKIP_INPUTS_KEYS = {"raw_data"}


class FieldDiff(BaseModel):
    """One field difference between two artifacts."""

    path: str  # e.g. "assumptions.parameters.wacc"
    old: Any
    new: Any
    kind: Literal["added", "removed", "changed"]
    abs_change: float | None = None  # set when both values are numeric
    pct_change: float | None = None  # set when old is nonzero numeric


def _collect_diffs(
    old_val: Any,
    new_val: Any,
    path: str,
    diffs: list[FieldDiff],
) -> None:
    """Recursively collect field diffs between old_val and new_val."""
    if isinstance(old_val, dict) and isinstance(new_val, dict):
        all_keys = old_val.keys() | new_val.keys()
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key in old_val and key in new_val:
                _collect_diffs(old_val[key], new_val[key], child_path, diffs)
            elif key in old_val:
                diffs.append(FieldDiff(path=child_path, old=old_val[key], new=None, kind="removed"))
            else:
                diffs.append(FieldDiff(path=child_path, old=None, new=new_val[key], kind="added"))
    elif isinstance(old_val, list) and isinstance(new_val, list):
        # Diff list elements by index
        for i, (ov, nv) in enumerate(zip(old_val, new_val)):
            _collect_diffs(ov, nv, f"{path}[{i}]", diffs)
        # Extra items in longer list
        if len(old_val) > len(new_val):
            for i in range(len(new_val), len(old_val)):
                diffs.append(
                    FieldDiff(path=f"{path}[{i}]", old=old_val[i], new=None, kind="removed")
                )
        elif len(new_val) > len(old_val):
            for i in range(len(old_val), len(new_val)):
                diffs.append(FieldDiff(path=f"{path}[{i}]", old=None, new=new_val[i], kind="added"))
    else:
        if old_val != new_val:
            diff = FieldDiff(path=path, old=old_val, new=new_val, kind="changed")
            # Enrich numeric diffs with absolute + pct change
            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                diff.abs_change = float(new_val) - float(old_val)
                if old_val != 0:
                    diff.pct_change = diff.abs_change / abs(float(old_val))
            diffs.append(diff)


def diff_artifacts(a: Artifact, b: Artifact) -> list[FieldDiff]:
    """Recursively compare two artifacts and return field-level diffs.

    Skipped sections:
    - ``meta``: id, timestamps, and user info will always differ.
    - ``id``: top-level artifact id always differs.
    - ``inputs.raw_data``: large blob; use a dedicated raw-diff endpoint.

    The comparison focuses on the scientifically meaningful sections:
    - ``assumptions`` (parameter choices)
    - ``outputs`` (computed results)
    - ``compute_version`` (which formula was used)
    - ``inputs`` except raw_data (data source, fetch time)

    Args:
        a: The "before" artifact (old).
        b: The "after" artifact (new).

    Returns:
        List of FieldDiff objects, sorted by path.

    Example:
        >>> diffs = diff_artifacts(v1, v2)
        >>> for d in diffs:
        ...     print(f"{d.path}: {d.old!r} → {d.new!r}")
    """
    a_dict = a.model_dump(mode="python")
    b_dict = b.model_dump(mode="python")

    diffs: list[FieldDiff] = []

    for section in sorted(a_dict.keys()):
        if section in _SKIP_TOP_LEVEL:
            continue

        if section == "inputs":
            # Diff inputs but skip raw_data
            a_inp = {k: v for k, v in a_dict["inputs"].items() if k not in _SKIP_INPUTS_KEYS}
            b_inp = {k: v for k, v in b_dict["inputs"].items() if k not in _SKIP_INPUTS_KEYS}
            _collect_diffs(a_inp, b_inp, "inputs", diffs)
            continue

        _collect_diffs(a_dict.get(section), b_dict.get(section), section, diffs)

    diffs.sort(key=lambda d: d.path)
    return diffs
