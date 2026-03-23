from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import AttendanceCompliance, EmployeeAttendance, WorkSchedule


class ComplianceService:
    @staticmethod
    def _date_key(dt: datetime.datetime) -> str:
        return dt.date().isoformat()

    @staticmethod
    def _parse_hhmm(hhmm: str) -> datetime.time:
        parts = hhmm.split(":")
        return datetime.time(int(parts[0]), int(parts[1]))

    async def evaluate_for_day(
        self,
        db: AsyncSession,
        employee_id: int,
        date_key: str,
    ) -> AttendanceCompliance:
        sched_res = await db.execute(
            select(WorkSchedule).where(WorkSchedule.employee_id == employee_id)
        )
        schedule = sched_res.scalar_one_or_none()

        comp_res = await db.execute(
            select(AttendanceCompliance)
            .where(AttendanceCompliance.employee_id == employee_id)
            .where(AttendanceCompliance.date == date_key)
        )
        comp = comp_res.scalar_one_or_none()

        if schedule is None:
            if comp is None:
                comp = AttendanceCompliance(
                    employee_id=employee_id,
                    date=date_key,
                    status="absent",
                    deviation_minutes=0,
                )
                db.add(comp)
                await db.flush()
            return comp

        att_res = await db.execute(
            select(EmployeeAttendance)
            .where(EmployeeAttendance.employee_id == employee_id)
            .where(EmployeeAttendance.date == date_key)
        )
        att = att_res.scalar_one_or_none()

        expected_start = self._parse_hhmm(schedule.expected_start_time)
        expected_end = self._parse_hhmm(schedule.expected_end_time)

        day = datetime.date.fromisoformat(date_key)
        expected_start_dt = datetime.datetime.combine(day, expected_start)
        expected_end_dt = datetime.datetime.combine(day, expected_end)

        grace = datetime.timedelta(minutes=schedule.grace_minutes)

        status = "compliant"
        deviation = 0

        if att is None:
            status = "absent"
            deviation = 0
        else:
            late_by = max(
                0,
                int(((att.first_seen - (expected_start_dt + grace)).total_seconds()) // 60),
            )
            early_exit_by = max(
                0,
                int((((expected_end_dt - grace) - att.last_seen).total_seconds()) // 60),
            )

            if late_by > 0 and early_exit_by > 0:
                if late_by >= early_exit_by:
                    status = "late"
                    deviation = late_by
                else:
                    status = "early_exit"
                    deviation = early_exit_by
            elif late_by > 0:
                status = "late"
                deviation = late_by
            elif early_exit_by > 0:
                status = "early_exit"
                deviation = early_exit_by
            else:
                status = "compliant"
                deviation = 0

        if comp is None:
            comp = AttendanceCompliance(
                employee_id=employee_id,
                date=date_key,
                status=status,
                deviation_minutes=deviation,
            )
            db.add(comp)
        else:
            comp.status = status
            comp.deviation_minutes = deviation

        await db.flush()
        return comp
