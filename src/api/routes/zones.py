from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import Zone
from src.models.schemas import ZoneCreate, ZoneOut
from src.models.db_session import get_db
from src.api.dependencies import get_zone_manager
from src.services.zone_manager import ZoneManager, ZoneDefinition

router = APIRouter(prefix="/zones", tags=["Zones"])


@router.get("/", response_model=list[ZoneOut])
async def list_zones(camera_id: int | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Zone)
    if camera_id is not None:
        stmt = stmt.where(Zone.camera_id == camera_id)
    result = await db.execute(stmt.order_by(Zone.id))
    return result.scalars().all()


@router.post("/", response_model=ZoneOut, status_code=201)
async def create_zone(
    payload: ZoneCreate,
    db: AsyncSession = Depends(get_db),
    zm: ZoneManager = Depends(get_zone_manager),
):
    zone = Zone(**payload.model_dump())
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    await _sync_zone_manager(zone.camera_id, db, zm)
    return zone


@router.delete("/{zone_id}", status_code=204)
async def delete_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    zm: ZoneManager = Depends(get_zone_manager),
):
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(404, "Zone not found")
    camera_id = zone.camera_id
    await db.delete(zone)
    await db.commit()
    await _sync_zone_manager(camera_id, db, zm)


async def _sync_zone_manager(camera_id: int, db: AsyncSession, zm: ZoneManager):
    result = await db.execute(
        select(Zone).where(Zone.camera_id == camera_id, Zone.is_active == True)
    )
    db_zones = result.scalars().all()
    zm.set_zones(camera_id, [
        ZoneDefinition(z.id, z.name, z.zone_type, z.polygon_points) for z in db_zones
    ])
