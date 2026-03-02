from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import Camera, Event, Alert
from src.models.schemas import DashboardStats, CameraOut, EventOut
from src.models.db_session import get_db
from src.utils.time_utils import start_of_today, hours_ago

router = APIRouter(tags=["Dashboard"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/api/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    today = start_of_today()
    one_hour_ago = hours_ago(1)

    cameras_result = await db.execute(select(Camera).where(Camera.is_active == True))
    cameras = cameras_result.scalars().all()

    events_today_count = (await db.execute(
        select(func.count(Event.id)).where(Event.timestamp >= today)
    )).scalar() or 0

    unack_count = (await db.execute(
        select(func.count(Alert.id)).where(Alert.status == "pending")
    )).scalar() or 0

    anomalies_hour = (await db.execute(
        select(func.count(Event.id)).where(Event.timestamp >= one_hour_ago)
    )).scalar() or 0

    recent_result = await db.execute(
        select(Event).order_by(Event.timestamp.desc()).limit(10)
    )
    recent_events = recent_result.scalars().all()

    return DashboardStats(
        active_cameras=len(cameras),
        total_events_today=events_today_count,
        unacknowledged_alerts=unack_count,
        anomalies_last_hour=anomalies_hour,
        cameras_online=[CameraOut.model_validate(c) for c in cameras],
        recent_events=[EventOut.model_validate(e) for e in recent_events],
    )
