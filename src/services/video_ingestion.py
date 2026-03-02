"""
Connects to RTSP camera streams and yields frames at a configurable sample rate.
Supports concurrent streams with graceful reconnection.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import cv2
import numpy as np
from loguru import logger

from config.settings import settings


class CameraStream:
    """Wraps an OpenCV VideoCapture with auto-reconnect."""

    def __init__(self, camera_id: int, rtsp_url: str, name: str = ""):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.name = name or f"camera-{camera_id}"
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False

    def _open(self) -> bool:
        if self._cap is not None:
            self._cap.release()
        self._cap = cv2.VideoCapture(self.rtsp_url)
        if not self._cap.isOpened():
            logger.error(f"[{self.name}] Failed to open stream: {self.rtsp_url}")
            return False
        logger.info(f"[{self.name}] Stream opened: {self.rtsp_url}")
        return True

    def read_frame(self) -> Optional[np.ndarray]:
        if self._cap is None or not self._cap.isOpened():
            if not self._open():
                return None
        ret, frame = self._cap.read()
        if not ret:
            logger.warning(f"[{self.name}] Frame read failed, will reconnect")
            self._cap.release()
            self._cap = None
            return None
        return frame

    def release(self) -> None:
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info(f"[{self.name}] Stream released")


class VideoIngestionService:
    """Manages multiple camera streams and yields sampled frames."""

    def __init__(self):
        self._streams: dict[int, CameraStream] = {}
        self._sample_interval: int = settings.frame_sample_interval

    def add_camera(self, camera_id: int, rtsp_url: str, name: str = "") -> None:
        if camera_id in self._streams:
            self._streams[camera_id].release()
        self._streams[camera_id] = CameraStream(camera_id, rtsp_url, name)
        logger.info(f"Camera {camera_id} registered for ingestion")

    def remove_camera(self, camera_id: int) -> None:
        stream = self._streams.pop(camera_id, None)
        if stream:
            stream.release()

    async def sample_frames(self, camera_id: int) -> AsyncGenerator[tuple[int, np.ndarray, float], None]:
        """
        Yields (camera_id, frame, timestamp) at the configured sample interval.
        Runs in a thread to avoid blocking the event loop.
        """
        stream = self._streams.get(camera_id)
        if not stream:
            logger.error(f"Camera {camera_id} not registered")
            return

        stream._running = True
        loop = asyncio.get_event_loop()

        while stream._running:
            frame = await loop.run_in_executor(None, stream.read_frame)
            if frame is not None:
                yield camera_id, frame, time.time()
            await asyncio.sleep(self._sample_interval)

    def stop_all(self) -> None:
        for stream in self._streams.values():
            stream.release()
        self._streams.clear()

    @property
    def active_camera_ids(self) -> list[int]:
        return list(self._streams.keys())
