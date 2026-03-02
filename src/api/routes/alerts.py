from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import Alert
from src.models.schemas import AlertOut
from src.models.db_session import get_db

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("/", response_model=list[AlertOut])
async def list_alerts(
    status: str | None = Query(None),
    channel: str | None = Query(None),
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Alert)
    if status:
        stmt = stmt.where(Alert.status == status)
    if channel:
        stmt = stmt.where(Alert.channel == channel)
    stmt = stmt.order_by(desc(Alert.created_at)).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
