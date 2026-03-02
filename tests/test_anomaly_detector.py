import time
import datetime
from unittest.mock import MagicMock

from src.services.anomaly_detector import AnomalyDetector
from src.services.activity_analyzer import ActivityAnalyzer, TrackedPerson
from src.services.zone_manager import ZoneManager, ZoneDefinition
from src.services.person_detector import Detection
from src.core.scheduler import ShiftScheduler, Shift


def _setup():
    aa = ActivityAnalyzer()
    zm = ZoneManager()
    ss = ShiftScheduler()
    ss.load_shifts([
        Shift(1, "Day", "08:00", "16:00", ["mon", "tue", "wed", "thu", "fri"],
              expected_min_workers=2),
    ])
    ad = AnomalyDetector(aa, zm, ss)
    return ad, zm


def test_restricted_zone_produces_event():
    ad, zm = _setup()
    zm.set_zones(1, [
        ZoneDefinition(10, "Server Room", "restricted", [
            [0.0, 0.0], [0.3, 0.0], [0.3, 0.3], [0.0, 0.3],
        ]),
    ])
    det = Detection(50, 50, 150, 200, 0.9, 0, "person")
    ts = datetime.datetime(2026, 2, 18, 10, 0).timestamp()

    events = ad.analyze(1, [det], [], 1000, 1000, ts)
    restricted_events = [e for e in events if e.event_type == "unauthorized_presence"]
    assert len(restricted_events) >= 1


def test_understaffing_produces_event():
    ad, zm = _setup()
    det = Detection(500, 500, 550, 600, 0.9, 0, "person")
    ts = datetime.datetime(2026, 2, 18, 10, 0).timestamp()

    events = ad.analyze(1, [det], [], 1000, 1000, ts)
    absence_events = [e for e in events if e.event_type == "unauthorized_absence"]
    assert len(absence_events) >= 1  # 1 person but 2 expected


def test_no_event_outside_shift():
    ad, zm = _setup()
    ts = datetime.datetime(2026, 2, 18, 20, 0).timestamp()  # 8pm, no shift
    events = ad.analyze(1, [], [], 1000, 1000, ts)
    absence_events = [e for e in events if e.event_type == "unauthorized_absence"]
    assert len(absence_events) == 0
