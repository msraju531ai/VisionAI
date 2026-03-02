import time
from src.services.activity_analyzer import ActivityAnalyzer
from src.services.person_detector import Detection


def _det(cx: float, cy: float) -> Detection:
    return Detection(cx - 15, cy - 30, cx + 15, cy + 30, 0.95, 0, "person")


def test_new_detections_create_tracks():
    aa = ActivityAnalyzer()
    dets = [_det(100, 200), _det(400, 300)]
    tracks = aa.update(1, dets, time.time())
    assert len(tracks) == 2
    assert aa.get_person_count(1) == 2


def test_idle_detection():
    aa = ActivityAnalyzer()
    t = time.time()
    d = _det(100, 200)
    aa.update(1, [d], t)

    # Simulate stationary person over many frames
    for i in range(1, 70):
        aa.update(1, [d], t + i * 5)

    idle = aa.get_idle_persons(1)
    assert len(idle) >= 1
    assert idle[0].is_idle


def test_moving_person_not_idle():
    aa = ActivityAnalyzer()
    t = time.time()
    for i in range(20):
        aa.update(1, [_det(100 + i * 50, 200)], t + i * 2)

    idle = aa.get_idle_persons(1)
    assert len(idle) == 0
