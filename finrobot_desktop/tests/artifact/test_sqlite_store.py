"""Contract tests for SqliteArtifactStore.

Mirrors tests/artifact/test_store.py — SqliteArtifactStore is a drop-in
replacement for the legacy filesystem ArtifactStore. Every method should
behave identically; this file encodes the contract.

Schema notes (covered by these tests):
- Per-row secondary index on (ticker, created_at DESC) — list ordering deterministic
- ArtifactSummary.verdict is extracted at save time and stored as a column,
  so dashboard aggregations don't need to reload the full payload.
- archive_stale uses last_viewed_at falling back to created_at.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from finrobot.artifact.sqlite_store import (
    SUMMARY_PROJECTION_VERSION,
    SqliteArtifactStore,
    _headline_from_summary,
)
from tests.artifact.conftest import _make_artifact

UTC = timezone.utc


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[SqliteArtifactStore]:
    """SqliteArtifactStore bound to a per-test tmp db, closed on teardown.

    Without the explicit ``close()`` aiosqlite leaves its connection
    worker thread alive after the test's event loop tears down — pytest
    then logs a noisy ``RuntimeError: Event loop is closed`` warning per
    test. Yield-style teardown closes the connection cleanly.
    """
    s = SqliteArtifactStore(db_path=tmp_path / "artifacts.db")
    try:
        yield s
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_save_then_get_roundtrip(store: SqliteArtifactStore) -> None:
    art = _make_artifact()
    await store.save(art)

    loaded = await store.get(art.id)
    assert loaded is not None
    assert loaded.id == art.id
    assert loaded.ticker == "AAPL"
    assert loaded.type == "dcf"
    assert loaded.outputs.structured["implied_price"] == pytest.approx(185.0)
    assert loaded.assumptions.parameters["wacc"] == pytest.approx(0.082)


@pytest.mark.asyncio
async def test_global_unarchived_list_uses_archived_created_index(
    store: SqliteArtifactStore,
) -> None:
    await store.save(_make_artifact(id="art_a", ticker="AAPL"))

    with sqlite3.connect(store._db_path) as conn:
        plan = conn.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT id, ticker, cross_tickers, type, verdict, created_at, archived,
                   entry_price, target_price, target_date, source, headline, tagline
            FROM artifacts
            WHERE archived = 0
            ORDER BY created_at DESC
            LIMIT 500
            """
        ).fetchall()

    rendered = "\n".join(str(row) for row in plan)
    assert "idx_artifacts_archived_created" in rendered
    assert "USE TEMP B-TREE" not in rendered


@pytest.mark.asyncio
async def test_get_missing_returns_none(store: SqliteArtifactStore) -> None:
    assert await store.get("nope_does_not_exist") is None


@pytest.mark.asyncio
async def test_list_by_ticker_sorted_desc(store: SqliteArtifactStore) -> None:
    now = datetime.now(tz=UTC)
    a1 = _make_artifact(id="art_a1", created_at=now - timedelta(hours=2))
    a2 = _make_artifact(id="art_a2", created_at=now - timedelta(hours=1))
    a3 = _make_artifact(id="art_a3", created_at=now)
    await store.save(a1)
    await store.save(a2)
    await store.save(a3)

    summaries = await store.list_by_ticker(ticker="AAPL", limit=10)
    assert [s.id for s in summaries] == ["art_a3", "art_a2", "art_a1"]


@pytest.mark.asyncio
async def test_list_by_ticker_rejects_non_positive_limit(store: SqliteArtifactStore) -> None:
    with pytest.raises(ValueError, match="limit must be >= 1"):
        await store.list_by_ticker(ticker="AAPL", limit=0)
    with pytest.raises(ValueError, match="limit must be >= 1"):
        await store.list_by_ticker(ticker="AAPL", limit=-1)


@pytest.mark.asyncio
async def test_list_all_tickers(store: SqliteArtifactStore) -> None:
    await store.save(_make_artifact(id="art_a", ticker="AAPL"))
    await store.save(_make_artifact(id="art_m", ticker="MSFT"))
    summaries = await store.list_by_ticker(ticker=None, limit=10)
    tickers = {s.ticker for s in summaries}
    assert tickers == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_list_by_tickers_in_clause_survives_global_cap(
    store: SqliteArtifactStore,
) -> None:
    """Scoped ``tickers={...}`` push the filter into SQL so the LIMIT applies to
    the SCOPED page (BUG-018). A small group whose reports are OLDER than the
    global newest-N page must still come back, not be evicted by a
    global-page-then-Python-filter.
    """
    now = datetime.now(tz=UTC)
    # 8 newest rows belong to a noisy ticker; the group's 2 rows are oldest.
    for i in range(8):
        await store.save(
            _make_artifact(
                id=f"art_noise_{i}",
                ticker="NVDA",
                created_at=now - timedelta(hours=i),
            )
        )
    await store.save(
        _make_artifact(
            id="art_grp_aapl",
            ticker="AAPL",
            created_at=now - timedelta(hours=100),
        )
    )
    await store.save(
        _make_artifact(
            id="art_grp_msft",
            ticker="MSFT",
            created_at=now - timedelta(hours=101),
        )
    )

    # A global newest-5 page is entirely NVDA → would evict the group.
    global_page = await store.list_by_ticker(ticker=None, limit=5)
    assert {s.ticker for s in global_page} == {"NVDA"}

    # Scoped query with the same cap still returns the group's older rows.
    scoped = await store.list_by_ticker(tickers={"AAPL", "MSFT"}, limit=5)
    assert {s.id for s in scoped} == {"art_grp_aapl", "art_grp_msft"}


@pytest.mark.asyncio
async def test_list_by_tickers_empty_set_returns_no_rows(
    store: SqliteArtifactStore,
) -> None:
    """An empty scope (empty coverage group) must not degrade to the global
    page — it has no track record."""
    await store.save(_make_artifact(id="art_a", ticker="AAPL"))
    assert await store.list_by_ticker(tickers=set(), limit=10) == []


@pytest.mark.asyncio
async def test_list_by_tickers_case_insensitive(store: SqliteArtifactStore) -> None:
    """Tickers are upper-cased before binding, matching single-ticker scope."""
    await store.save(_make_artifact(id="art_a", ticker="AAPL"))
    scoped = await store.list_by_ticker(tickers={"aapl"}, limit=10)
    assert {s.id for s in scoped} == {"art_a"}


@pytest.mark.asyncio
async def test_list_filters_archived(store: SqliteArtifactStore) -> None:
    a = _make_artifact(id="art_archived")
    a.meta.archived = True
    await store.save(a)
    await store.save(_make_artifact(id="art_live"))
    visible = await store.list_by_ticker(ticker="AAPL")
    assert {s.id for s in visible} == {"art_live"}
    with_archived = await store.list_by_ticker(ticker="AAPL", include_archived=True)
    assert {s.id for s in with_archived} == {"art_archived", "art_live"}


@pytest.mark.asyncio
async def test_list_filters_by_type(store: SqliteArtifactStore) -> None:
    await store.save(_make_artifact(id="art_d", type="dcf"))
    await store.save(_make_artifact(id="art_l", type="lbo"))
    only_dcf = await store.list_by_ticker(ticker="AAPL", type="dcf")
    assert {s.id for s in only_dcf} == {"art_d"}


@pytest.mark.asyncio
async def test_delete_then_get_is_none(store: SqliteArtifactStore) -> None:
    art = _make_artifact()
    await store.save(art)
    assert await store.delete(art.id) is True
    assert await store.get(art.id) is None
    assert await store.delete(art.id) is False  # second delete = miss


@pytest.mark.asyncio
async def test_cross_ticker_artifact(store: SqliteArtifactStore) -> None:
    """ticker=None artifacts live in the same table, identified by NULL."""
    art = _make_artifact(id="art_cross", ticker=None)
    art.cross_tickers = ["AAPL", "MSFT"]
    await store.save(art)
    loaded = await store.get("art_cross")
    assert loaded is not None
    assert loaded.ticker is None
    assert loaded.cross_tickers == ["AAPL", "MSFT"]
    # list_by_ticker(None) returns it
    summaries = await store.list_by_ticker(ticker=None)
    assert any(s.id == "art_cross" for s in summaries)


@pytest.mark.asyncio
async def test_summary_has_verdict_from_artifact(store: SqliteArtifactStore) -> None:
    """ArtifactSummary.verdict must be populated at save time so dashboard
    aggregations don't N+1 the full artifact for the verdict field."""
    art = _make_artifact()
    art.outputs.structured["thesis"] = {
        "recommendation": "BUY",
        "price_target": 250.0,
    }
    await store.save(art)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert summaries[0].verdict == "BUY"
    assert summaries[0].target_price == pytest.approx(250.0)


@pytest.mark.asyncio
async def test_mark_viewed_unarchives(store: SqliteArtifactStore) -> None:
    art = _make_artifact()
    art.meta.archived = True
    await store.save(art)
    # Sanity: archived hidden
    assert await store.list_by_ticker(ticker="AAPL") == []
    await store.mark_viewed(art.id)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert any(s.id == art.id for s in summaries)


@pytest.mark.asyncio
async def test_mark_viewed_is_column_only_no_payload_rewrite(
    store: SqliteArtifactStore,
) -> None:
    """mark_viewed must flip last_viewed_at/archived as a column UPDATE.

    The old get()+save() path re-(de)serialised the full payload to change two
    scalars, and silently skipped rows whose payload no longer validates —
    exactly the rows where the lifecycle columns are the only live state.
    Guard: payload bytes unchanged, columns moved, corrupt-payload row still
    gets stamped, missing id is a no-op.
    """
    art = _make_artifact(id="art_v")
    art.meta.archived = True
    await store.save(art)
    # A row whose payload no longer parses (schema drift) — columns must still move.
    corrupt = _make_artifact(id="art_corrupt")
    await store.save(corrupt)
    with sqlite3.connect(store._db_path) as conn:
        conn.execute(
            'UPDATE artifacts SET payload = \'{"not": "an artifact"}\' WHERE id = ?',
            ("art_corrupt",),
        )
        conn.commit()
        before = dict(conn.execute("SELECT id, payload FROM artifacts").fetchall())

    await store.mark_viewed("art_v")
    await store.mark_viewed("art_corrupt")
    await store.mark_viewed("art_missing")  # no-op, must not raise

    with sqlite3.connect(store._db_path) as conn:
        after = dict(conn.execute("SELECT id, payload FROM artifacts").fetchall())
        rows = dict(conn.execute("SELECT id, last_viewed_at FROM artifacts").fetchall())
        archived_flags = dict(conn.execute("SELECT id, archived FROM artifacts").fetchall())
    assert after == before, "mark_viewed must not rewrite the payload column"
    assert rows["art_v"] is not None
    assert rows["art_corrupt"] is not None, "corrupt payload must not block the lifecycle stamp"
    assert archived_flags["art_v"] == 0

    # get() realigns the in-memory Artifact to the columns.
    loaded = await store.get("art_v")
    assert loaded is not None
    assert loaded.meta.archived is False
    assert loaded.meta.last_viewed_at is not None


@pytest.mark.asyncio
async def test_archive_stale_marks_old(store: SqliteArtifactStore) -> None:
    now = datetime.now(tz=UTC)
    old = _make_artifact(id="art_old", created_at=now - timedelta(hours=48))
    fresh = _make_artifact(id="art_fresh", created_at=now)
    await store.save(old)
    await store.save(fresh)
    archived = await store.archive_stale(hours=24)
    assert archived == 1
    visible_ids = {s.id for s in await store.list_by_ticker(ticker="AAPL")}
    assert "art_fresh" in visible_ids
    assert "art_old" not in visible_ids  # now archived


@pytest.mark.asyncio
async def test_archive_stale_rejects_negative_hours(store: SqliteArtifactStore) -> None:
    with pytest.raises(ValueError, match="hours must be >= 0"):
        await store.archive_stale(hours=-1)


@pytest.mark.asyncio
async def test_archive_stale_is_set_based_no_payload_rewrite(
    store: SqliteArtifactStore,
) -> None:
    """BUG-048: archive must flip the column in ONE UPDATE, not per-row get()+save().

    The old implementation did a full get() (deserialize whole payload) + save()
    (re-serialize + 15-col UPSERT) for every stale row just to toggle one bool.
    Guard the fix three ways:
      1. archive_stale calls neither get() nor save() (no payload roundtrip).
      2. The stored payload JSON is byte-for-byte unchanged after archiving.
      3. A single batch UPDATE archives ALL stale rows regardless of count.
    """
    now = datetime.now(tz=UTC)
    stale_ids = [f"art_stale_{i}" for i in range(5)]
    for sid in stale_ids:
        await store.save(_make_artifact(id=sid, created_at=now - timedelta(hours=48)))
    await store.save(_make_artifact(id="art_fresh", created_at=now))

    # Snapshot the raw payload bytes BEFORE archiving.
    with sqlite3.connect(store._db_path) as conn:
        before = dict(conn.execute("SELECT id, payload FROM artifacts").fetchall())

    # Spy: archive_stale must not touch the payload codecs.
    get_calls = 0
    save_calls = 0
    orig_get = store.get
    orig_save = store.save

    async def spy_get(artifact_id: str):  # type: ignore[no-untyped-def]
        nonlocal get_calls
        get_calls += 1
        return await orig_get(artifact_id)

    async def spy_save(artifact):  # type: ignore[no-untyped-def]
        nonlocal save_calls
        save_calls += 1
        return await orig_save(artifact)

    store.get = spy_get  # type: ignore[method-assign]
    store.save = spy_save  # type: ignore[method-assign]
    try:
        archived = await store.archive_stale(hours=24)
    finally:
        store.get = orig_get  # type: ignore[method-assign]
        store.save = orig_save  # type: ignore[method-assign]

    assert archived == len(stale_ids)  # all stale rows in one statement
    assert get_calls == 0, "archive_stale must not deserialize payloads"
    assert save_calls == 0, "archive_stale must not re-serialize payloads"

    # Payload bytes unchanged — only the archived column moved.
    with sqlite3.connect(store._db_path) as conn:
        after = dict(conn.execute("SELECT id, payload FROM artifacts").fetchall())
        archived_flags = dict(conn.execute("SELECT id, archived FROM artifacts").fetchall())
    assert after == before, "archive must not rewrite the payload column"
    for sid in stale_ids:
        assert archived_flags[sid] == 1
    assert archived_flags["art_fresh"] == 0


@pytest.mark.asyncio
async def test_get_realigns_payload_archived_to_column(
    store: SqliteArtifactStore,
) -> None:
    """After a column-only archive, get() must reflect archived=True in the payload.

    archive_stale no longer rewrites payload.meta.archived (it stays False in the
    stored JSON), so get() realigns it to the authoritative column on read —
    otherwise a caller reading the Artifact would see archived=False while
    list_by_ticker (column-driven) reports it archived. (BUG-048 read alignment.)
    """
    now = datetime.now(tz=UTC)
    art = _make_artifact(id="art_old", created_at=now - timedelta(hours=48))
    assert art.meta.archived is False
    await store.save(art)

    await store.archive_stale(hours=24)

    # Stored payload still says archived=False (no rewrite)...
    with sqlite3.connect(store._db_path) as conn:
        (payload,) = conn.execute(
            "SELECT payload FROM artifacts WHERE id = ?", ("art_old",)
        ).fetchone()
    assert '"archived":true' not in payload.replace(" ", "")

    # ...but get() realigns the in-memory Artifact to the column.
    loaded = await store.get("art_old")
    assert loaded is not None
    assert loaded.meta.archived is True


@pytest.mark.asyncio
async def test_rebuild_summaries_reprojects_stale_mirror_columns(
    store: SqliteArtifactStore,
) -> None:
    """BUG-065: rebuild_summaries must re-derive the mirror columns from the
    payload so a row written under an OLD extractor is brought current.

    Simulate the stale state directly: corrupt the verdict/target_price columns
    in SQL (as an obsolete extractor would have left them), leaving the payload
    intact. rebuild_summaries must re-run the current extractor over the payload
    and overwrite the columns — without touching the payload bytes.
    """
    art = _make_artifact()
    art.outputs.structured["thesis"] = {"recommendation": "BUY", "price_target": 250.0}
    await store.save(art)

    with sqlite3.connect(store._db_path) as conn:
        (payload_before,) = conn.execute(
            "SELECT payload FROM artifacts WHERE id = ?", (art.id,)
        ).fetchone()
        # Stale columns: a prior extractor failed to parse these.
        conn.execute(
            "UPDATE artifacts SET verdict = NULL, target_price = NULL WHERE id = ?",
            (art.id,),
        )
        conn.commit()

    # Pre-condition: the stale row reads back wrong.
    stale = await store.list_by_ticker(ticker="AAPL")
    assert stale[0].verdict is None
    assert stale[0].target_price is None

    rebuilt = await store.rebuild_summaries()
    assert rebuilt == 1

    fresh = await store.list_by_ticker(ticker="AAPL")
    assert fresh[0].verdict == "BUY"
    assert fresh[0].target_price == pytest.approx(250.0)

    # Payload must be byte-for-byte unchanged (mirror-column-only UPDATE).
    with sqlite3.connect(store._db_path) as conn:
        (payload_after,) = conn.execute(
            "SELECT payload FROM artifacts WHERE id = ?", (art.id,)
        ).fetchone()
    assert payload_after == payload_before


@pytest.mark.asyncio
async def test_rebuild_summaries_skips_unparseable_payload(
    store: SqliteArtifactStore,
) -> None:
    """A row whose payload no longer validates must be skipped + logged, never
    aborting the whole backfill — the good rows still get re-projected."""
    good = _make_artifact(id="art_good")
    good.outputs.structured["thesis"] = {"recommendation": "SELL"}
    await store.save(good)
    await store.save(_make_artifact(id="art_bad"))

    with sqlite3.connect(store._db_path) as conn:
        conn.execute("UPDATE artifacts SET payload = ? WHERE id = ?", ("not json", "art_bad"))
        conn.execute("UPDATE artifacts SET verdict = NULL WHERE id = ?", ("art_good",))
        conn.commit()

    rebuilt = await store.rebuild_summaries()
    assert rebuilt == 1  # only the good row re-projected; bad one skipped

    summaries = {s.id: s for s in await store.list_by_ticker(ticker="AAPL")}
    assert summaries["art_good"].verdict == "SELL"


@pytest.mark.asyncio
async def test_rebuild_summaries_if_outdated_gates_on_version(
    store: SqliteArtifactStore,
) -> None:
    """The startup gate runs the backfill once, then records the version so a
    second call (same version) is a no-op — and a later version bump re-runs."""
    art = _make_artifact()
    art.outputs.structured["thesis"] = {"recommendation": "BUY"}
    await store.save(art)
    with sqlite3.connect(store._db_path) as conn:
        conn.execute("UPDATE artifacts SET verdict = NULL WHERE id = ?", (art.id,))
        conn.commit()

    # Fresh db is at user_version 0 → below the code version → backfill runs.
    first = await store.rebuild_summaries_if_outdated()
    assert first == 1
    assert (await store.list_by_ticker(ticker="AAPL"))[0].verdict == "BUY"

    # Version now recorded → second call at the same version is a no-op.
    second = await store.rebuild_summaries_if_outdated()
    assert second == 0

    # Corrupt again and bump the requested version → it re-runs.
    with sqlite3.connect(store._db_path) as conn:
        conn.execute("UPDATE artifacts SET verdict = NULL WHERE id = ?", (art.id,))
        conn.commit()
    third = await store.rebuild_summaries_if_outdated(version=999)
    assert third == 1
    assert (await store.list_by_ticker(ticker="AAPL"))[0].verdict == "BUY"


@pytest.mark.asyncio
async def test_save_is_upsert_on_id_conflict(store: SqliteArtifactStore) -> None:
    """Re-saving the same id replaces the row (one-version-per-id contract)."""
    art = _make_artifact()
    await store.save(art)
    art.outputs.structured["implied_price"] = 999.0
    await store.save(art)
    loaded = await store.get(art.id)
    assert loaded is not None
    assert loaded.outputs.structured["implied_price"] == pytest.approx(999.0)
    # Still only one row
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert len(summaries) == 1


# ── 门四溯源半: primary_provider mirror column ───────────────────────────────


@pytest.mark.asyncio
async def test_summary_carries_primary_provider(store: SqliteArtifactStore) -> None:
    """save() must extract inputs.data_source into the primary_provider column
    so the Library list can show WHICH provider fed each artifact without
    reloading payloads (溯源驾驶舱: provider visible at a glance)."""
    art = _make_artifact()  # conftest sets inputs.data_source="yfinance"
    await store.save(art)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert summaries[0].primary_provider == "yfinance"


# ── fairly_valued: in-band point-target withhold mirror column ───────────────


@pytest.mark.asyncio
async def test_summary_carries_fairly_valued_roundtrip(store: SqliteArtifactStore) -> None:
    """save() projects extract_fairly_valued into the fairly_valued column and
    list_by_ticker unpacks it back (SQLite 0/1 → bool) in the right tuple slot —
    so the version-timeline row can render "Fairly Valued" vs generic "WITHHELD"
    without reloading the payload."""
    in_band = _make_artifact(id="art_in_band", type="equity_research")
    in_band.outputs.structured = {
        "valuation_withheld": True,
        "thesis": {
            "recommendation": "HOLD",
            "price_target": None,
            "price_target_basis": "FAIRLY VALUED — price sits inside the band; HOLD.",
        },
    }
    genuine = _make_artifact(id="art_withheld", type="equity_research")
    genuine.outputs.structured = {
        "valuation_withheld": True,
        "thesis": {
            "recommendation": "HOLD",
            "price_target": None,
            "price_target_basis": "WITHHELD — M&A transition poisons the inputs.",
        },
    }
    await store.save(in_band)
    await store.save(genuine)
    await store.save(_make_artifact(id="art_plain"))  # default DCF, no withhold

    by_id = {s.id: s for s in await store.list_by_ticker(ticker="AAPL")}
    assert by_id["art_in_band"].fairly_valued is True
    assert by_id["art_withheld"].fairly_valued is False
    assert by_id["art_plain"].fairly_valued is False


@pytest.mark.asyncio
async def test_legacy_db_without_fairly_valued_column_self_migrates(tmp_path: Path) -> None:
    """A pre-fairly_valued artifacts.db (column absent) must ALTER the column in
    so a legacy row reads back NULL→False without crashing, and the projection
    rebuild backfills the in-band marker from the stored payload."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    # Schema as of the primary_provider migration (no fairly_valued column yet).
    conn.execute(
        """
        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY, ticker TEXT, cross_tickers TEXT NOT NULL DEFAULT '[]',
            type TEXT NOT NULL, verdict TEXT, created_at TEXT NOT NULL,
            last_viewed_at TEXT, archived INTEGER NOT NULL DEFAULT 0,
            entry_price REAL, target_price REAL, target_date TEXT,
            source TEXT, headline TEXT, tagline TEXT, primary_provider TEXT,
            payload TEXT NOT NULL
        )
        """
    )
    legacy = _make_artifact(id="art_legacy_in_band", type="equity_research")
    legacy.outputs.structured = {
        "valuation_withheld": True,
        "thesis": {
            "recommendation": "HOLD",
            "price_target": None,
            "price_target_basis": "FAIRLY VALUED — within band.",
        },
    }
    conn.execute(
        "INSERT INTO artifacts (id, ticker, type, created_at, payload) VALUES (?, ?, ?, ?, ?)",
        (
            legacy.id,
            legacy.ticker,
            str(legacy.type),
            legacy.meta.created_at.isoformat(),
            legacy.model_dump_json(),
        ),
    )
    conn.commit()
    conn.close()

    s = SqliteArtifactStore(db_path=db)
    try:
        # NULL column on first read (column just ALTER'd in) → False, no crash.
        summaries = await s.list_by_ticker(ticker="AAPL")
        assert summaries[0].fairly_valued is False
        # … and the projection rebuild backfills it from the payload.
        await s.rebuild_summaries()
        summaries = await s.list_by_ticker(ticker="AAPL")
        assert summaries[0].fairly_valued is True
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_get_hydrates_legacy_llm_narrative_from_thesis(
    store: SqliteArtifactStore,
) -> None:
    """Legacy rows predate outputs.llm_narrative; hydrate from structured.thesis
    at read time so consumers can use the semantic top-level key."""
    art = _make_artifact(id="art_legacy_narrative", type="equity_research")
    art.outputs.structured = {
        "thesis": {
            "tagline": "AI infrastructure play",
            "recommendation": "BUY",
            "valuation_overview": "DCF and comps corroborate.",
            "risks": ["Export controls"],
        }
    }
    art.outputs.llm_narrative = {}
    await store.save(art)

    loaded = await store.get(art.id)

    assert loaded is not None
    assert loaded.outputs.llm_narrative == {
        "tagline": "AI infrastructure play",
        "valuation_overview": "DCF and comps corroborate.",
        "recommendation": "BUY",
        "risks": ["Export controls"],
    }


@pytest.mark.asyncio
async def test_unknown_provider_normalizes_to_none(store: SqliteArtifactStore) -> None:
    """builders fall back to data_source="unknown" when no structured step
    matched — that placeholder must not render as a fake provider chip."""
    art = _make_artifact(id="art_unknown_src")
    art.inputs.data_source = "unknown"
    await store.save(art)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert summaries[0].primary_provider is None


@pytest.mark.asyncio
async def test_legacy_db_without_column_self_migrates(tmp_path: Path) -> None:
    """Opening a pre-门四 artifacts.db (no primary_provider column) must
    ALTER the table in place — existing installs can't lose their store."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY, ticker TEXT, cross_tickers TEXT NOT NULL DEFAULT '[]',
            type TEXT NOT NULL, verdict TEXT, created_at TEXT NOT NULL,
            last_viewed_at TEXT, archived INTEGER NOT NULL DEFAULT 0,
            entry_price REAL, target_price REAL, target_date TEXT,
            source TEXT, headline TEXT, tagline TEXT, payload TEXT NOT NULL
        )
        """
    )
    legacy = _make_artifact(id="art_legacy_row")
    conn.execute(
        "INSERT INTO artifacts (id, ticker, type, created_at, payload) VALUES (?, ?, ?, ?, ?)",
        (
            legacy.id,
            legacy.ticker,
            str(legacy.type),
            legacy.meta.created_at.isoformat(),
            legacy.model_dump_json(),
        ),
    )
    conn.commit()
    conn.close()

    s = SqliteArtifactStore(db_path=db)
    try:
        # legacy row reads back with a NULL column (no crash) …
        summaries = await s.list_by_ticker(ticker="AAPL")
        assert summaries[0].primary_provider is None
        # … and the projection rebuild backfills it from the payload.
        await s.rebuild_summaries()
        summaries = await s.list_by_ticker(ticker="AAPL")
        assert summaries[0].primary_provider == "yfinance"
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_get_unreadable_payload_self_archives_and_exists(
    store: SqliteArtifactStore,
) -> None:
    """Schema-drift ghost rows (P2 audit 2026-06-10): get() on an unreadable
    payload archives the row column-only (payload preserved) so it leaves
    default lists, and exists() lets callers tell 'never stored' from
    'stored but unreadable'."""
    await store.save(_make_artifact(id="art_ghost"))
    with sqlite3.connect(store._db_path) as conn:
        conn.execute(
            'UPDATE artifacts SET payload = \'{"not": "an artifact"}\' WHERE id = ?',
            ("art_ghost",),
        )
        conn.commit()

    # Visible in the default list before detection (columns still render).
    assert any(s.id == "art_ghost" for s in await store.list_by_ticker(ticker="AAPL"))

    assert await store.get("art_ghost") is None  # unreadable → None
    # ...but the detection self-archived it (column-only, payload untouched).
    with sqlite3.connect(store._db_path) as conn:
        archived, payload = conn.execute(
            "SELECT archived, payload FROM artifacts WHERE id = ?", ("art_ghost",)
        ).fetchone()
    assert archived == 1
    assert payload == '{"not": "an artifact"}'
    assert not any(s.id == "art_ghost" for s in await store.list_by_ticker(ticker="AAPL"))

    # exists() splits the two miss cases.
    assert await store.exists("art_ghost") is True
    assert await store.exists("art_never_stored") is False


# ── headline projection: no markdown-facade leak (external-review defect) ─────

# A real multi-method equity_research summary_text — format_summary() output,
# which opens with the generic markdown scaffolding a blind [:120] slice used to
# leak into the headline column / exported-HTML timeline JSON.
_POLLUTED_SUMMARY = (
    "# FinRobot Analysis Report\n\n\n---\n\n## Data Collection\n\n"
    "### Microsoft Corporation (MSFT) Financial and Price Data Summary\n\n"
    "Microsoft reported revenue of $245.1B (TTM) with a 44% operating margin, "
    "driven by Azure and Microsoft 365 Copilot adoption."
)


def test_headline_from_summary_skips_markdown_facade() -> None:
    """The bug: a blind summary_text[:120] leaked "# FinRobot Analysis Report /
    --- / ## Data Collection" scaffolding. The cleaned headline is the first
    PROSE line — no heading hash, no rule, no scaffolding text."""
    headline = _headline_from_summary(_POLLUTED_SUMMARY)
    assert headline.startswith("Microsoft reported revenue of $245.1B")
    assert "#" not in headline
    assert "FinRobot Analysis Report" not in headline
    assert "Data Collection" not in headline
    assert len(headline) <= 120


def test_headline_from_summary_strips_leading_bullet_and_inline_emphasis() -> None:
    text = "## Header\n\n- **Revenue:** $245.1B up 12% YoY on `cloud` demand"
    assert _headline_from_summary(text) == "Revenue: $245.1B up 12% YoY on cloud demand"


def test_headline_from_summary_plain_prose_matches_legacy_slice() -> None:
    """A plain-prose summary (no scaffolding) is unchanged from the old [:120]."""
    prose = "DDM implies $319.89 per share (10.3% upside vs $290.00)."
    assert _headline_from_summary(prose) == prose[:120] == prose


def test_headline_from_summary_truncates_long_prose_to_120() -> None:
    long_line = "Microsoft " + "x" * 300
    out = _headline_from_summary(long_line)
    assert len(out) == 120
    assert out == long_line[:120]


def test_headline_from_summary_all_scaffolding_falls_back_to_slice() -> None:
    """Every line is heading/rule/blank → fall back to the raw [:120] so the
    result is never emptier than the old behaviour (caller adds `or id`)."""
    only_scaffold = "# FinRobot Analysis Report\n\n---\n\n## Data Collection"
    assert _headline_from_summary(only_scaffold) == only_scaffold[:120]


def test_headline_from_summary_empty_returns_empty() -> None:
    """Empty in → empty out; call sites keep their `or artifact.id` guard."""
    assert _headline_from_summary("") == ""


@pytest.mark.asyncio
async def test_save_projects_clean_headline_not_markdown_facade(
    store: SqliteArtifactStore,
) -> None:
    """save() (_artifact_to_row) must store a prose headline preview, not the
    leaked "# FinRobot Analysis Report / --- / ## Data Collection" scaffolding
    the exported-HTML timeline JSON surfaces to external readers."""
    art = _make_artifact(id="art_polluted", type="equity_research")
    art.outputs.summary_text = _POLLUTED_SUMMARY
    await store.save(art)

    with sqlite3.connect(store._db_path) as conn:
        (headline,) = conn.execute(
            "SELECT headline FROM artifacts WHERE id = ?", ("art_polluted",)
        ).fetchone()
    assert headline.startswith("Microsoft reported revenue of $245.1B")
    assert "# FinRobot Analysis Report" not in headline
    assert not headline.lstrip().startswith("#")


@pytest.mark.asyncio
async def test_headline_backfills_via_startup_version_gate(
    store: SqliteArtifactStore,
) -> None:
    """Migration story: a db stamped at the pre-fix projection version (4) with a
    leaked-facade headline column gets the clean headline backfilled by the
    startup gate (rebuild_summaries_if_outdated → rebuild_summaries), advancing
    the recorded version — so shipped installs self-heal on next boot WITHOUT
    the reprojection path re-writing the facade back (the third [:120] site).
    """
    art = _make_artifact(id="art_backfill", type="equity_research")
    art.outputs.summary_text = _POLLUTED_SUMMARY
    await store.save(art)

    # Stamp the pre-fix state: old projection version + the blind-slice headline.
    with sqlite3.connect(store._db_path) as conn:
        conn.execute("PRAGMA user_version = 4")
        conn.execute(
            "UPDATE artifacts SET headline = ? WHERE id = ?",
            (_POLLUTED_SUMMARY[:120], "art_backfill"),
        )
        conn.commit()
        (stale,) = conn.execute(
            "SELECT headline FROM artifacts WHERE id = ?", ("art_backfill",)
        ).fetchone()
    assert stale.startswith("# FinRobot Analysis Report")  # pre-condition: polluted

    assert SUMMARY_PROJECTION_VERSION >= 5  # this fix bumped past the v4 baseline
    updated = await store.rebuild_summaries_if_outdated()
    assert updated == 1  # the pre-fix row was re-projected

    summaries = await store.list_by_ticker(ticker="AAPL")
    assert summaries[0].headline.startswith("Microsoft reported revenue of $245.1B")
    assert "# FinRobot Analysis Report" not in summaries[0].headline

    with sqlite3.connect(store._db_path) as conn:
        (applied,) = conn.execute("PRAGMA user_version").fetchone()
    assert applied == SUMMARY_PROJECTION_VERSION
