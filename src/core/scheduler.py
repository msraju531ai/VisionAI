"""
Shift schedule management.
Determines the current active shift and expected staffing levels.
"""

from __future__ import annotations

import datetime
from typing import Optional

from loguru import logger


class Shift:

    def __init__(
        self,
        shift_id: int,
        name: str,
        start_time: str,
        end_time: str,
        days_of_week: list[str],
        expected_min_workers: int = 1,
        expected_supervisor_walkthroughs: int = 2,
    ):
        self.shift_id = shift_id
        self.name = name
        self.start_time = self._parse_time(start_time)
        self.end_time = self._parse_time(end_time)
        self.days_of_week = [d.lower()[:3] for d in days_of_week]
        self.expected_min_workers = expected_min_workers
        self.expected_supervisor_walkthroughs = expected_supervisor_walkthroughs

    @staticmethod
    def _parse_time(t: str) -> datetime.time:
        parts = t.split(":")
        return datetime.time(int(parts[0]), int(parts[1]))

    def is_active_at(self, dt: datetime.datetime) -> bool:
        day_abbr = dt.strftime("%a").lower()[:3]
        if day_abbr not in self.days_of_week:
            return False
        current_time = dt.time()
        if self.start_time <= self.end_time:
            return self.start_time <= current_time <= self.end_time
        # Overnight shift (e.g. 22:00 - 06:00)
        return current_time >= self.start_time or current_time <= self.end_time


class ShiftScheduler:

    def __init__(self):
        self._shifts: list[Shift] = []

    def load_shifts(self, shifts: list[Shift]) -> None:
        self._shifts = shifts
        logger.info(f"Loaded {len(shifts)} shift schedules")

    def get_current_shift(self, dt: Optional[datetime.datetime] = None) -> Optional[Shift]:
        dt = dt or datetime.datetime.now()
        for shift in self._shifts:
            if shift.is_active_at(dt):
                return shift
        return None

    def is_night_shift(self, dt: Optional[datetime.datetime] = None) -> bool:
        shift = self.get_current_shift(dt)
        if not shift:
            return False
        return shift.start_time > shift.end_time  # overnight = night shift

    def expected_workers(self, dt: Optional[datetime.datetime] = None) -> int:
        shift = self.get_current_shift(dt)
        return shift.expected_min_workers if shift else 0

    def expected_walkthroughs(self, dt: Optional[datetime.datetime] = None) -> int:
        shift = self.get_current_shift(dt)
        return shift.expected_supervisor_walkthroughs if shift else 0
