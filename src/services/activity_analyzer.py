"""
Analyses worker activity across consecutive frames to detect:
- Idle time at equipment / work areas
- Presence vs. absence in zones
- Movement patterns
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from loguru import logger

from config.settings import settings
from src.services.person_detector import Detection


class TrackedPerson:
    """Tracks a single person across frames using simple centroid proximity."""

    def __init__(self, person_id: int, detection: Detection, timestamp: float):
        self.person_id = person_id
        self.last_detection = detection
        self.last_seen = timestamp
        self.first_seen = timestamp
        self.positions: list[tuple[float, float, float]] = [(*detection.center, timestamp)]
        self._idle_start: Optional[float] = timestamp
        self.movement_threshold = 30.0  # pixels

    def update(self, detection: Detection, timestamp: float) -> None:
        dx = abs(detection.center[0] - self.last_detection.center[0])
        dy = abs(detection.center[1] - self.last_detection.center[1])
        moved = (dx**2 + dy**2) ** 0.5 > self.movement_threshold

        if moved:
            self._idle_start = timestamp
        self.last_detection = detection
        self.last_seen = timestamp
        self.positions.append((*detection.center, timestamp))

    @property
    def idle_seconds(self) -> float:
        if self._idle_start is None:
            return 0.0
        return self.last_seen - self._idle_start

    @property
    def is_idle(self) -> bool:
        return self.idle_seconds >= settings.idle_threshold_seconds

    @property
    def duration_seconds(self) -> float:
        return self.last_seen - self.first_seen


class ActivityAnalyzer:
    """
    Maintains a set of tracked persons per camera and produces activity metrics.
    Uses a simple nearest-centroid tracker (sufficient for fixed cameras).
    """

    def __init__(self):
        self._tracks: dict[int, dict[int, TrackedPerson]] = defaultdict(dict)
        self._next_id: int = 1
        self._max_age: float = 10.0  # seconds before a track is considered lost
        self._match_distance: float = 80.0  # max pixel distance for matching

    def update(
        self, camera_id: int, detections: list[Detection], timestamp: float
    ) -> list[TrackedPerson]:
        tracks = self._tracks[camera_id]

        unmatched_dets = list(range(len(detections)))
        matched_track_ids: set[int] = set()

        # Greedy nearest-centroid matching
        for tid, track in list(tracks.items()):
            best_idx, best_dist = -1, self._match_distance
            for i in unmatched_dets:
                d = detections[i]
                dx = d.center[0] - track.last_detection.center[0]
                dy = d.center[1] - track.last_detection.center[1]
                dist = (dx**2 + dy**2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            if best_idx >= 0:
                track.update(detections[best_idx], timestamp)
                unmatched_dets.remove(best_idx)
                matched_track_ids.add(tid)

        # Remove stale tracks
        stale = [tid for tid, t in tracks.items() if (timestamp - t.last_seen) > self._max_age]
        for tid in stale:
            del tracks[tid]

        # Create new tracks for unmatched detections
        for i in unmatched_dets:
            pid = self._next_id
            self._next_id += 1
            tracks[pid] = TrackedPerson(pid, detections[i], timestamp)

        return list(tracks.values())

    def get_idle_persons(self, camera_id: int) -> list[TrackedPerson]:
        return [t for t in self._tracks.get(camera_id, {}).values() if t.is_idle]

    def get_person_count(self, camera_id: int) -> int:
        return len(self._tracks.get(camera_id, {}))

    def clear_camera(self, camera_id: int) -> None:
        self._tracks.pop(camera_id, None)
