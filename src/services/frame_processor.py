"""
Pre-processes raw frames: resize, normalize, and optionally persist to disk.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from config.settings import settings


class FrameProcessor:

    def __init__(
        self,
        target_width: int = 640,
        target_height: int = 640,
        storage_path: Optional[str] = None,
    ):
        self._target_w = target_width
        self._target_h = target_height
        self._storage = Path(storage_path or settings.frame_storage_path)
        self._storage.mkdir(parents=True, exist_ok=True)

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        resized = cv2.resize(frame, (self._target_w, self._target_h), interpolation=cv2.INTER_LINEAR)
        return resized

    def save_frame(self, frame: np.ndarray, camera_id: int, timestamp: float) -> str:
        dt = datetime.datetime.fromtimestamp(timestamp)
        day_dir = self._storage / str(camera_id) / dt.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        filename = dt.strftime("%H-%M-%S") + f"_{int(timestamp * 1000) % 1000:03d}.jpg"
        filepath = day_dir / filename
        cv2.imwrite(str(filepath), frame)
        return str(filepath)

    def draw_detections(
        self,
        frame: np.ndarray,
        boxes: list[dict],
        color: tuple[int, int, int] = (0, 255, 0),
    ) -> np.ndarray:
        """Draw bounding boxes on a frame copy. Each box: {x1, y1, x2, y2, label, confidence}."""
        annotated = frame.copy()
        for b in boxes:
            x1, y1, x2, y2 = int(b["x1"]), int(b["y1"]), int(b["x2"]), int(b["y2"])
            label = f"{b.get('label', '')} {b.get('confidence', 0):.0%}"
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(annotated, label, (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        return annotated

    def draw_zones(
        self,
        frame: np.ndarray,
        zones: list[dict],
    ) -> np.ndarray:
        """Overlay zone polygons. Each zone: {name, polygon_points, zone_type}."""
        overlay = frame.copy()
        h, w = frame.shape[:2]
        zone_colors = {
            "restricted": (0, 0, 255),
            "work_area": (0, 200, 0),
            "walkway": (200, 200, 0),
            "equipment": (200, 100, 0),
            "entry_exit": (200, 0, 200),
        }
        for z in zones:
            pts = np.array(
                [[int(p[0] * w), int(p[1] * h)] for p in z["polygon_points"]],
                dtype=np.int32,
            )
            clr = zone_colors.get(z.get("zone_type", ""), (128, 128, 128))
            cv2.fillPoly(overlay, [pts], (*clr, 40))
            cv2.polylines(overlay, [pts], True, clr, 2)
            centroid = pts.mean(axis=0).astype(int)
            cv2.putText(overlay, z["name"], tuple(centroid), cv2.FONT_HERSHEY_SIMPLEX, 0.5, clr, 1)
        return cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)
