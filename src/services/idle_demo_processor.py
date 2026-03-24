from __future__ import annotations

import asyncio
import datetime
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
from loguru import logger
from sqlalchemy import select

from config.settings import settings
from src.models.db_session import async_session_factory
from src.models.database import Employee, IdleDemoVideo, IdleEvent
from src.services.activity_analyzer import ActivityAnalyzer
from src.services.centralized_detection_service import CentralizedDetectionService
from src.services.employee_identifier import EmployeeIdentifier
from src.services.person_detector import PersonDetector


@dataclass
class _TrackIdentity:
    employee_id: Optional[int]
    employee_name: str
    confidence: Optional[float]


class IdleDemoProcessor:
    def __init__(
        self,
        identifier: Optional[EmployeeIdentifier] = None,
        person_detector: Optional[PersonDetector] = None,
        activity_analyzer: Optional[ActivityAnalyzer] = None,
        frame_sample_interval_seconds: float = 1.0,
        similarity_threshold: float = 0.6,
    ):
        self._identifier = identifier or EmployeeIdentifier()
        self._person_detector = person_detector or PersonDetector()
        self._activity = activity_analyzer or ActivityAnalyzer()
        self._central = CentralizedDetectionService(dedup_seconds=60)
        self._frame_sample_interval_seconds = frame_sample_interval_seconds
        self._similarity_threshold = similarity_threshold

    def start_background(self, demo_video_id: int) -> None:
        asyncio.create_task(self.process_video(demo_video_id))

    async def process_video(self, demo_video_id: int) -> None:
        video_path = await self._load_video_path(demo_video_id)
        video_start_at = await self._load_video_start_at(demo_video_id)
        employees = await self._load_employees()
        await self._mark_processing(demo_video_id)

        loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(
                self._process_video_thread,
                loop,
                demo_video_id,
                video_path,
                video_start_at,
                employees,
            )
            await self._finalize_video(demo_video_id, status="completed")
        except Exception as e:
            logger.exception(f"Idle demo processing failed for video_id={demo_video_id}: {e}")
            await self._mark_failed(demo_video_id, str(e))

    def _process_video_thread(
        self,
        loop: asyncio.AbstractEventLoop,
        demo_video_id: int,
        video_path: Path,
        video_start_at: Optional[datetime.datetime],
        employees: list[tuple[int, str, list[float]]],
    ) -> None:
        cap: Optional[cv2.VideoCapture] = None
        writer: Optional[cv2.VideoWriter] = None

        track_identities: dict[int, _TrackIdentity] = {}
        idle_open: dict[int, float] = {}
        any_person_seen = False
        any_unauthorized_seen = False
        any_idle_seen = False

        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise RuntimeError(f"Failed to open video: {video_path}")

            fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            frame_step = max(1, int(round(fps * self._frame_sample_interval_seconds)))

            total_samples = (total_frames + frame_step - 1) // frame_step if total_frames > 0 else None
            fut = asyncio.run_coroutine_threadsafe(self._set_total_samples(demo_video_id, total_samples), loop)
            fut.result(timeout=30)

            out_path = self._output_path_for(video_path, demo_video_id)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))
            if not writer.isOpened():
                raise RuntimeError(f"Failed to open video writer for: {out_path}")

            fut = asyncio.run_coroutine_threadsafe(self._set_output_path(demo_video_id, out_path), loop)
            fut.result(timeout=30)

            frame_index = 0
            processed = 0

            # Use a fake camera_id namespace for the analyzer so it can track across frames
            camera_id = 10_000 + demo_video_id
            self._activity.clear_camera(camera_id)

            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if frame_index % frame_step != 0:
                    writer.write(frame)
                    frame_index += 1
                    continue

                t_seconds = frame_index / fps if fps > 0 else 0.0

                detections = self._person_detector.detect(frame, person_only=True)
                if detections:
                    any_person_seen = True
                tracks = self._activity.update(camera_id, detections, t_seconds)

                # Assign identity to tracks (best-effort) using face crop
                for tr in tracks:
                    if tr.person_id in track_identities:
                        continue

                    d = tr.last_detection
                    x1, y1, x2, y2 = self._clip_bbox(frame, d)
                    if x2 <= x1 or y2 <= y1:
                        continue

                    person_crop = frame[y1:y2, x1:x2]
                    if person_crop.size == 0:
                        continue

                    ph, pw = person_crop.shape[:2]
                    face_crop = person_crop[0 : max(1, int(ph * 0.6)), :]

                    identity = _TrackIdentity(employee_id=None, employee_name="Unauthorized", confidence=None)
                    if employees:
                        emb_res = self._identifier.detect_and_embed(face_crop)
                        if emb_res is not None:
                            match = self._identifier.match_employee(
                                emb_res.embedding,
                                employees,
                                threshold=self._similarity_threshold,
                            )

                            if match is not None:
                                emp_id, emp_name, score = match
                                identity = _TrackIdentity(employee_id=emp_id, employee_name=emp_name, confidence=score)

                    track_identities[tr.person_id] = identity

                # Draw tracks with color rules
                for tr in tracks:
                    d = tr.last_detection
                    x1, y1, x2, y2 = self._clip_bbox(frame, d)
                    if x2 <= x1 or y2 <= y1:
                        continue

                    identity = track_identities.get(tr.person_id)
                    is_authorized = bool(identity is not None and identity.employee_id is not None)

                    if not is_authorized:
                        any_unauthorized_seen = True

                    # Default colors
                    color = (0, 0, 255)  # red
                    label = "Unauthorized"

                    if is_authorized:
                        color = (0, 200, 0)  # green
                        if identity and identity.confidence is not None:
                            label = f"{identity.employee_name} ({identity.confidence:.2f})"
                        else:
                            label = identity.employee_name if identity else "Authorized"

                    # Idle overrides to yellow
                    if tr.is_idle:
                        any_idle_seen = True
                        color = (0, 215, 255)  # yellow-ish (BGR)
                        label = f"Idle: {label}"

                        if tr.person_id not in idle_open:
                            idle_open[tr.person_id] = t_seconds
                    else:
                        # close idle window if it was open
                        if tr.person_id in idle_open:
                            start_ts = idle_open.pop(tr.person_id)
                            end_ts = t_seconds
                            duration = max(0.0, end_ts - start_ts)
                            if duration >= settings.idle_threshold_seconds:
                                emp_id = identity.employee_id if identity else None
                                fut = asyncio.run_coroutine_threadsafe(
                                    self._save_idle_event(
                                        video_id=demo_video_id,
                                        employee_id=emp_id,
                                        start_ts=start_ts,
                                        end_ts=end_ts,
                                        duration=duration,
                                    ),
                                    loop,
                                )
                                fut.result(timeout=30)

                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(
                        frame,
                        label,
                        (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        color,
                        2,
                        cv2.LINE_AA,
                    )

                    if video_start_at is not None and is_authorized and identity and identity.employee_id is not None:
                        ts_dt = video_start_at + datetime.timedelta(seconds=float(t_seconds))
                        fut = asyncio.run_coroutine_threadsafe(
                            self._save_central_detection(
                                employee_id=identity.employee_id,
                                camera_id=0,
                                timestamp=ts_dt,
                                confidence=float(identity.confidence or 0.0),
                            ),
                            loop,
                        )
                        fut.result(timeout=30)

                writer.write(frame)

                processed += 1
                if processed % 25 == 0:
                    fut = asyncio.run_coroutine_threadsafe(self._update_progress(demo_video_id, processed), loop)
                    fut.result(timeout=30)

                frame_index += 1

            # Close any open idle windows at the end
            for pid, start_ts in list(idle_open.items()):
                end_ts = (frame_index / fps) if fps > 0 else start_ts
                duration = max(0.0, end_ts - start_ts)
                identity = track_identities.get(pid)
                if duration >= settings.idle_threshold_seconds:
                    fut = asyncio.run_coroutine_threadsafe(
                        self._save_idle_event(
                            video_id=demo_video_id,
                            employee_id=identity.employee_id if identity else None,
                            start_ts=start_ts,
                            end_ts=end_ts,
                            duration=duration,
                        ),
                        loop,
                    )
                    fut.result(timeout=30)

            fut = asyncio.run_coroutine_threadsafe(self._update_progress(demo_video_id, processed), loop)
            fut.result(timeout=30)

            outcome = "authorized"
            if (not any_person_seen) or any_idle_seen:
                outcome = "idle"
            elif any_unauthorized_seen:
                outcome = "unauthorized"
            fut = asyncio.run_coroutine_threadsafe(self._set_outcome_status(demo_video_id, outcome), loop)
            fut.result(timeout=30)

            # Transcode to H.264 for browser playback when ffmpeg is available.
            h264_path = self._h264_output_path_for(video_path, demo_video_id)
            if self._try_transcode_to_h264(out_path, h264_path):
                fut = asyncio.run_coroutine_threadsafe(self._set_output_path(demo_video_id, h264_path), loop)
                fut.result(timeout=30)

        finally:
            if cap is not None:
                cap.release()
            if writer is not None:
                writer.release()

    @staticmethod
    def _clip_bbox(frame_bgr, d) -> tuple[int, int, int, int]:
        h, w = frame_bgr.shape[:2]
        x1 = max(0, min(w - 1, int(d.x1)))
        y1 = max(0, min(h - 1, int(d.y1)))
        x2 = max(0, min(w, int(d.x2)))
        y2 = max(0, min(h, int(d.y2)))
        return x1, y1, x2, y2

    @staticmethod
    def _output_path_for(input_path: Path, demo_video_id: int) -> Path:
        base = Path("data") / "demo" / "idle" / "outputs"
        stem = input_path.stem
        return base / f"{stem}_idle_{demo_video_id}.mp4"

    @staticmethod
    def _h264_output_path_for(input_path: Path, demo_video_id: int) -> Path:
        base = Path("data") / "demo" / "idle" / "outputs"
        stem = input_path.stem
        return base / f"{stem}_idle_{demo_video_id}_h264.mp4"

    @staticmethod
    def _try_transcode_to_h264(src_path: Path, dst_path: Path) -> bool:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False

        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(src_path),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    "-an",
                    str(dst_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                logger.warning(f"ffmpeg transcode failed: {proc.stderr or proc.stdout}")
                return False
            return dst_path.exists() and dst_path.stat().st_size > 0
        except Exception as e:
            logger.warning(f"ffmpeg transcode error: {e}")
            return False

    async def _load_video_path(self, demo_video_id: int) -> Path:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                raise RuntimeError(f"IdleDemoVideo {demo_video_id} not found")
            return Path(video.video_path)

    async def _load_video_start_at(self, demo_video_id: int) -> Optional[datetime.datetime]:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return None
            return getattr(video, "video_start_at", None)

    async def _load_employees(self) -> list[tuple[int, str, list[float]]]:
        async with async_session_factory() as db:
            result = await db.execute(select(Employee))
            employees = result.scalars().all()
            return [(e.id, e.name, list(e.embedding)) for e in employees]

    async def _set_output_path(self, demo_video_id: int, out_path: Path) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.output_video_path = str(out_path)
            await db.commit()

    async def _set_total_samples(self, demo_video_id: int, total_samples: Optional[int]) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.total_samples = total_samples
            await db.commit()

    async def _set_outcome_status(self, demo_video_id: int, outcome_status: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.outcome_status = outcome_status
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

    async def _save_idle_event(
        self,
        video_id: int,
        employee_id: Optional[int],
        start_ts: float,
        end_ts: float,
        duration: float,
    ) -> None:
        async with async_session_factory() as db:
            ev = IdleEvent(
                video_id=video_id,
                employee_id=employee_id,
                start_ts_seconds=start_ts,
                end_ts_seconds=end_ts,
                duration_seconds=duration,
            )
            db.add(ev)
            await db.commit()

    async def _update_progress(self, demo_video_id: int, processed_frames: int) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.processed_frames = processed_frames
            await db.commit()

    async def _mark_processing(self, demo_video_id: int) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                raise RuntimeError(f"IdleDemoVideo {demo_video_id} not found")
            video.status = "processing"
            video.started_at = datetime.datetime.utcnow()
            video.finished_at = None
            video.error_message = None
            await db.commit()

    async def _mark_failed(self, demo_video_id: int, error_message: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.status = "failed"
            video.error_message = error_message
            video.finished_at = datetime.datetime.utcnow()
            await db.commit()

    async def _finalize_video(self, demo_video_id: int, status: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.status = status
            video.finished_at = datetime.datetime.utcnow()
            await db.commit()
