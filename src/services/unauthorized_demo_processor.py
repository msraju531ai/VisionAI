from __future__ import annotations

import asyncio
import datetime
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import cv2
from loguru import logger
from sqlalchemy import select

from src.models.db_session import async_session_factory
from src.models.database import Employee, UnauthorizedDemoVideo, UnauthorizedEntryEvent
from src.services.employee_identifier import EmployeeIdentifier
from src.services.person_detector import PersonDetector


class UnauthorizedDemoProcessor:
    def __init__(
        self,
        identifier: Optional[EmployeeIdentifier] = None,
        person_detector: Optional[PersonDetector] = None,
        frame_sample_interval_seconds: float = 1.0,
        similarity_threshold: float = 0.6,
    ):
        self._identifier = identifier or EmployeeIdentifier()
        self._person_detector = person_detector or PersonDetector()
        self._frame_sample_interval_seconds = frame_sample_interval_seconds
        self._similarity_threshold = similarity_threshold

    def start_background(self, demo_video_id: int) -> None:
        asyncio.create_task(self.process_video(demo_video_id))

    async def process_video(self, demo_video_id: int) -> None:
        video_path = await self._load_video_path(demo_video_id)
        employees = await self._load_employees()
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
            logger.exception(f"Unauthorized demo processing failed for video_id={demo_video_id}: {e}")
            await self._mark_failed(demo_video_id, str(e))

    def _process_video_thread(
        self,
        loop: asyncio.AbstractEventLoop,
        demo_video_id: int,
        video_path: Path,
        employees: list[tuple[int, str, list[float]]],
    ) -> None:
        cap: Optional[cv2.VideoCapture] = None
        ffmpeg_proc: Optional[subprocess.Popen] = None
        writer: Optional[cv2.VideoWriter] = None

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
            fut = asyncio.run_coroutine_threadsafe(
                self._set_total_samples(demo_video_id, total_samples),
                loop,
            )
            fut.result(timeout=30)

            # Prefer ffmpeg pipe (guaranteed H.264) → fall back to OpenCV VideoWriter
            out_path, ffmpeg_proc, writer = self._open_writer(video_path, demo_video_id, fps, width, height)

            fut = asyncio.run_coroutine_threadsafe(self._set_output_path(demo_video_id, out_path), loop)
            fut.result(timeout=30)

            frame_index = 0
            processed = 0
            unauthorized_event_saved = False
            any_person_seen = False
            # Persist last known boxes so every frame (sampled or not) is annotated
            last_boxes: list[tuple[int, int, int, int, tuple, str]] = []

            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if frame_index % frame_step != 0:
                    # Draw last known detections on every non-sampled frame
                    for bx1, by1, bx2, by2, bcolor, blabel in last_boxes:
                        cv2.rectangle(frame, (bx1, by1), (bx2, by2), bcolor, 2)
                        cv2.putText(frame, blabel, (bx1, max(20, by1 - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, bcolor, 2, cv2.LINE_AA)
                    self._write_frame(ffmpeg_proc, writer, frame)
                    frame_index += 1
                    continue

                detections = self._person_detector.detect(frame, person_only=True)

                if detections:
                    any_person_seen = True

                current_boxes: list[tuple[int, int, int, int, tuple, str]] = []

                for d in detections:
                    x1, y1, x2, y2 = self._clip_bbox(frame, d)
                    if x2 <= x1 or y2 <= y1:
                        continue

                    person_crop = frame[y1:y2, x1:x2]
                    if person_crop.size == 0:
                        continue

                    ph, pw = person_crop.shape[:2]
                    face_crop = person_crop[0 : max(1, int(ph * 0.6)), :]

                    authorized = False
                    label = "Unauthorized"
                    color = (0, 0, 255)  # red
                    best_score: Optional[float] = None

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
                                authorized = True
                                best_score = score
                                label = f"{emp_name} ({score:.2f})"
                                color = (0, 200, 0)  # green

                    current_boxes.append((x1, y1, x2, y2, color, label))
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

                    if (not authorized) and (not unauthorized_event_saved):
                        timestamp_seconds = frame_index / fps if fps > 0 else 0.0
                        fut = asyncio.run_coroutine_threadsafe(
                            self._save_unauthorized_event(
                                video_id=demo_video_id,
                                timestamp_seconds=timestamp_seconds,
                                confidence=best_score,
                                frame_index=frame_index,
                            ),
                            loop,
                        )
                        fut.result(timeout=30)
                        unauthorized_event_saved = True

                last_boxes = current_boxes
                self._write_frame(ffmpeg_proc, writer, frame)

                processed += 1
                if processed % 25 == 0:
                    fut = asyncio.run_coroutine_threadsafe(self._update_progress(demo_video_id, processed), loop)
                    fut.result(timeout=30)

                frame_index += 1

            fut = asyncio.run_coroutine_threadsafe(self._update_progress(demo_video_id, processed), loop)
            fut.result(timeout=30)

            outcome = "authorized"
            if not any_person_seen:
                outcome = "idle"
            elif unauthorized_event_saved:
                outcome = "unauthorized"
            fut = asyncio.run_coroutine_threadsafe(self._set_outcome_status(demo_video_id, outcome), loop)
            fut.result(timeout=30)

            # Finalize ffmpeg pipe — must flush before marking completed
            if ffmpeg_proc is not None:
                ffmpeg_proc.stdin.close()
                rc = ffmpeg_proc.wait(timeout=120)
                ffmpeg_proc = None
                if rc != 0:
                    raise RuntimeError(f"ffmpeg encoding failed (exit code {rc})")

        finally:
            if cap is not None:
                cap.release()
            if ffmpeg_proc is not None:
                try:
                    ffmpeg_proc.stdin.close()
                except Exception:
                    pass
                try:
                    ffmpeg_proc.wait(timeout=30)
                except Exception:
                    ffmpeg_proc.terminate()
            if writer is not None:
                writer.release()

    @staticmethod
    def _open_writer(
        video_path: Path,
        demo_video_id: int,
        fps: float,
        width: int,
        height: int,
    ) -> tuple[Path, Optional[subprocess.Popen], Optional[cv2.VideoWriter]]:
        """Try ffmpeg pipe (H.264) first; fall back to OpenCV VideoWriter."""
        base = Path("data") / "demo" / "unauthorized" / "outputs"
        stem = video_path.stem
        h264_path = base / f"{stem}_unauth_{demo_video_id}.mp4"
        h264_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            try:
                proc = subprocess.Popen(
                    [
                        ffmpeg, "-y",
                        "-f", "rawvideo",
                        "-vcodec", "rawvideo",
                        "-pix_fmt", "bgr24",
                        "-s", f"{width}x{height}",
                        "-r", str(fps),
                        "-i", "pipe:0",
                        "-vcodec", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart",
                        "-an",
                        str(h264_path),
                    ],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                logger.info("Unauthorized demo: writing H.264 via ffmpeg pipe")
                return h264_path, proc, None
            except Exception as e:
                logger.warning(f"ffmpeg pipe failed to open: {e} — falling back to OpenCV")

        # OpenCV fallback (mp4v — may not play in all browsers)
        fallback_path = base / f"{stem}_unauth_{demo_video_id}_cv.mp4"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        for fourcc_str in ("avc1", "H264", "mp4v"):
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            w = cv2.VideoWriter(str(fallback_path), fourcc, fps, (width, height))
            if w.isOpened():
                logger.warning(
                    f"Unauthorized demo: ffmpeg not found, using OpenCV fourcc={fourcc_str}. "
                    "Install ffmpeg for guaranteed browser playback."
                )
                return fallback_path, None, w
        raise RuntimeError(f"Failed to open any video writer for: {fallback_path}")

    @staticmethod
    def _write_frame(
        ffmpeg_proc: Optional[subprocess.Popen],
        writer: Optional[cv2.VideoWriter],
        frame,
    ) -> None:
        if ffmpeg_proc is not None:
            ffmpeg_proc.stdin.write(frame.tobytes())
        elif writer is not None:
            writer.write(frame)

    @staticmethod
    def _clip_bbox(frame_bgr, d) -> tuple[int, int, int, int]:
        h, w = frame_bgr.shape[:2]
        x1 = max(0, min(w - 1, int(d.x1)))
        y1 = max(0, min(h - 1, int(d.y1)))
        x2 = max(0, min(w, int(d.x2)))
        y2 = max(0, min(h, int(d.y2)))
        return x1, y1, x2, y2



    async def _load_video_path(self, demo_video_id: int) -> Path:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                raise RuntimeError(f"UnauthorizedDemoVideo {demo_video_id} not found")
            return Path(video.video_path)

    async def _load_employees(self) -> list[tuple[int, str, list[float]]]:
        async with async_session_factory() as db:
            result = await db.execute(select(Employee))
            employees = result.scalars().all()
            return [(e.id, e.name, list(e.embedding)) for e in employees]

    async def _set_output_path(self, demo_video_id: int, out_path: Path) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.output_video_path = str(out_path)
            await db.commit()

    async def _set_total_samples(self, demo_video_id: int, total_samples: Optional[int]) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.total_samples = total_samples
            await db.commit()

    async def _set_outcome_status(self, demo_video_id: int, outcome_status: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.outcome_status = outcome_status
            await db.commit()

    async def _save_unauthorized_event(
        self,
        video_id: int,
        timestamp_seconds: float,
        confidence: Optional[float],
        frame_index: Optional[int],
    ) -> None:
        async with async_session_factory() as db:
            ev = UnauthorizedEntryEvent(
                video_id=video_id,
                timestamp_seconds=timestamp_seconds,
                confidence=confidence,
                frame_index=frame_index,
            )
            db.add(ev)
            await db.commit()

    async def _update_progress(self, demo_video_id: int, processed_frames: int) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.processed_frames = processed_frames
            await db.commit()

    async def _mark_processing(self, demo_video_id: int) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                raise RuntimeError(f"UnauthorizedDemoVideo {demo_video_id} not found")
            video.status = "processing"
            video.started_at = datetime.datetime.utcnow()
            video.finished_at = None
            video.error_message = None
            await db.commit()

    async def _mark_failed(self, demo_video_id: int, error_message: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.status = "failed"
            video.error_message = error_message
            video.finished_at = datetime.datetime.utcnow()
            await db.commit()

    async def _finalize_video(self, demo_video_id: int, status: str) -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == demo_video_id))
            video = result.scalar_one_or_none()
            if video is None:
                return
            video.status = status
            video.finished_at = datetime.datetime.utcnow()
            await db.commit()
