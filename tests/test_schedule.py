# tests/test_schedule.py
import pytest
from datetime import datetime, timezone, timedelta, date
from unittest.mock import MagicMock
from core.state import ActivityType, ScheduleItem, LifeStateSnapshot, SleepState
from utils.time_helper import local_time_to_utc_datetime
from systems.schedule import (
    calc_next_transition, get_current_activity,
    get_missed_transitions, build_skeleton, build_fallback_schedule
)


def make_item(start_h: int, end_h: int, activity: ActivityType,
              desc: str = "", d: date = None) -> ScheduleItem:
    d = d or date.today()
    start = local_time_to_utc_datetime(d, f"{start_h:02d}:00", "Asia/Shanghai")
    end = local_time_to_utc_datetime(d, f"{end_h:02d}:00", "Asia/Shanghai")
    return ScheduleItem(start_time=start, end_time=end, activity=activity, description=desc)


def make_snap(items: list, last_processed: datetime = None) -> LifeStateSnapshot:
    now = datetime.now(tz=timezone.utc)
    return LifeStateSnapshot(
        sleep_state=SleepState.AWAKE,
        current_activity=ActivityType.OTHER,
        prev_activity=ActivityType.OTHER,
        activity_since=now,
        last_transition_processed_at=last_processed or now,
        schedule_generated_date=date.today().isoformat(),
        schedule_is_repair=False,
        today_schedule=tuple(items),
        recent_events=tuple(),
    )


def test_get_current_activity_finds_item():
    item = make_item(8, 9, ActivityType.EATING, "breakfast")
    snap = make_snap([item])
    t = local_time_to_utc_datetime(date.today(), "08:30", "Asia/Shanghai")
    assert get_current_activity(snap, t) == ActivityType.EATING


def test_get_current_activity_returns_other_when_no_match():
    item = make_item(8, 9, ActivityType.EATING)
    snap = make_snap([item])
    t = local_time_to_utc_datetime(date.today(), "10:00", "Asia/Shanghai")
    assert get_current_activity(snap, t) == ActivityType.OTHER


def test_calc_next_transition_returns_future():
    item = make_item(8, 9, ActivityType.EATING)
    snap = make_snap([item])
    t = local_time_to_utc_datetime(date.today(), "08:30", "Asia/Shanghai")
    next_time, next_act = calc_next_transition(snap, t)
    assert next_time > t


def test_get_missed_transitions_empty_when_no_gap():
    item = make_item(8, 9, ActivityType.EATING)
    now = local_time_to_utc_datetime(date.today(), "08:30", "Asia/Shanghai")
    last = now - timedelta(minutes=1)
    snap = make_snap([item], last_processed=last)
    missed = get_missed_transitions(snap, now)
    assert len(missed) == 0


def test_get_missed_transitions_finds_skipped():
    item1 = make_item(8, 9, ActivityType.EATING)
    item2 = make_item(9, 10, ActivityType.STUDYING)
    last = local_time_to_utc_datetime(date.today(), "07:50", "Asia/Shanghai")
    now = local_time_to_utc_datetime(date.today(), "09:10", "Asia/Shanghai")
    snap = make_snap([item1, item2], last_processed=last)
    missed = get_missed_transitions(snap, now)
    assert len(missed) >= 1


def test_build_skeleton_returns_items():
    cfg = MagicMock()
    cfg.sleep_start = "23:00"
    cfg.sleep_end = "07:00"
    cfg.breakfast_start = "07:30"
    cfg.breakfast_end = "08:00"
    cfg.lunch_start = "12:00"
    cfg.lunch_end = "12:30"
    cfg.dinner_start = "18:00"
    cfg.dinner_end = "18:30"
    items = build_skeleton(date.today(), cfg, "Asia/Shanghai")
    activities = [i.activity for i in items]
    assert ActivityType.SLEEPING in activities
    assert ActivityType.EATING in activities
    assert all(i.is_skeleton for i in items)


def test_build_fallback_schedule_has_non_skeleton():
    cfg = MagicMock()
    cfg.sleep_start = "23:00"
    cfg.sleep_end = "07:00"
    cfg.breakfast_start = "07:30"
    cfg.breakfast_end = "08:00"
    cfg.lunch_start = "12:00"
    cfg.lunch_end = "12:30"
    cfg.dinner_start = "18:00"
    cfg.dinner_end = "18:30"
    items = build_fallback_schedule(date.today(), cfg, "Asia/Shanghai")
    non_skeleton = [i for i in items if not i.is_skeleton]
    assert len(non_skeleton) > 0
