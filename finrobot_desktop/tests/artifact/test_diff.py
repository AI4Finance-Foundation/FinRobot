"""Tests for finagent.artifact.diff.diff_artifacts.

Coverage:
- Identical artifacts → empty diff
- Changed scalar field → kind="changed" with abs/pct enrichment
- Added key in dict → kind="added"
- Removed key in dict → kind="removed"
- Nested path is correctly built (e.g. assumptions.parameters.wacc)
- Meta and raw_data are skipped
- List element diffs carry index notation [0], [1], ...
- Numeric diffs carry abs_change and pct_change
"""

from __future__ import annotations

import pytest

from finagent.artifact.diff import FieldDiff, diff_artifacts
from finagent.artifact.models import Artifact


def _diff_dict(diffs: list[FieldDiff]) -> dict[str, FieldDiff]:
    return {d.path: d for d in diffs}


class TestIdentical:
    def test_same_artifact_returns_empty_diff(self, sample_artifact: Artifact) -> None:
        diffs = diff_artifacts(sample_artifact, sample_artifact)
        assert diffs == []

    def test_copy_artifact_returns_empty_diff(self, sample_artifact: Artifact) -> None:
        copy = sample_artifact.model_copy(deep=True)
        diffs = diff_artifacts(sample_artifact, copy)
        assert diffs == []


class TestChangedFields:
    def test_wacc_changed(self, sample_artifact: Artifact, sample_artifact_v2: Artifact) -> None:
        diffs = diff_artifacts(sample_artifact, sample_artifact_v2)
        by_path = _diff_dict(diffs)

        wacc_diff = by_path.get("assumptions.parameters.wacc")
        assert wacc_diff is not None
        assert wacc_diff.kind == "changed"
        assert wacc_diff.old == pytest.approx(0.082)
        assert wacc_diff.new == pytest.approx(0.095)

    def test_implied_price_changed(
        self, sample_artifact: Artifact, sample_artifact_v2: Artifact
    ) -> None:
        diffs = diff_artifacts(sample_artifact, sample_artifact_v2)
        by_path = _diff_dict(diffs)

        price_diff = by_path.get("outputs.structured.implied_price")
        assert price_diff is not None
        assert price_diff.old == pytest.approx(185.0)
        assert price_diff.new == pytest.approx(162.0)
        assert price_diff.kind == "changed"

    def test_numeric_diff_has_abs_and_pct_change(
        self, sample_artifact: Artifact, sample_artifact_v2: Artifact
    ) -> None:
        diffs = diff_artifacts(sample_artifact, sample_artifact_v2)
        by_path = _diff_dict(diffs)

        wacc_diff = by_path["assumptions.parameters.wacc"]
        assert wacc_diff.abs_change is not None
        assert wacc_diff.abs_change == pytest.approx(0.095 - 0.082)
        assert wacc_diff.pct_change is not None
        assert wacc_diff.pct_change == pytest.approx((0.095 - 0.082) / 0.082)

    def test_string_diff_has_no_pct_change(self, sample_artifact: Artifact) -> None:
        b = sample_artifact.model_copy(deep=True)
        b.compute_version.formula_id = "dcf_standard_v2"

        diffs = diff_artifacts(sample_artifact, b)
        by_path = _diff_dict(diffs)

        fid_diff = by_path.get("compute_version.formula_id")
        assert fid_diff is not None
        assert fid_diff.kind == "changed"
        assert fid_diff.old == "dcf_simplified_v1"
        assert fid_diff.new == "dcf_standard_v2"
        assert fid_diff.abs_change is None
        assert fid_diff.pct_change is None


class TestAddedRemoved:
    def test_added_key_in_parameters(self, sample_artifact: Artifact) -> None:
        b = sample_artifact.model_copy(deep=True)
        b.assumptions.parameters["new_key"] = 42.0

        diffs = diff_artifacts(sample_artifact, b)
        by_path = _diff_dict(diffs)

        added = by_path.get("assumptions.parameters.new_key")
        assert added is not None
        assert added.kind == "added"
        assert added.old is None
        assert added.new == 42.0

    def test_removed_key_in_parameters(self, sample_artifact: Artifact) -> None:
        a = sample_artifact.model_copy(deep=True)
        a.assumptions.parameters["extra_key"] = 99.0
        b = sample_artifact.model_copy(deep=True)
        # b does not have "extra_key"

        diffs = diff_artifacts(a, b)
        by_path = _diff_dict(diffs)

        removed = by_path.get("assumptions.parameters.extra_key")
        assert removed is not None
        assert removed.kind == "removed"
        assert removed.old == 99.0
        assert removed.new is None

    def test_added_warning(self, sample_artifact: Artifact) -> None:
        b = sample_artifact.model_copy(deep=True)
        b.outputs.warnings = ["Simplified FCF formula used", "New warning"]

        diffs = diff_artifacts(sample_artifact, b)
        by_path = _diff_dict(diffs)

        added = by_path.get("outputs.warnings[1]")
        assert added is not None
        assert added.kind == "added"
        assert added.new == "New warning"


class TestSkippedSections:
    def test_meta_is_skipped(self, sample_artifact: Artifact, sample_artifact_v2: Artifact) -> None:
        diffs = diff_artifacts(sample_artifact, sample_artifact_v2)
        paths = [d.path for d in diffs]
        assert not any(p.startswith("meta.") for p in paths)

    def test_artifact_id_is_skipped(
        self, sample_artifact: Artifact, sample_artifact_v2: Artifact
    ) -> None:
        diffs = diff_artifacts(sample_artifact, sample_artifact_v2)
        paths = [d.path for d in diffs]
        assert "id" not in paths

    def test_raw_data_is_skipped(self, sample_artifact: Artifact) -> None:
        b = sample_artifact.model_copy(deep=True)
        b.inputs.raw_data = {"revenue": 999_999, "extra_field": "different"}

        diffs = diff_artifacts(sample_artifact, b)
        paths = [d.path for d in diffs]
        assert not any("raw_data" in p for p in paths)

    def test_inputs_data_source_is_diffed(self, sample_artifact: Artifact) -> None:
        b = sample_artifact.model_copy(deep=True)
        b.inputs.data_source = "FMP"

        diffs = diff_artifacts(sample_artifact, b)
        by_path = _diff_dict(diffs)
        assert "inputs.data_source" in by_path


class TestNestedPath:
    def test_nested_path_is_correct(self, sample_artifact: Artifact) -> None:
        b = sample_artifact.model_copy(deep=True)
        b.assumptions.parameters["wacc"] = 0.10

        diffs = diff_artifacts(sample_artifact, b)
        by_path = _diff_dict(diffs)
        assert "assumptions.parameters.wacc" in by_path

    def test_sorted_by_path(self, sample_artifact: Artifact, sample_artifact_v2: Artifact) -> None:
        diffs = diff_artifacts(sample_artifact, sample_artifact_v2)
        paths = [d.path for d in diffs]
        assert paths == sorted(paths)
