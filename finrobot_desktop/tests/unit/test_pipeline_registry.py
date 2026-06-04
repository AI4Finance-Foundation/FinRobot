"""Tests for the pipeline registry (BUG-025).

The registry is the single source of truth for the pipeline set across all four
execution paths (Mode A chat tools, REST runs, CLI, SDK). These tests pin the
PipelineSpec shape, the lazy-import contract that the module exists to enforce,
and the key↔factory↔tool-name mapping.
"""

from __future__ import annotations

import sys

import pytest

from finrobot.engine.pipelines.registry import (
    PipelineSpec,
    get_pipeline_factories,
    get_pipeline_spec,
    iter_pipeline_specs,
)

# The canonical pipeline set. If a pipeline is added/removed, this list (and the
# registry) change together — that is the whole point of the consolidation.
EXPECTED_KEYS = {"research", "comps", "dcf", "ddm", "lbo", "earnings", "ic-memo"}


class TestSpecShape:
    def test_iter_returns_specs(self):
        specs = iter_pipeline_specs()
        assert specs, "registry returned no specs"
        assert all(isinstance(s, PipelineSpec) for s in specs)

    def test_keys_are_the_canonical_set(self):
        assert {s.key for s in iter_pipeline_specs()} == EXPECTED_KEYS

    def test_every_spec_has_non_empty_metadata(self):
        for spec in iter_pipeline_specs():
            assert spec.key
            assert spec.import_path and ":" in spec.import_path
            assert spec.tool_name
            assert spec.tool_description and spec.tool_description.strip()

    def test_tool_names_are_unique_and_valid_identifiers(self):
        names = [s.tool_name for s in iter_pipeline_specs()]
        assert len(names) == len(set(names)), "duplicate tool names"
        for name in names:
            assert name.isidentifier(), f"{name!r} is not a valid tool identifier"

    def test_spec_is_frozen(self):
        spec = iter_pipeline_specs()[0]
        with pytest.raises(Exception):
            spec.key = "mutated"  # type: ignore[misc]


class TestKeyToolNameMapping:
    def test_ic_memo_key_maps_to_hyphenless_tool_name(self):
        # The hyphen in the key would be illegal in a tool identifier, so the
        # tool name is stored explicitly rather than derived from the key.
        spec = get_pipeline_spec("ic-memo")
        assert spec.tool_name == "run_ic_memo"
        assert "-" not in spec.tool_name

    def test_get_pipeline_spec_unknown_key_raises(self):
        with pytest.raises(KeyError):
            get_pipeline_spec("does-not-exist")


class TestLazyImport:
    def test_importing_registry_does_not_eager_import_pipelines(self):
        """The module exists to break server→web→tasks circular imports — it
        must NOT import any create_*_pipeline module at module-load time."""
        # Re-import the registry fresh and confirm no pipeline impl modules got
        # pulled in *by the registry itself*. (Other tests in the session may
        # already have imported them; assert on a sub-process for isolation.)
        import subprocess

        code = (
            "import sys; import finrobot.engine.pipelines.registry as r; "
            "leaked=[m for m in sys.modules if any(k in m for k in "
            "('equity_research','pipelines.comps','pipelines.dcf','pipelines.ddm',"
            "'pipelines.lbo','earnings_analysis','ic_memo'))]; "
            "print('LEAK' if leaked else 'CLEAN')"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert out.stdout.strip() == "CLEAN", out.stdout

    def test_factory_is_importable_and_callable(self):
        # Accessing .factory triggers the lazy import and returns the real
        # create_*_pipeline callable.
        spec = get_pipeline_spec("dcf")
        factory = spec.factory
        assert callable(factory)
        assert factory.__name__ == "create_dcf_pipeline"

    def test_factory_is_cached(self):
        spec = get_pipeline_spec("dcf")
        assert spec.factory is spec.factory


class TestFactoriesView:
    def test_factories_map_matches_specs(self):
        factories = get_pipeline_factories()
        assert set(factories) == {s.key for s in iter_pipeline_specs()}

    def test_factories_values_match_spec_factories(self):
        factories = get_pipeline_factories()
        for spec in iter_pipeline_specs():
            assert factories[spec.key] is spec.factory

    def test_factories_cached_across_calls(self):
        assert get_pipeline_factories() is get_pipeline_factories()
