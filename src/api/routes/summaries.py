from __future__ import annotations

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import IncidentSummary
from src.models.schemas import IncidentSummaryOut
from src.models.db_session import get_db
from src.services.incident_summarizer import IncidentSummarizer
from src.api.dependencies import get_incident_summarizer

router = APIRouter(prefix="/summaries", tags=["Incident Summaries"])


@router.get("/", response_model=list[IncidentSummaryOut])
async def list_summaries(
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IncidentSummary).order_by(desc(IncidentSummary.created_at)).limit(limit)
    )
    return result.scalars().all()


@router.post("/generate", response_model=IncidentSummaryOut)
async def generate_summary(
    period_start: datetime.datetime,
    period_end: datetime.datetime,
    camera_ids: Optional[str] = Query(None, description="Comma-separated camera IDs"),
    summarizer: IncidentSummarizer = Depends(get_incident_summarizer),
    db: AsyncSession = Depends(get_db),
):
    cam_ids = [int(x) for x in camera_ids.split(",")] if camera_ids else None
    summary = await summarizer.generate_summary(period_start, period_end, cam_ids)
    await db.commit()
    return summary
