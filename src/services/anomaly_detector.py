"""
Anomaly detection orchestrator.
Evaluates frame analysis results against rules and shift expectations to produce events.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from config.settings import settings
from src.services.person_detector import Detection
from src.services.activity_analyzer import ActivityAnalyzer, TrackedPerson
from src.services.zone_manager import ZoneManager, ZoneDefinition
from src.core.scheduler import ShiftScheduler


@dataclass
class AnomalyEvent:
    event_type: str
    severity: str
    description: str
    camera_id: int
    zone_id: Optional[int] = None
    frame_path: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.utcnow)


class AnomalyDetector:

    def __init__(
        self,
        activity_analyzer: ActivityAnalyzer,
        zone_manager: ZoneManager,
        shift_scheduler: ShiftScheduler,
    ):
        self._activity = activity_analyzer
        self._zones = zone_manager
        self._shifts = shift_scheduler
        self._cooldowns: dict[str, float] = {}

    def _is_cooled_down(self, key: str, timestamp: float) -> bool:
        last = self._cooldowns.get(key, 0.0)
        if timestamp - last < settings.alert_cooldown_seconds:
            return False
        self._cooldowns[key] = timestamp
        return True

    def analyze(
        self,
        camera_id: int,
        detections: list[Detection],
        tracked: list[TrackedPerson],
        frame_w: int,
        frame_h: int,
        timestamp: float,
        frame_path: Optional[str] = None,
    ) -> list[AnomalyEvent]:
        events: list[AnomalyEvent] = []
        dt = datetime.datetime.fromtimestamp(timestamp)

        events.extend(self._check_restricted_zones(camera_id, detections, frame_w, frame_h, timestamp, frame_path))
        events.extend(self._check_idle_workers(camera_id, tracked, timestamp, frame_path))
        events.extend(self._check_staffing_levels(camera_id, detections, dt, timestamp, frame_path))

        return events

    def _check_restricted_zones(
        self, camera_id: int, detections: list[Detection],
        frame_w: int, frame_h: int, timestamp: float, frame_path: Optional[str],
    ) -> list[AnomalyEvent]:
        if not settings.unauthorized_zone_alert:
            return []

        violations = self._zones.check_restricted_zones(camera_id, detections, frame_w, frame_h)
        events = []
        for det, zone in violations:
            key = f"restricted_{camera_id}_{zone.zone_id}"
            if not self._is_cooled_down(key, timestamp):
                continue
            events.append(AnomalyEvent(
                event_type="unauthorized_presence",
                severity="high",
                description=f"Person detected in restricted zone '{zone.name}'",
                camera_id=camera_id,
                zone_id=zone.zone_id,
                frame_path=frame_path,
                metadata={"detection": det.to_dict(), "zone": zone.name},
            ))
        return events

    def _check_idle_workers(
        self, camera_id: int, tracked: list[TrackedPerson],
        timestamp: float, frame_path: Optional[str],
    ) -> list[AnomalyEvent]:
        events = []
        for person in tracked:
            if not person.is_idle:
                continue
            key = f"idle_{camera_id}_{person.person_id}"
            if not self._is_cooled_down(key, timestamp):
                continue
            events.append(AnomalyEvent(
                event_type="idle_time",
                severity="medium",
                description=f"Worker idle for {person.idle_seconds:.0f}s at camera {camera_id}",
                camera_id=camera_id,
                frame_path=frame_path,
                metadata={
                    "idle_seconds": person.idle_seconds,
                    "person_id": person.person_id,
                    "position": list(person.last_detection.center),
                },
            ))
        return events

    def _check_staffing_levels(
        self, camera_id: int, detections: list[Detection],
        dt: datetime.datetime, timestamp: float, frame_path: Optional[str],
    ) -> list[AnomalyEvent]:
        expected = self._shifts.expected_workers(dt)
        if expected <= 0:
            return []

        actual = len(detections)
        events = []

        if actual < expected:
            key = f"understaffed_{camera_id}"
            if self._is_cooled_down(key, timestamp):
                events.append(AnomalyEvent(
                    event_type="unauthorized_absence",
                    severity="high" if actual == 0 else "medium",
                    description=f"Staffing below minimum: {actual}/{expected} workers detected",
                    camera_id=camera_id,
                    frame_path=frame_path,
                    metadata={"expected": expected, "actual": actual},
                ))

        return events
