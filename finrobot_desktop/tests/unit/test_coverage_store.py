"""CoverageStore (coverage/sqlite_store.py) — persistence round-trips.

The store now exposes only the single ``Studied Tickers`` workspace: the
system group is the sole creation primitive (``get_or_create_system_group``);
members are added via ``add_members`` and read back via ``get_group`` /
``get_system_group`` / ``list_groups``. There is no multi-group management
(create / rename / delete / remove-member) — that surface was removed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finrobot.coverage.sqlite_store import CoverageStore


@pytest.fixture
async def store(tmp_path: Path):
    s = CoverageStore(db_path=tmp_path / "coverage.db")
    yield s
    await s.close()


async def test_get_or_create_and_get_group(store: CoverageStore) -> None:
    g = await store.get_or_create_system_group("Studied Tickers", "My research universe")
    assert g.id.startswith("cov_")
    assert g.name == "Studied Tickers"
    assert g.is_system is True

    fetched = await store.get_group(g.id)
    assert fetched is not None
    assert fetched.name == "Studied Tickers"
    assert fetched.description == "My research universe"
    assert fetched.members == []


async def test_get_missing_group_returns_none(store: CoverageStore) -> None:
    assert await store.get_group("cov_nope") is None


async def test_add_members_upper_cased_and_idempotent(store: CoverageStore) -> None:
    g = await store.get_or_create_system_group("Studied Tickers")
    await store.add_members(g.id, ["nvda", "AMD"])
    detail = await store.add_members(g.id, ["nvda"])  # dup → no-op
    assert detail is not None
    tickers = sorted(m.ticker for m in detail.members)
    assert tickers == ["AMD", "NVDA"]


async def test_add_members_to_missing_group_returns_none(store: CoverageStore) -> None:
    assert await store.add_members("cov_nope", ["AAPL"]) is None


async def test_list_groups_carries_member_count(store: CoverageStore) -> None:
    g = await store.get_or_create_system_group("Studied Tickers")
    await store.add_members(g.id, ["AAPL", "MSFT"])
    groups = await store.list_groups()
    counts = {grp.name: grp.member_count for grp in groups}
    assert counts == {"Studied Tickers": 2}


async def test_count_groups(store: CoverageStore) -> None:
    assert await store.count_groups() == 0
    await store.get_or_create_system_group("Studied Tickers")
    # The single system group is find-or-create — a second call is a no-op.
    await store.get_or_create_system_group("Studied Tickers")
    assert await store.count_groups() == 1


async def test_system_group_flag_persists(store: CoverageStore) -> None:
    g = await store.get_or_create_system_group("Studied Tickers")
    fetched = await store.get_group(g.id)
    assert fetched is not None
    assert fetched.is_system is True


async def test_get_system_group_none_when_absent(store: CoverageStore) -> None:
    assert await store.get_system_group() is None


async def test_get_system_group_finds_seeded(store: CoverageStore) -> None:
    sys_g = await store.get_or_create_system_group("Studied Tickers")
    await store.add_members(sys_g.id, ["AAPL"])
    found = await store.get_system_group()
    assert found is not None
    assert found.id == sys_g.id
    assert found.is_system is True
    assert [m.ticker for m in found.members] == ["AAPL"]


async def test_get_or_create_system_group_idempotent(store: CoverageStore) -> None:
    # The safe entry point: concurrent/repeat cold-start calls resolve to the
    # single surviving row instead of raising or duplicating (BUG-088).
    a = await store.get_or_create_system_group("Studied Tickers", "desc")
    b = await store.get_or_create_system_group("Studied Tickers", "desc")
    assert a.id == b.id
    assert a.is_system is True
    # Exactly one system group ever — the partial unique index guarantees it.
    systems = [g for g in await store.list_groups() if g.is_system]
    assert len(systems) == 1
