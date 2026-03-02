from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import Camera
from src.models.schemas import PipelineStatus
from src.models.db_session import get_db
from src.api.dependencies import get_ingestion
from src.services.video_ingestion import VideoIngestionService
from src.core.pipeline import get_pipeline_manager

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.post("/start/{camera_id}")
async def start_pipeline(
    camera_id: int,
    db: AsyncSession = Depends(get_db),
    ingestion: VideoIngestionService = Depends(get_ingestion),
):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(404, "Camera not found")
    if not camera.is_active:
        raise HTTPException(400, "Camera is not active")

    pm = get_pipeline_manager()
    if camera_id in pm.running_cameras:
        return {"status": "already_running", "camera_id": camera_id}

    await pm.start_camera(camera_id, camera.rtsp_url, camera.name)
    return {"status": "started", "camera_id": camera_id}


@router.post("/stop/{camera_id}")
async def stop_pipeline(camera_id: int):
    pm = get_pipeline_manager()
    await pm.stop_camera(camera_id)
    return {"status": "stopped", "camera_id": camera_id}


@router.get("/status", response_model=list[PipelineStatus])
async def pipeline_status(db: AsyncSession = Depends(get_db)):
    pm = get_pipeline_manager()
    cameras_result = await db.execute(select(Camera))
    cameras = {c.id: c for c in cameras_result.scalars().all()}
    statuses = []
    for cam_id, info in pm.camera_stats.items():
        cam = cameras.get(cam_id)
        statuses.append(PipelineStatus(
            camera_id=cam_id,
            camera_name=cam.name if cam else f"camera-{cam_id}",
            status="running" if cam_id in pm.running_cameras else "stopped",
            frames_processed=info.get("frames_processed", 0),
            detections=info.get("detections", 0),
            anomalies_found=info.get("anomalies_found", 0),
            started_at=info.get("started_at"),
        ))
    return statuses


@router.post("/start-all")
async def start_all(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.is_active == True))
    cameras = result.scalars().all()
    pm = get_pipeline_manager()
    started = []
    for cam in cameras:
        if cam.id not in pm.running_cameras:
            await pm.start_camera(cam.id, cam.rtsp_url, cam.name)
            started.append(cam.id)
    return {"started": started, "count": len(started)}


@router.post("/stop-all")
async def stop_all():
    pm = get_pipeline_manager()
    await pm.stop_all()
    return {"status": "all_stopped"}
