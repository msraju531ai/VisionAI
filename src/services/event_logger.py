"""
Persists anomaly events to the database and provides searchable query access.
"""

from __future__ import annotations

import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import Event
from src.services.anomaly_detector import AnomalyEvent


class EventLogger:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def log_event(self, anomaly: AnomalyEvent) -> Event:
        event = Event(
            camera_id=anomaly.camera_id,
            event_type=anomaly.event_type,
            severity=anomaly.severity,
            description=anomaly.description,
            zone_id=anomaly.zone_id,
            frame_path=anomaly.frame_path,
            metadata_json=anomaly.metadata,
            timestamp=anomaly.timestamp,
        )
        self._db.add(event)
        await self._db.flush()
        logger.info(f"Logged event {event.id}: {anomaly.event_type} on camera {anomaly.camera_id}")
        return event

    async def search_events(
        self,
        camera_id: Optional[int] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        filters = []
        if camera_id is not None:
            filters.append(Event.camera_id == camera_id)
        if event_type:
            filters.append(Event.event_type == event_type)
        if severity:
            filters.append(Event.severity == severity)
        if start_time:
            filters.append(Event.timestamp >= start_time)
        if end_time:
            filters.append(Event.timestamp <= end_time)

        stmt = (
            select(Event)
            .where(and_(*filters) if filters else True)
            .order_by(desc(Event.timestamp))
            .offset(offset)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def count_events(
        self,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        event_type: Optional[str] = None,
    ) -> int:
        filters = []
        if start_time:
            filters.append(Event.timestamp >= start_time)
        if end_time:
            filters.append(Event.timestamp <= end_time)
        if event_type:
            filters.append(Event.event_type == event_type)

        stmt = select(func.count(Event.id)).where(and_(*filters) if filters else True)
        result = await self._db.execute(stmt)
        return result.scalar() or 0

    async def acknowledge_event(self, event_id: int) -> Optional[Event]:
        result = await self._db.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one_or_none()
        if event:
            event.is_acknowledged = True
            await self._db.flush()
        return event

    async def get_recent_events(self, limit: int = 20) -> list[Event]:
        stmt = select(Event).order_by(desc(Event.timestamp)).limit(limit)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_unacknowledged_count(self) -> int:
        stmt = select(func.count(Event.id)).where(Event.is_acknowledged == False)
        result = await self._db.execute(stmt)
        return result.scalar() or 0
