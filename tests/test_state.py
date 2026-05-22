# tests/test_state.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from core.state import (
    LifeStateManager, LifeStateSnapshot,
    ActivityType, SleepState, ScheduleItem, RecentEvent
)


@pytest.fixture
def config():
    c = MagicMock()
    c.plugin.max_recent_events = 20
    c.sleep.sleepy_duration_minutes = 30
    c.sleep.waking_duration_minutes = 15
    return c


@pytest.fixture
def manager(config):
    return LifeStateManager(config)


def test_snapshot_is_frozen(manager):
    snap = manager.snapshot()
    assert isinstance(snap, LifeStateSnapshot)
    with pytest.raises((AttributeError, TypeError)):
        snap.sleep_state = SleepState.SLEEPING


def test_snapshot_schedule_is_tuple(manager):
    assert isinstance(manager.snapshot().today_schedule, tuple)


def test_snapshot_events_is_tuple(manager):
    assert isinstance(manager.snapshot().recent_events, tuple)


@pytest.mark.asyncio
async def test_transition_returns_true(manager):
    ok = await manager.transition_activity(ActivityType.EATING, "t1")
    assert ok is True
    assert manager.snapshot().current_activity == ActivityType.EATING


@pytest.mark.asyncio
async def test_transition_idempotent(manager):
    await manager.transition_activity(ActivityType.EATING, "t1")
    ok = await manager.transition_activity(ActivityType.SLEEPING, "t1")
    assert ok is False
    assert manager.snapshot().current_activity == ActivityType.EATING


@pytest.mark.asyncio
async def test_transition_stores_prev(manager):
    await manager.transition_activity(ActivityType.EATING, "t1")
    await manager.transition_activity(ActivityType.LEISURE, "t2")
    snap = manager.snapshot()
    assert snap.prev_activity == ActivityType.EATING
    assert snap.current_activity == ActivityType.LEISURE


@pytest.mark.asyncio
async def test_set_schedule(manager):
    from datetime import date
    from utils.time_helper import local_time_to_utc_datetime
    d = date.today()
    start = local_time_to_utc_datetime(d, "08:00", "Asia/Shanghai")
    end = local_time_to_utc_datetime(d, "09:00", "Asia/Shanghai")
    item = ScheduleItem(start_time=start, end_time=end,
                        activity=ActivityType.EATING, description="breakfast")
    await manager.set_schedule([item])
    assert len(manager.snapshot().today_schedule) == 1


@pytest.mark.asyncio
async def test_append_event_prunes_expired(manager):
    old = RecentEvent("t", "old", datetime(2020, 1, 1, tzinfo=timezone.utc), ttl_seconds=1)
    new = RecentEvent("t", "new", datetime.now(tz=timezone.utc), ttl_seconds=3600)
    await manager.append_event(old)
    await manager.append_event(new)
    descs = [e.description for e in manager.snapshot().recent_events]
    assert "old" not in descs and "new" in descs
