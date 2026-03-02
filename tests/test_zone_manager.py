from src.services.zone_manager import ZoneManager, ZoneDefinition
from src.services.person_detector import Detection


def _make_detection(cx: float, cy: float) -> Detection:
    return Detection(cx - 10, cy - 10, cx + 10, cy + 10, 0.9, 0, "person")


def test_contains_point():
    zone = ZoneDefinition(1, "Test Zone", "restricted", [
        [0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5],
    ])
    assert zone.contains_point(0.3, 0.3) is True
    assert zone.contains_point(0.0, 0.0) is False
    assert zone.contains_point(0.8, 0.8) is False


def test_restricted_zone_violation():
    zm = ZoneManager()
    zm.set_zones(1, [
        ZoneDefinition(10, "Restricted", "restricted", [
            [0.0, 0.0], [0.3, 0.0], [0.3, 0.3], [0.0, 0.3],
        ]),
    ])
    d_inside = _make_detection(100, 100)  # centre at (100,100) on a 1000x1000 frame → 0.1,0.1
    d_outside = _make_detection(800, 800)

    violations = zm.check_restricted_zones(1, [d_inside, d_outside], 1000, 1000)
    assert len(violations) == 1
    assert violations[0][1].name == "Restricted"


def test_no_zones_returns_empty():
    zm = ZoneManager()
    violations = zm.check_restricted_zones(99, [_make_detection(100, 100)], 640, 640)
    assert violations == []
