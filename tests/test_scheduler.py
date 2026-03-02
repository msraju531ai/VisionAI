import datetime
from src.core.scheduler import Shift, ShiftScheduler


def test_shift_active_during_hours():
    shift = Shift(1, "Day Shift", "08:00", "16:00", ["mon", "tue", "wed", "thu", "fri"])
    dt = datetime.datetime(2026, 2, 18, 10, 0)  # Wednesday 10:00
    assert shift.is_active_at(dt) is True


def test_shift_inactive_outside_hours():
    shift = Shift(1, "Day Shift", "08:00", "16:00", ["mon", "tue", "wed", "thu", "fri"])
    dt = datetime.datetime(2026, 2, 18, 20, 0)  # Wednesday 20:00
    assert shift.is_active_at(dt) is False


def test_night_shift_overnight():
    shift = Shift(2, "Night Shift", "22:00", "06:00", ["mon", "tue", "wed", "thu", "fri"])
    late_night = datetime.datetime(2026, 2, 18, 23, 30)
    early_morning = datetime.datetime(2026, 2, 19, 3, 0)
    mid_day = datetime.datetime(2026, 2, 18, 12, 0)

    assert shift.is_active_at(late_night) is True
    assert shift.is_active_at(early_morning) is True
    assert shift.is_active_at(mid_day) is False


def test_scheduler_returns_current_shift():
    scheduler = ShiftScheduler()
    scheduler.load_shifts([
        Shift(1, "Day", "08:00", "16:00", ["mon", "tue", "wed", "thu", "fri"]),
        Shift(2, "Night", "22:00", "06:00", ["mon", "tue", "wed", "thu", "fri"]),
    ])
    dt = datetime.datetime(2026, 2, 18, 23, 0)  # Wednesday 23:00
    shift = scheduler.get_current_shift(dt)
    assert shift is not None
    assert shift.name == "Night"
    assert scheduler.is_night_shift(dt) is True


def test_no_shift_on_weekend():
    scheduler = ShiftScheduler()
    scheduler.load_shifts([
        Shift(1, "Day", "08:00", "16:00", ["mon", "tue", "wed", "thu", "fri"]),
    ])
    saturday = datetime.datetime(2026, 2, 21, 10, 0)
    assert scheduler.get_current_shift(saturday) is None
