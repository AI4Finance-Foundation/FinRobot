"""Extractor pulls entry/target/target_date out of full Artifacts (v5 ADR-0001)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from finagent.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finagent.artifact.store import _summary_from_artifact
from finagent.artifact.summary_extractor import (
    extract_entry_price,
    extract_target_date,
    extract_target_price,
)

UTC = timezone.utc
CREATED = datetime(2026, 5, 1, tzinfo=UTC)


def _artifact(
    *,
    raw_data: dict | None = None,
    structured: dict | None = None,
    type_: str = "equity_research",
) -> Artifact:
    return Artifact(
        id="art_2026-05-01T00:00:00_NVDA_equity_research",
        ticker="NVDA",
        cross_tickers=[],
        type=type_,  # type: ignore[arg-type]
        inputs=ArtifactInputs(
            data_source="yfinance",
            data_fetched_at=CREATED,
            raw_data=raw_data or {},
        ),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="x"),
        outputs=ArtifactOutputs(structured=structured or {}, summary_text="head"),
        meta=ArtifactMeta(created_at=CREATED, source="pipeline:equity_research"),
    )


def test_entry_price_extracted_from_financialdata_raw_dump() -> None:
    art = _artifact(raw_data={"market": {"current_price": 876.42}})
    assert extract_entry_price(art) == 876.42


def test_entry_price_none_when_market_missing() -> None:
    assert extract_entry_price(_artifact(raw_data={})) is None


def test_entry_price_none_when_value_non_positive() -> None:
    art = _artifact(raw_data={"market": {"current_price": 0}})
    assert extract_entry_price(art) is None


def test_target_price_from_equity_research_thesis_block() -> None:
    art = _artifact(structured={"thesis": {"price_target": 920.0}})
    assert extract_target_price(art) == 920.0


def test_target_price_from_dcf_implied_price_nested() -> None:
    art = _artifact(
        structured={"financial_modeling": {"implied_price": 185.4}},
        type_="dcf",
    )
    assert extract_target_price(art) == 185.4


def test_target_price_from_top_level_implied_price() -> None:
    art = _artifact(structured={"implied_price": 42.0}, type_="lbo")
    assert extract_target_price(art) == 42.0


def test_target_price_none_when_structured_empty() -> None:
    assert extract_target_price(_artifact(structured={})) is None


def test_target_date_defaults_to_created_at_plus_365_when_present() -> None:
    art = _artifact(structured={"thesis": {"price_target": 920.0}})
    expected = CREATED + timedelta(days=365)
    assert extract_target_date(art, 920.0) == expected


def test_target_date_honours_explicit_thesis_date_iso_string() -> None:
    art = _artifact(
        structured={"thesis": {"price_target": 920.0, "target_date": "2027-01-15T00:00:00+00:00"}}
    )
    out = extract_target_date(art, 920.0)
    assert out == datetime(2027, 1, 15, tzinfo=UTC)


def test_target_date_none_when_no_target_price() -> None:
    assert extract_target_date(_artifact(), None) is None


def test_summary_from_artifact_carries_new_v5_fields() -> None:
    art = _artifact(
        raw_data={"market": {"current_price": 876.42}},
        structured={"thesis": {"price_target": 920.0}},
    )
    s = _summary_from_artifact(art)
    assert s.entry_price == 876.42
    assert s.target_price == 920.0
    assert s.target_date == CREATED + timedelta(days=365)
    assert s.signal is None  # always lazy — routes attach it


def test_summary_from_legacy_artifact_keeps_v5_fields_none() -> None:
    s = _summary_from_artifact(_artifact())
    assert s.entry_price is None
    assert s.target_price is None
    assert s.target_date is None
    assert s.signal is None
