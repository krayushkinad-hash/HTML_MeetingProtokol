"""Coverage tests for app/routers/calendar.py — targets 60%+.

Endpoint covered:
- GET /calendar?year=YYYY&month=MM   (get_calendar — US-011)

Branches exercised:
- month == 12   → end_date crosses year boundary (year + 1, 1, 1)
- month <  12   → end_date is (year, month + 1, 1)
- empty result   → empty counts_by_date dict
- multi-day result → group_by & sum aggregation
- soft-deleted protocols excluded
- past month   (before any data)
- future month (after any data)
- 422 validation: missing year, missing month, month=0, month=13, year<2020, year>2100
"""
from __future__ import annotations

import uuid
from datetime import date as date_cls, datetime, timezone

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Local factory — sample_protocol in tests/conftest_pg.py uses date=now(),
# so we make our own with explicit date / deleted_at control.
# ---------------------------------------------------------------------------


async def _make_protocol(
    db_session,
    *,
    title: str = "Cal Test",
    day: date_cls,
    deleted_at=None,
):
    from app.db.models import Protocol

    p = Protocol(
        id=uuid.uuid4(),
        title=title,
        date=day,
        status="loaded",
        language="ru",
        created_at=datetime.now(timezone.utc),
        deleted_at=deleted_at,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


URL = "/api/v1/hmp/calendar"


# ---------------------------------------------------------------------------
# Happy path — 4 tests covering both month-branches and aggregation paths
# ---------------------------------------------------------------------------


async def test_calendar_empty_month(client):
    """GET /calendar with no data → empty counts_by_date, 200."""
    r = await client.get(f"{URL}?year=2026&month=3")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year"] == 2026
    assert body["month"] == 3
    assert body["counts_by_date"] == {}


async def test_calendar_single_day(client, db_session):
    """GET /calendar groups by date — one date → one entry, count=1."""
    await _make_protocol(db_session, day=date_cls(2026, 4, 15))
    r = await client.get(f"{URL}?year=2026&month=4")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts_by_date"] == {"2026-04-15": 1}


async def test_calendar_multiple_days_aggregation(client, db_session):
    """GET /calendar sums counts per day — 3 protocols on day A, 2 on day B."""
    for _ in range(3):
        await _make_protocol(db_session, title="A", day=date_cls(2026, 5, 10))
    for _ in range(2):
        await _make_protocol(db_session, title="B", day=date_cls(2026, 5, 11))
    r = await client.get(f"{URL}?year=2026&month=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts_by_date"] == {
        "2026-05-10": 3,
        "2026-05-11": 2,
    }


async def test_calendar_month_december_year_boundary(client, db_session):
    """month=12 must cross into next year (year+1, 1, 1)."""
    # Dec 2026 — inside the window
    await _make_protocol(db_session, title="Dec", day=date_cls(2026, 12, 31))
    # Jan 2027 — MUST NOT appear
    await _make_protocol(db_session, title="Jan", day=date_cls(2027, 1, 1))
    # Dec 2025 — MUST NOT appear
    await _make_protocol(db_session, title="Prev", day=date_cls(2025, 12, 31))

    r = await client.get(f"{URL}?year=2026&month=12")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts_by_date"] == {"2026-12-31": 1}, body["counts_by_date"]


# ---------------------------------------------------------------------------
# Filtering — soft-deleted & out-of-window
# ---------------------------------------------------------------------------


async def test_calendar_excludes_soft_deleted(client, db_session):
    """Protocols with deleted_at IS NOT NULL must be excluded."""
    from datetime import datetime as dt_cls

    # Live protocol on 2026-06-10
    await _make_protocol(db_session, title="live", day=date_cls(2026, 6, 10))
    # Soft-deleted on the same day — must NOT count
    await _make_protocol(
        db_session,
        title="dead",
        day=date_cls(2026, 6, 10),
        deleted_at=dt_cls(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
    )

    r = await client.get(f"{URL}?year=2026&month=6")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts_by_date"] == {"2026-06-10": 1}, body["counts_by_date"]


async def test_calendar_excludes_neighbouring_months(client, db_session):
    """Window is [start, end) — previous month and next month must be excluded."""
    # Previous month (June 30) — must NOT appear
    await _make_protocol(db_session, title="prev", day=date_cls(2026, 6, 30))
    # Next month (Aug 1) — must NOT appear
    await _make_protocol(db_session, title="next", day=date_cls(2026, 8, 1))
    # Target month (July 15) — should appear
    await _make_protocol(db_session, title="in", day=date_cls(2026, 7, 15))

    r = await client.get(f"{URL}?year=2026&month=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts_by_date"] == {"2026-07-15": 1}, body["counts_by_date"]


async def test_calendar_future_month_empty(client, db_session):
    """A future month with no data → empty dict, year/month echoed."""
    await _make_protocol(db_session, day=date_cls(2026, 9, 20))  # last month
    r = await client.get(f"{URL}?year=2099&month=11")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"year": 2099, "month": 11, "counts_by_date": {}}


# ---------------------------------------------------------------------------
# 422 validation — missing/invalid params (Query constraints)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "qs",
    [
        "",                # both missing
        "?year=2026",      # month missing
        "?month=5",        # year missing
        "?year=2026&month=0",   # month < 1
        "?year=2026&month=13",  # month > 12
        "?year=2019&month=5",   # year < 2020
        "?year=2101&month=5",   # year > 2100
    ],
)
async def test_calendar_validation_returns_422(client, qs):
    """Missing or out-of-range year/month → FastAPI 422."""
    r = await client.get(f"{URL}{qs}")
    assert r.status_code == 422, (qs, r.status_code, r.text)


# ---------------------------------------------------------------------------
# Response shape sanity — explicit asserts on every field
# ---------------------------------------------------------------------------


async def test_calendar_response_shape(client, db_session):
    """Body must contain year, month, counts_by_date with isoformat keys."""
    await _make_protocol(db_session, day=date_cls(2026, 4, 1))
    await _make_protocol(db_session, day=date_cls(2026, 4, 1))
    await _make_protocol(db_session, day=date_cls(2026, 4, 2))

    r = await client.get(f"{URL}?year=2026&month=4")
    assert r.status_code == 200, r.text
    body = r.json()

    assert set(body.keys()) == {"year", "month", "counts_by_date"}
    assert isinstance(body["year"], int)
    assert isinstance(body["month"], int)
    assert isinstance(body["counts_by_date"], dict)
    # Every key must be ISO-8601 date string, every value must be a positive int
    for k, v in body["counts_by_date"].items():
        assert len(k) == 10 and k[4] == "-" and k[7] == "-"
        assert isinstance(v, int) and v >= 1
