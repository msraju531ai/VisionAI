"""
YOLOv8-based person detection service.
Detects people and returns bounding boxes with confidence scores.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from loguru import logger

from config.settings import settings

_PERSON_CLASS_ID = 0  # COCO class 0 = person


class Detection:
    __slots__ = ("x1", "y1", "x2", "y2", "confidence", "class_id", "label")

    def __init__(self, x1: float, y1: float, x2: float, y2: float, confidence: float, class_id: int, label: str):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.confidence = confidence
        self.class_id = class_id
        self.label = label

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return (self.x2 - self.x1) * (self.y2 - self.y1)

    def to_dict(self) -> dict:
        return {
            "x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2,
            "confidence": self.confidence, "label": self.label,
        }


class PersonDetector:

    def __init__(self, model_path: Optional[str] = None, confidence: Optional[float] = None):
        self._model_path = model_path or settings.yolo_model_path
        self._confidence = confidence or settings.yolo_confidence_threshold
        self._device = settings.device
        self._model = None

    def _load_model(self):
        from ultralytics import YOLO
        logger.info(f"Loading YOLO model: {self._model_path} on {self._device}")
        self._model = YOLO(self._model_path)
        if self._device != "cpu":
            self._model.to(self._device)
        logger.info("YOLO model loaded successfully")

    @property
    def model(self):
        if self._model is None:
            self._load_model()
        return self._model

    def detect(self, frame: np.ndarray, person_only: bool = True) -> list[Detection]:
        results = self.model(frame, conf=self._confidence, verbose=False)
        detections: list[Detection] = []

        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                if person_only and cls_id != _PERSON_CLASS_ID:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                label = r.names[cls_id]
                detections.append(Detection(x1, y1, x2, y2, conf, cls_id, label))

        return detections

    def count_persons(self, frame: np.ndarray) -> int:
        return len(self.detect(frame, person_only=True))
