from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import EmployeeDetection
from src.services.attendance_service import AttendanceService
from src.services.compliance_service import ComplianceService


class CentralizedDetectionService:
    def __init__(self, dedup_seconds: int = 60):
        self._dedup_seconds = dedup_seconds
        self._attendance = AttendanceService()
        self._compliance = ComplianceService()

    async def record_detection(
        self,
        db: AsyncSession,
        employee_id: int,
        camera_id: int | None,
        timestamp: datetime.datetime,
        confidence: float,
    ) -> EmployeeDetection | None:
        last_stmt = (
            select(EmployeeDetection)
            .where(EmployeeDetection.employee_id == employee_id)
            .order_by(EmployeeDetection.timestamp.desc())
            .limit(1)
        )
        last = (await db.execute(last_stmt)).scalar_one_or_none()
        if last is not None:
            delta = (timestamp - last.timestamp).total_seconds()
            if delta >= 0 and delta < self._dedup_seconds:
                return None

        det = EmployeeDetection(
            employee_id=employee_id,
            camera_id=camera_id,
            timestamp=timestamp,
            confidence=confidence,
        )
        db.add(det)
        await db.flush()

        att = await self._attendance.update_from_detection(db, employee_id, timestamp)
        await self._compliance.evaluate_for_day(db, employee_id, att.date)

        return det
