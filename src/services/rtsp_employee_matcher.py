from __future__ import annotations

import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select

from src.models.db_session import async_session_factory
from src.models.database import Employee
from src.services.employee_identifier import EmployeeIdentifier
from src.services.centralized_detection_service import CentralizedDetectionService
from src.services.person_detector import Detection


class RTSPEmployeeMatcher:
    def __init__(
        self,
        identifier: Optional[EmployeeIdentifier] = None,
        similarity_threshold: float = 0.6,
        dedup_seconds: int = 60,
        refresh_seconds: int = 300,
    ):
        self._identifier = identifier or EmployeeIdentifier()
        self._similarity_threshold = similarity_threshold
        self._central = CentralizedDetectionService(dedup_seconds=dedup_seconds)

        self._refresh_seconds = refresh_seconds
        self._employees_cache: list[tuple[int, str, list[float]]] = []
        self._last_refresh_ts: float = 0.0

    async def _refresh_employees_if_needed(self, now_ts: float) -> None:
        if self._employees_cache and (now_ts - self._last_refresh_ts) < self._refresh_seconds:
            return

        async with async_session_factory() as db:
            result = await db.execute(select(Employee))
            employees = result.scalars().all()
            self._employees_cache = [(e.id, e.name, list(e.embedding)) for e in employees]

        self._last_refresh_ts = now_ts
        logger.debug(f"RTSPEmployeeMatcher cache refreshed: {len(self._employees_cache)} employees")

    async def process_frame(
        self,
        camera_id: int,
        frame_bgr,
        timestamp_unix: float,
    ) -> None:
        try:
            await self._refresh_employees_if_needed(timestamp_unix)
            if not self._employees_cache:
                return

            emb_res = self._identifier.detect_and_embed(frame_bgr)
            if emb_res is None:
                return

            match = self._identifier.match_employee(
                emb_res.embedding,
                self._employees_cache,
                threshold=self._similarity_threshold,
            )
            if match is None:
                return

            employee_id, _, score = match
            ts = datetime.datetime.utcfromtimestamp(timestamp_unix)

            async with async_session_factory() as db:
                await self._central.record_detection(
                    db,
                    employee_id=employee_id,
                    camera_id=camera_id,
                    timestamp=ts,
                    confidence=score,
                )
                await db.commit()

        except Exception as e:
            logger.error(f"RTSP employee match failed (camera_id={camera_id}): {e}")

    async def process_detections(
        self,
        camera_id: int,
        frame_bgr,
        detections: list[Detection],
        timestamp_unix: float,
    ) -> None:
        """Try to identify employees in an RTSP frame.

        Uses existing person detections to crop likely face regions (upper portion of bbox)
        and runs face embedding matching on those crops.
        """
        try:
            await self._refresh_employees_if_needed(timestamp_unix)
            if not self._employees_cache:
                return

            if frame_bgr is None or not detections:
                return

            h, w = frame_bgr.shape[:2]
            ts = datetime.datetime.utcfromtimestamp(timestamp_unix)

            for d in detections[:5]:
                x1 = max(0, min(w - 1, int(d.x1)))
                y1 = max(0, min(h - 1, int(d.y1)))
                x2 = max(0, min(w, int(d.x2)))
                y2 = max(0, min(h, int(d.y2)))
                if x2 <= x1 or y2 <= y1:
                    continue

                person_crop = frame_bgr[y1:y2, x1:x2]
                if person_crop.size == 0:
                    continue

                ph, pw = person_crop.shape[:2]
                face_crop = person_crop[0 : max(1, int(ph * 0.6)), :]

                emb_res = self._identifier.detect_and_embed(face_crop)
                if emb_res is None:
                    continue

                match = self._identifier.match_employee(
                    emb_res.embedding,
                    self._employees_cache,
                    threshold=self._similarity_threshold,
                )
                if match is None:
                    continue

                employee_id, _, score = match
                async with async_session_factory() as db:
                    saved = await self._central.record_detection(
                        db,
                        employee_id=employee_id,
                        camera_id=camera_id,
                        timestamp=ts,
                        confidence=score,
                    )
                    await db.commit()
                if saved is not None:
                    break

        except Exception as e:
            logger.error(f"RTSP employee match failed (camera_id={camera_id}): {e}")
