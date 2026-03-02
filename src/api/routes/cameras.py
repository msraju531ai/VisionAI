from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import Camera
from src.models.schemas import CameraCreate, CameraUpdate, CameraOut
from src.models.db_session import get_db

router = APIRouter(prefix="/cameras", tags=["Cameras"])


@router.get("/", response_model=list[CameraOut])
async def list_cameras(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).order_by(Camera.id))
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


@router.post("/", response_model=CameraOut, status_code=201)
async def create_camera(payload: CameraCreate, db: AsyncSession = Depends(get_db)):
    cam = Camera(**payload.model_dump())
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    return cam


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: int, payload: CameraUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cam, field, value)
    await db.commit()
    await db.refresh(cam)
    return cam


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = result.scalar_one_or_none()
    if not cam:
        raise HTTPException(404, "Camera not found")
    await db.delete(cam)
    await db.commit()
