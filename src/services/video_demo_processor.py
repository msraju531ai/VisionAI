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
from src.services.centralized_detection_service import CentralizedDetectionService
from src.services.person_detector import PersonDetector


class VideoDemoProcessor:
    def __init__(
        self,
        identifier: Optional[EmployeeIdentifier] = None,
        person_detector: Optional[PersonDetector] = None,
        frame_sample_interval_seconds: float = 2.0,
        similarity_threshold: float = 0.70,
    ):
        self._identifier = identifier or EmployeeIdentifier()
        self._person_detector = person_detector or PersonDetector()
        self._frame_sample_interval_seconds = frame_sample_interval_seconds
        self._similarity_threshold = similarity_threshold
        self._central = CentralizedDetectionService(dedup_seconds=60)

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
            total_samples = (total_frames + frame_step - 1) // frame_step if total_frames > 0 else None

            fut = asyncio.run_coroutine_threadsafe(
                self._set_total_samples(demo_video_id, total_samples), loop
            )
            fut.result(timeout=30)

            frame_index = 0
            processed = 0
            # Centroid cache: once an employee is matched, carry their identity
            # forward so face detection isn't needed on every single frame.
            # list of (cx, cy, emp_id, score)
            authorized_cache: list[tuple[float, float, int, float]] = []
            _CACHE_DIST = 100.0  # pixels
            # One detection record per employee per video — reset for each new video
            saved_this_video: set[int] = set()

            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if frame_index % frame_step != 0:
                    frame_index += 1
                    continue

                timestamp_seconds = frame_index / fps if fps > 0 else 0.0
                h_frame, w_frame = frame.shape[:2]

                # Step 1: detect all persons with YOLO
                detections = self._person_detector.detect(frame, person_only=True)

                new_authorized_cache: list[tuple[float, float, int, float]] = []

                for d in detections:
                    x1 = max(0, min(w_frame - 1, int(d.x1)))
                    y1 = max(0, min(h_frame - 1, int(d.y1)))
                    x2 = max(0, min(w_frame, int(d.x2)))
                    y2 = max(0, min(h_frame, int(d.y2)))
                    if x2 <= x1 or y2 <= y1:
                        continue

                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0

                    emp_id: Optional[int] = None
                    score: Optional[float] = None

                    # Step 2: check centroid cache first
                    for prev_cx, prev_cy, prev_id, prev_score in authorized_cache:
                        dist = ((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2) ** 0.5
                        if dist <= _CACHE_DIST:
                            emp_id = prev_id
                            score = prev_score
                            break

                    # Step 3: run DeepFace on face crop only (top 50% of bbox)
                    if emp_id is None and employees:
                        person_crop = frame[y1:y2, x1:x2]
                        if person_crop.size > 0:
                            ph = person_crop.shape[0]
                            face_crop = person_crop[0 : max(1, int(ph * 0.50)), :]

                            emb_res = self._identifier.detect_and_embed(face_crop)
                            if emb_res is not None:
                                match = self._identifier.match_employee(
                                    emb_res.embedding,
                                    employees,
                                    threshold=self._similarity_threshold,
                                )
                                if match is not None:
                                    emp_id, _, score = match

                    if emp_id is not None and score is not None:
                        new_authorized_cache.append((cx, cy, emp_id, score))

                        # Skip if this employee was already recorded in this video
                        if emp_id in saved_this_video:
                            continue
                        saved_this_video.add(emp_id)

                        fut = asyncio.run_coroutine_threadsafe(
                            self._save_detection(
                                demo_video_id=demo_video_id,
                                employee_id=emp_id,
                                timestamp_seconds=timestamp_seconds,
                                confidence=score,
                                frame_index=frame_index,
                                metadata={"bbox": [x1, y1, x2, y2]},
                            ),
                            loop,
                        )
                        fut.result(timeout=30)

                        det_ts = datetime.datetime.utcnow()
                        fut = asyncio.run_coroutine_threadsafe(
                            self._save_central_detection(
                                employee_id=emp_id,
                                camera_id=0,
                                timestamp=det_ts,
                                confidence=score,
                            ),
                            loop,
                        )
                        fut.result(timeout=30)

                authorized_cache = new_authorized_cache if new_authorized_cache else authorized_cache

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

    async def _save_central_detection(
        self,
        employee_id: int,
        camera_id: int | None,
        timestamp: datetime.datetime,
        confidence: float,
    ) -> None:
        async with async_session_factory() as db:
            await self._central.record_detection(
                db,
                employee_id=employee_id,
                camera_id=camera_id,
                timestamp=timestamp,
                confidence=confidence,
            )
            await db.commit()

    async def _set_total_samples(self, demo_video_id: int, total_samples: Optional[int]) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(DemoVideo).where(DemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.total_samples = total_samples
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
