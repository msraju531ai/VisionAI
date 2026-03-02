from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import ShiftSchedule
from src.models.schemas import ShiftScheduleCreate, ShiftScheduleOut
from src.models.db_session import get_db
from src.api.dependencies import get_shift_scheduler
from src.core.scheduler import ShiftScheduler, Shift

router = APIRouter(prefix="/shifts", tags=["Shift Schedules"])


@router.get("/", response_model=list[ShiftScheduleOut])
async def list_shifts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ShiftSchedule).order_by(ShiftSchedule.id))
    return result.scalars().all()


@router.post("/", response_model=ShiftScheduleOut, status_code=201)
async def create_shift(
    payload: ShiftScheduleCreate,
    db: AsyncSession = Depends(get_db),
    scheduler: ShiftScheduler = Depends(get_shift_scheduler),
):
    shift = ShiftSchedule(**payload.model_dump())
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    await _sync_scheduler(db, scheduler)
    return shift


@router.delete("/{shift_id}", status_code=204)
async def delete_shift(
    shift_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: ShiftScheduler = Depends(get_shift_scheduler),
):
    result = await db.execute(select(ShiftSchedule).where(ShiftSchedule.id == shift_id))
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(404, "Shift not found")
    await db.delete(shift)
    await db.commit()
    await _sync_scheduler(db, scheduler)


@router.get("/current")
async def current_shift(scheduler: ShiftScheduler = Depends(get_shift_scheduler)):
    shift = scheduler.get_current_shift()
    if not shift:
        return {"active": False, "message": "No active shift"}
    return {
        "active": True,
        "name": shift.name,
        "expected_workers": shift.expected_min_workers,
        "is_night_shift": scheduler.is_night_shift(),
    }


async def _sync_scheduler(db: AsyncSession, scheduler: ShiftScheduler):
    result = await db.execute(select(ShiftSchedule).where(ShiftSchedule.is_active == True))
    db_shifts = result.scalars().all()
    scheduler.load_shifts([
        Shift(s.id, s.name, s.start_time, s.end_time, s.days_of_week,
              s.expected_min_workers, s.expected_supervisor_walkthroughs)
        for s in db_shifts
    ])
