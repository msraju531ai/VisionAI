"""
Main processing pipeline orchestrator.
For each camera: ingest frames → detect persons → track activity → detect anomalies → log & alert.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Optional

from loguru import logger

from src.models.db_session import async_session_factory
from src.services.video_ingestion import VideoIngestionService
from src.services.frame_processor import FrameProcessor
from src.services.person_detector import PersonDetector
from src.services.activity_analyzer import ActivityAnalyzer
from src.services.zone_manager import ZoneManager
from src.services.anomaly_detector import AnomalyDetector
from src.services.event_logger import EventLogger
from src.services.alert_service import AlertService
from src.core.scheduler import ShiftScheduler
from src.services.rtsp_employee_matcher import RTSPEmployeeMatcher


class PipelineManager:
    """Manages per-camera analysis tasks."""

    def __init__(
        self,
        ingestion: VideoIngestionService,
        frame_processor: FrameProcessor,
        person_detector: PersonDetector,
        activity_analyzer: ActivityAnalyzer,
        zone_manager: ZoneManager,
        anomaly_detector: AnomalyDetector,
        shift_scheduler: ShiftScheduler,
    ):
        self._ingestion = ingestion
        self._frame_proc = frame_processor
        self._detector = person_detector
        self._activity = activity_analyzer
        self._zones = zone_manager
        self._anomaly = anomaly_detector
        self._scheduler = shift_scheduler

        self._employee_matcher = RTSPEmployeeMatcher()

        self._tasks: dict[int, asyncio.Task] = {}
        self._stats: dict[int, dict] = {}

    @property
    def running_cameras(self) -> set[int]:
        return {cid for cid, t in self._tasks.items() if not t.done()}

    @property
    def camera_stats(self) -> dict[int, dict]:
        return self._stats

    async def start_camera(self, camera_id: int, rtsp_url: str, name: str = "") -> None:
        if camera_id in self._tasks and not self._tasks[camera_id].done():
            logger.warning(f"Pipeline already running for camera {camera_id}")
            return

        self._ingestion.add_camera(camera_id, rtsp_url, name)
        self._stats[camera_id] = {
            "frames_processed": 0,
            "detections": 0,
            "anomalies_found": 0,
            "started_at": datetime.datetime.utcnow(),
        }
        task = asyncio.create_task(self._run_camera_loop(camera_id))
        self._tasks[camera_id] = task
        logger.info(f"Pipeline started for camera {camera_id} ({name})")

    async def stop_camera(self, camera_id: int) -> None:
        task = self._tasks.pop(camera_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._ingestion.remove_camera(camera_id)
        self._activity.clear_camera(camera_id)
        logger.info(f"Pipeline stopped for camera {camera_id}")

    async def stop_all(self) -> None:
        cam_ids = list(self._tasks.keys())
        for cid in cam_ids:
            await self.stop_camera(cid)

    async def _run_camera_loop(self, camera_id: int) -> None:
        stats = self._stats[camera_id]
        try:
            async for cam_id, frame, timestamp in self._ingestion.sample_frames(camera_id):
                processed = self._frame_proc.preprocess(frame)
                frame_h, frame_w = frame.shape[:2]

                detections = self._detector.detect(processed)
                stats["frames_processed"] += 1
                stats["detections"] += len(detections)

                if detections:
                    asyncio.create_task(
                        self._employee_matcher.process_detections(
                            camera_id=camera_id,
                            frame_bgr=frame,
                            detections=detections,
                            timestamp_unix=timestamp,
                        )
                    )

                tracked = self._activity.update(camera_id, detections, timestamp)

                frame_path: Optional[str] = None
                if detections:
                    frame_path = self._frame_proc.save_frame(frame, camera_id, timestamp)

                anomalies = self._anomaly.analyze(
                    camera_id, detections, tracked, frame_w, frame_h, timestamp, frame_path,
                )

                if anomalies:
                    stats["anomalies_found"] += len(anomalies)
                    await self._persist_anomalies(anomalies)

        except asyncio.CancelledError:
            logger.info(f"Camera {camera_id} pipeline cancelled")
        except Exception as e:
            logger.error(f"Camera {camera_id} pipeline error: {e}")

    async def _persist_anomalies(self, anomalies) -> None:
        async with async_session_factory() as db:
            event_logger = EventLogger(db)
            alert_service = AlertService(db)
            for anomaly in anomalies:
                event = await event_logger.log_event(anomaly)
                await alert_service.dispatch(event.id, anomaly)
            await db.commit()


_pipeline_manager: Optional[PipelineManager] = None


def init_pipeline_manager(
    ingestion: VideoIngestionService,
    frame_processor: FrameProcessor,
    person_detector: PersonDetector,
    activity_analyzer: ActivityAnalyzer,
    zone_manager: ZoneManager,
    anomaly_detector: AnomalyDetector,
    shift_scheduler: ShiftScheduler,
) -> PipelineManager:
    global _pipeline_manager
    _pipeline_manager = PipelineManager(
        ingestion, frame_processor, person_detector,
        activity_analyzer, zone_manager, anomaly_detector, shift_scheduler,
    )
    return _pipeline_manager


def get_pipeline_manager() -> PipelineManager:
    if _pipeline_manager is None:
        raise RuntimeError("PipelineManager not initialised — call init_pipeline_manager() first")
    return _pipeline_manager
