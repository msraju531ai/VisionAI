from __future__ import annotations

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_session import get_db
from src.models.database import Employee, EmployeeAttendance, AttendanceCompliance

router = APIRouter(tags=["Attendance"])
templates = Jinja2Templates(directory="templates")


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_page(request: Request, db: AsyncSession = Depends(get_db)):
    today = datetime.date.today().isoformat()

    stmt = (
        select(Employee, EmployeeAttendance, AttendanceCompliance)
        .join(EmployeeAttendance, EmployeeAttendance.employee_id == Employee.id, isouter=True)
        .join(
            AttendanceCompliance,
            and_(AttendanceCompliance.employee_id == Employee.id, AttendanceCompliance.date == today),
            isouter=True,
        )
        .where((EmployeeAttendance.date == today) | (EmployeeAttendance.date.is_(None)))
        .order_by(Employee.name.asc())
    )

    rows = (await db.execute(stmt)).all()
    items = []
    for emp, att, comp in rows:
        items.append(
            {
                "employee_name": emp.name,
                "check_in": getattr(att, "first_seen", None),
                "check_out": getattr(att, "last_seen", None),
                "total_minutes": getattr(att, "total_minutes", 0) if att else 0,
                "status": getattr(comp, "status", "absent") if comp else "absent",
                "deviation_minutes": getattr(comp, "deviation_minutes", 0) if comp else 0,
            }
        )

    return templates.TemplateResponse(
        "attendance.html",
        {"request": request, "items": items, "date": today},
    )


@router.get("/api/attendance/daily")
async def attendance_daily(
    date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: AsyncSession = Depends(get_db),
):
    date_key = date or datetime.date.today().isoformat()

    stmt = (
        select(Employee, EmployeeAttendance)
        .join(EmployeeAttendance, EmployeeAttendance.employee_id == Employee.id, isouter=True)
        .where((EmployeeAttendance.date == date_key) | (EmployeeAttendance.date.is_(None)))
        .order_by(Employee.name.asc())
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            "employee_id": emp.id,
            "employee_name": emp.name,
            "date": date_key,
            "first_seen": att.first_seen.isoformat() if att else None,
            "last_seen": att.last_seen.isoformat() if att else None,
            "total_minutes": att.total_minutes if att else 0,
        }
        for emp, att in rows
    ]


@router.get("/api/attendance/{employee_id}")
async def attendance_for_employee(
    employee_id: int,
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    filters = [EmployeeAttendance.employee_id == employee_id]
    if start_date:
        filters.append(EmployeeAttendance.date >= start_date)
    if end_date:
        filters.append(EmployeeAttendance.date <= end_date)

    stmt = select(EmployeeAttendance).where(and_(*filters)).order_by(EmployeeAttendance.date.desc()).limit(90)
    atts = (await db.execute(stmt)).scalars().all()

    return [
        {
            "employee_id": a.employee_id,
            "date": a.date,
            "first_seen": a.first_seen.isoformat(),
            "last_seen": a.last_seen.isoformat(),
            "total_minutes": a.total_minutes,
        }
        for a in atts
    ]


@router.get("/api/compliance/daily")
async def compliance_daily(
    date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: AsyncSession = Depends(get_db),
):
    date_key = date or datetime.date.today().isoformat()

    stmt = (
        select(Employee, AttendanceCompliance)
        .join(AttendanceCompliance, AttendanceCompliance.employee_id == Employee.id, isouter=True)
        .where((AttendanceCompliance.date == date_key) | (AttendanceCompliance.date.is_(None)))
        .order_by(Employee.name.asc())
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            "employee_id": emp.id,
            "employee_name": emp.name,
            "date": date_key,
            "status": comp.status if comp else "absent",
            "deviation_minutes": comp.deviation_minutes if comp else 0,
        }
        for emp, comp in rows
    ]
