from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_session import get_db
from src.models.database import WorkSchedule, Employee

router = APIRouter(prefix="/schedule", tags=["Schedule"])


class WorkScheduleIn(BaseModel):
    employee_id: int
    expected_start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    expected_end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    grace_minutes: int = Field(10, ge=0, le=180)


@router.post("/", summary="Upsert an employee work schedule")
async def upsert_schedule(payload: WorkScheduleIn, db: AsyncSession = Depends(get_db)):
    emp = (await db.execute(select(Employee).where(Employee.id == payload.employee_id))).scalar_one_or_none()
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    sched = (await db.execute(select(WorkSchedule).where(WorkSchedule.employee_id == payload.employee_id))).scalar_one_or_none()

    if sched is None:
        sched = WorkSchedule(
            employee_id=payload.employee_id,
            expected_start_time=payload.expected_start_time,
            expected_end_time=payload.expected_end_time,
            grace_minutes=payload.grace_minutes,
        )
        db.add(sched)
    else:
        sched.expected_start_time = payload.expected_start_time
        sched.expected_end_time = payload.expected_end_time
        sched.grace_minutes = payload.grace_minutes

    await db.commit()
    return {"ok": True, "employee_id": payload.employee_id}
