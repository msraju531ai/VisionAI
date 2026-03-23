from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import EmployeeAttendance


class AttendanceService:
    def __init__(self, dedup_minutes: int = 1):
        self._dedup_minutes = dedup_minutes

    @staticmethod
    def _date_key(ts: datetime.datetime) -> str:
        return ts.date().isoformat()

    async def update_from_detection(
        self,
        db: AsyncSession,
        employee_id: int,
        timestamp: datetime.datetime,
    ) -> EmployeeAttendance:
        date_key = self._date_key(timestamp)

        result = await db.execute(
            select(EmployeeAttendance)
            .where(EmployeeAttendance.employee_id == employee_id)
            .where(EmployeeAttendance.date == date_key)
        )
        att = result.scalar_one_or_none()

        if att is None:
            att = EmployeeAttendance(
                employee_id=employee_id,
                date=date_key,
                first_seen=timestamp,
                last_seen=timestamp,
                total_minutes=0,
            )
            db.add(att)
            await db.flush()
            return att

        changed = False
        if timestamp < att.first_seen:
            att.first_seen = timestamp
            changed = True
        if timestamp > att.last_seen:
            att.last_seen = timestamp
            changed = True

        if changed:
            total_minutes = int((att.last_seen - att.first_seen).total_seconds() // 60)
            att.total_minutes = max(0, total_minutes)
            await db.flush()

        return att
