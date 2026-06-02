"""CoverageStore (coverage/sqlite_store.py) — persistence round-trips."""

from __future__ import annotations

from pathlib import Path

import pytest

from finrobot.coverage.sqlite_store import CoverageStore


@pytest.fixture
async def store(tmp_path: Path):
    s = CoverageStore(db_path=tmp_path / "coverage.db")
    yield s
    await s.close()


async def test_create_and_get_group(store: CoverageStore) -> None:
    g = await store.create_group("Mag7", "Mega-cap tech")
    assert g.id.startswith("cov_")
    assert g.name == "Mag7"
    assert g.is_system is False

    fetched = await store.get_group(g.id)
    assert fetched is not None
    assert fetched.name == "Mag7"
    assert fetched.description == "Mega-cap tech"
    assert fetched.members == []


async def test_get_missing_group_returns_none(store: CoverageStore) -> None:
    assert await store.get_group("cov_nope") is None


async def test_add_members_upper_cased_and_idempotent(store: CoverageStore) -> None:
    g = await store.create_group("AI Infra")
    await store.add_members(g.id, ["nvda", "AMD"])
    detail = await store.add_members(g.id, ["nvda"])  # dup → no-op
    assert detail is not None
    tickers = sorted(m.ticker for m in detail.members)
    assert tickers == ["AMD", "NVDA"]


async def test_add_members_to_missing_group_returns_none(store: CoverageStore) -> None:
    assert await store.add_members("cov_nope", ["AAPL"]) is None


async def test_remove_member(store: CoverageStore) -> None:
    g = await store.create_group("Semi")
    await store.add_members(g.id, ["NVDA", "AMD", "INTC"])
    assert await store.remove_member(g.id, "amd") is True  # case-insensitive
    assert await store.remove_member(g.id, "amd") is False  # already gone
    detail = await store.get_group(g.id)
    assert detail is not None
    assert sorted(m.ticker for m in detail.members) == ["INTC", "NVDA"]


async def test_list_groups_carries_member_count(store: CoverageStore) -> None:
    a = await store.create_group("A")
    b = await store.create_group("B")
    await store.add_members(a.id, ["AAPL", "MSFT"])
    groups = await store.list_groups()
    counts = {g.name: g.member_count for g in groups}
    assert counts == {"A": 2, "B": 0}
    # created_at ASC ordering
    assert [g.id for g in groups] == [a.id, b.id]


async def test_update_group_name_and_description(store: CoverageStore) -> None:
    g = await store.create_group("Old", "old desc")
    updated = await store.update_group(g.id, name="New")
    assert updated is not None
    assert updated.name == "New"
    assert updated.description == "old desc"  # untouched
    assert updated.updated_at >= g.updated_at


async def test_update_missing_group_returns_none(store: CoverageStore) -> None:
    assert await store.update_group("cov_nope", name="x") is None


async def test_delete_group_cascades_members(store: CoverageStore) -> None:
    g = await store.create_group("Doomed")
    await store.add_members(g.id, ["AAPL"])
    assert await store.delete_group(g.id) is True
    assert await store.get_group(g.id) is None
    # members table no longer references the group
    assert await store.list_members(g.id) == []
    assert await store.delete_group(g.id) is False  # already gone


async def test_count_groups(store: CoverageStore) -> None:
    assert await store.count_groups() == 0
    await store.create_group("X")
    await store.create_group("Y")
    assert await store.count_groups() == 2


async def test_system_group_flag_persists(store: CoverageStore) -> None:
    g = await store.create_group("Studied Tickers", is_system=True)
    fetched = await store.get_group(g.id)
    assert fetched is not None
    assert fetched.is_system is True
