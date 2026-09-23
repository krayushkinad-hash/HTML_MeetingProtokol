"""Calendar endpoints (US-011).

Returns protocol counts per day for a given year/month — powers the calendar
heatmap in the UI. Soft-deleted protocols (``deleted_at IS NOT NULL``) are
excluded.
"""
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Protocol
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


@router.get(
    "/calendar",
    summary="Calendar view — protocols per day (US-011)",
)
async def get_calendar(
    year: int = Query(..., ge=2020, le=2100, description="Год, например 2026"),
    month: int = Query(..., ge=1, le=12, description="Месяц 1-12"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return ``{year, month, counts_by_date: {"2026-09-14": 3, ...}}``."""
    start_date = date_cls(year, month, 1)
    if month == 12:
        end_date = date_cls(year + 1, 1, 1)
    else:
        end_date = date_cls(year, month + 1, 1)

    query = (
        select(Protocol.date, func.count(Protocol.id))
        .where(
            and_(
                Protocol.date >= start_date,
                Protocol.date < end_date,
                Protocol.deleted_at.is_(None),
            )
        )
        .group_by(Protocol.date)
    )

    result = await db.execute(query)
    counts_by_date: dict[str, int] = {
        row[0].isoformat(): int(row[1]) for row in result.all()
    }

    logger.info(
        "calendar_fetched",
        year=year,
        month=month,
        days_with_protocols=len(counts_by_date),
        total_protocols=sum(counts_by_date.values()),
    )

    return {
        "year": year,
        "month": month,
        "counts_by_date": counts_by_date,
    }
