"""
Manages detection zones per camera.
Determines whether a detected person is inside a defined zone polygon.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from loguru import logger

from src.services.person_detector import Detection


class ZoneDefinition:

    def __init__(self, zone_id: int, name: str, zone_type: str, polygon_points: list[list[float]]):
        self.zone_id = zone_id
        self.name = name
        self.zone_type = zone_type
        self.polygon_points = polygon_points

    def contains_point(self, x_norm: float, y_norm: float) -> bool:
        """Ray-casting algorithm for point-in-polygon (normalised coords 0-1)."""
        pts = self.polygon_points
        n = len(pts)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if ((yi > y_norm) != (yj > y_norm)) and (x_norm < (xj - xi) * (y_norm - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "zone_type": self.zone_type,
            "polygon_points": self.polygon_points,
        }


class ZoneManager:
    """Maps detections to zones for a given camera."""

    def __init__(self):
        self._zones: dict[int, list[ZoneDefinition]] = {}

    def set_zones(self, camera_id: int, zones: list[ZoneDefinition]) -> None:
        self._zones[camera_id] = zones
        logger.info(f"Camera {camera_id}: loaded {len(zones)} zones")

    def get_zones(self, camera_id: int) -> list[ZoneDefinition]:
        return self._zones.get(camera_id, [])

    def find_zone_for_detection(
        self,
        camera_id: int,
        detection: Detection,
        frame_w: int,
        frame_h: int,
    ) -> Optional[ZoneDefinition]:
        cx, cy = detection.center
        x_norm, y_norm = cx / frame_w, cy / frame_h
        for zone in self._zones.get(camera_id, []):
            if zone.contains_point(x_norm, y_norm):
                return zone
        return None

    def persons_in_zone(
        self,
        camera_id: int,
        zone_id: int,
        detections: list[Detection],
        frame_w: int,
        frame_h: int,
    ) -> list[Detection]:
        zone = next((z for z in self._zones.get(camera_id, []) if z.zone_id == zone_id), None)
        if not zone:
            return []
        result = []
        for d in detections:
            cx, cy = d.center
            if zone.contains_point(cx / frame_w, cy / frame_h):
                result.append(d)
        return result

    def check_restricted_zones(
        self,
        camera_id: int,
        detections: list[Detection],
        frame_w: int,
        frame_h: int,
    ) -> list[tuple[Detection, ZoneDefinition]]:
        """Returns detections found inside restricted zones."""
        violations = []
        restricted = [z for z in self._zones.get(camera_id, []) if z.zone_type == "restricted"]
        for d in detections:
            cx, cy = d.center
            for zone in restricted:
                if zone.contains_point(cx / frame_w, cy / frame_h):
                    violations.append((d, zone))
        return violations
