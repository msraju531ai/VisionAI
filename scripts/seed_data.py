"""
Seeds the database with sample cameras, zones, and shift schedules for local testing.
Run: python -m scripts.seed_data
"""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.db_session import async_session_factory, init_db
from src.models.database import Camera, Zone, ShiftSchedule


async def seed():
    await init_db()

    async with async_session_factory() as db:
        # Cameras
        cameras = [
            Camera(name="Warehouse Entry", location="Warehouse A - Main Gate", rtsp_url="rtsp://192.168.1.101:554/stream1"),
            Camera(name="Assembly Line 1", location="Manufacturing Floor - Line 1", rtsp_url="rtsp://192.168.1.102:554/stream1"),
            Camera(name="Loading Dock", location="Warehouse B - Dock 3", rtsp_url="rtsp://192.168.1.103:554/stream1"),
            Camera(name="Storage Area", location="Warehouse A - Rack Section C", rtsp_url="rtsp://192.168.1.104:554/stream1"),
            Camera(name="Office Corridor", location="Admin Building - 2nd Floor", rtsp_url="rtsp://192.168.1.105:554/stream1"),
        ]
        db.add_all(cameras)
        await db.flush()

        # Zones
        zones = [
            Zone(camera_id=cameras[0].id, name="Entry Gate", zone_type="entry_exit",
                 polygon_points=[[0.3, 0.2], [0.7, 0.2], [0.7, 0.9], [0.3, 0.9]]),
            Zone(camera_id=cameras[1].id, name="Machine Area", zone_type="equipment",
                 polygon_points=[[0.1, 0.1], [0.6, 0.1], [0.6, 0.8], [0.1, 0.8]]),
            Zone(camera_id=cameras[1].id, name="Electrical Panel", zone_type="restricted",
                 polygon_points=[[0.7, 0.0], [1.0, 0.0], [1.0, 0.3], [0.7, 0.3]]),
            Zone(camera_id=cameras[3].id, name="High-Value Storage", zone_type="restricted",
                 polygon_points=[[0.0, 0.0], [0.4, 0.0], [0.4, 0.5], [0.0, 0.5]]),
        ]
        db.add_all(zones)

        # Shift Schedules
        shifts = [
            ShiftSchedule(
                name="Day Shift",
                start_time="06:00", end_time="14:00",
                days_of_week=["mon", "tue", "wed", "thu", "fri"],
                expected_min_workers=5, expected_supervisor_walkthroughs=3,
            ),
            ShiftSchedule(
                name="Evening Shift",
                start_time="14:00", end_time="22:00",
                days_of_week=["mon", "tue", "wed", "thu", "fri"],
                expected_min_workers=4, expected_supervisor_walkthroughs=2,
            ),
            ShiftSchedule(
                name="Night Shift",
                start_time="22:00", end_time="06:00",
                days_of_week=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                expected_min_workers=2, expected_supervisor_walkthroughs=2,
            ),
        ]
        db.add_all(shifts)

        await db.commit()
        print(f"Seeded {len(cameras)} cameras, {len(zones)} zones, {len(shifts)} shift schedules")


if __name__ == "__main__":
    asyncio.run(seed())
