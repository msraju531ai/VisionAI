from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import Optional

import cv2
from loguru import logger
from sqlalchemy import select

from src.models.db_session import async_session_factory
from src.models.database import DemoVideo, DemoDetection, Employee
from src.services.employee_identifier import EmployeeIdentifier


class VideoDemoProcessor:
    def __init__(
        self,
        identifier: Optional[EmployeeIdentifier] = None,
        frame_sample_interval_seconds: float = 1.0,
        similarity_threshold: float = 0.6,
    ):
        self._identifier = identifier or EmployeeIdentifier()
        self._frame_sample_interval_seconds = frame_sample_interval_seconds
        self._similarity_threshold = similarity_threshold

    def start_background(self, demo_video_id: int) -> None:
        asyncio.create_task(self.process_video(demo_video_id))

    async def process_video(self, demo_video_id: int) -> None:
        video_path = await self._load_video_path(demo_video_id)
        employees = await self._load_employees()

        if not employees:
            await self._mark_failed(demo_video_id, "No employees registered. Register at least one employee before processing videos.")
            return

        await self._mark_processing(demo_video_id)

        loop = asyncio.get_running_loop()

        try:
            await asyncio.to_thread(
                self._process_video_thread,
                loop,
                demo_video_id,
                video_path,
                employees,
            )
            await self._finalize_video(demo_video_id, status="completed")
        except Exception as e:
            logger.exception(f"Demo video processing failed for video_id={demo_video_id}: {e}")
            await self._mark_failed(demo_video_id, str(e))

    def _process_video_thread(
        self,
        loop: asyncio.AbstractEventLoop,
        demo_video_id: int,
        video_path: Path,
        employees: list[tuple[int, str, list[float]]],
    ) -> None:
        cap: Optional[cv2.VideoCapture] = None
        try:
            if not video_path.exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise RuntimeError(f"Failed to open video: {video_path}")

            fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            frame_step = max(1, int(round(fps * self._frame_sample_interval_seconds)))

            frame_index = 0
            processed = 0

            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if frame_index % frame_step != 0:
                    frame_index += 1
                    continue

                timestamp_seconds = frame_index / fps if fps > 0 else 0.0

                res = self._identifier.detect_and_embed(frame)
                if res is not None:
                    match = self._identifier.match_employee(
                        res.embedding,
                        employees,
                        threshold=self._similarity_threshold,
                    )
                    if match is not None:
                        emp_id, _, score = match
                        fut = asyncio.run_coroutine_threadsafe(
                            self._save_detection(
                                demo_video_id=demo_video_id,
                                employee_id=emp_id,
                                timestamp_seconds=timestamp_seconds,
                                confidence=score,
                                frame_index=frame_index,
                                metadata={"bbox_xywh": list(res.bbox_xywh)},
                            ),
                            loop,
                        )
                        fut.result(timeout=30)

                processed += 1
                if processed % 25 == 0:
                    fut = asyncio.run_coroutine_threadsafe(
                        self._update_progress(demo_video_id, processed),
                        loop,
                    )
                    fut.result(timeout=30)

                frame_index += 1

            fut = asyncio.run_coroutine_threadsafe(
                self._update_progress(demo_video_id, processed),
                loop,
            )
            fut.result(timeout=30)

            logger.info(f"Demo video processed: id={demo_video_id}, frames_sampled={processed}, total_frames={total_frames}")

        finally:
            if cap is not None:
                cap.release()

    async def _load_video_path(self, demo_video_id: int) -> Path:
        async with async_session_factory() as db:
            result = await db.execute(select(DemoVideo).where(DemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                raise RuntimeError(f"DemoVideo {demo_video_id} not found")
            return Path(video.video_path)

    async def _load_employees(self) -> list[tuple[int, str, list[float]]]:
        async with async_session_factory() as db:
            result = await db.execute(select(Employee))
            employees = result.scalars().all()
            return [(e.id, e.name, list(e.embedding)) for e in employees]

    async def _save_detection(
        self,
        demo_video_id: int,
        employee_id: int,
        timestamp_seconds: float,
        confidence: float,
        frame_index: Optional[int],
        metadata: Optional[dict] = None,
    ) -> None:
        async with async_session_factory() as db:
            det = DemoDetection(
                video_id=demo_video_id,
                employee_id=employee_id,
                timestamp_seconds=timestamp_seconds,
                confidence=confidence,
                frame_index=frame_index,
                metadata_json=metadata,
            )
            db.add(det)
            await db.commit()

    async def _update_progress(self, demo_video_id: int, processed_frames: int) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(DemoVideo).where(DemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.processed_frames = processed_frames
            await db.commit()

    async def _mark_processing(self, demo_video_id: int) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(DemoVideo).where(DemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                raise RuntimeError(f"DemoVideo {demo_video_id} not found")
            video.status = "processing"
            video.started_at = datetime.datetime.utcnow()
            video.finished_at = None
            video.error_message = None
            await db.commit()

    async def _mark_failed(self, demo_video_id: int, error_message: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(DemoVideo).where(DemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.status = "failed"
            video.error_message = error_message
            video.finished_at = datetime.datetime.utcnow()
            await db.commit()

    async def _finalize_video(self, demo_video_id: int, status: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(DemoVideo).where(DemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.status = status
            video.finished_at = datetime.datetime.utcnow()
            await db.commit()
