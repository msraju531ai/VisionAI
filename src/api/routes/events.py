from __future__ import annotations

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.schemas import EventOut
from src.models.db_session import get_db
from src.services.event_logger import EventLogger
from src.api.dependencies import get_event_logger

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("/", response_model=list[EventOut])
async def search_events(
    camera_id: Optional[int] = Query(None),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    start_time: Optional[datetime.datetime] = Query(None),
    end_time: Optional[datetime.datetime] = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    logger: EventLogger = Depends(get_event_logger),
):
    return await logger.search_events(
        camera_id=camera_id,
        event_type=event_type,
        severity=severity,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )


@router.get("/count")
async def count_events(
    start_time: Optional[datetime.datetime] = Query(None),
    end_time: Optional[datetime.datetime] = Query(None),
    event_type: Optional[str] = Query(None),
    logger: EventLogger = Depends(get_event_logger),
):
    count = await logger.count_events(start_time=start_time, end_time=end_time, event_type=event_type)
    return {"count": count}


@router.post("/{event_id}/acknowledge")
async def acknowledge_event(event_id: int, el: EventLogger = Depends(get_event_logger), db: AsyncSession = Depends(get_db)):
    event = await el.acknowledge_event(event_id)
    if not event:
        return {"error": "Event not found"}, 404
    await db.commit()
    return {"acknowledged": True, "event_id": event_id}
