# tests/test_sleep.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from core.state import ActivityType, SleepState
from systems.sleep import derive_sleep_state


@pytest.fixture
def cfg():
    c = MagicMock()
    c.sleepy_duration_minutes = 30
    c.waking_duration_minutes = 15
    return c


def test_eating_returns_awake(cfg):
    now = datetime.now(tz=timezone.utc)
    assert derive_sleep_state(ActivityType.EATING, now, ActivityType.LEISURE, now, cfg) == SleepState.AWAKE


def test_after_sleep_within_waking(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=5)
    result = derive_sleep_state(ActivityType.OTHER, since, ActivityType.SLEEPING, now, cfg)
    assert result == SleepState.WAKING


def test_after_sleep_past_waking(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=20)
    result = derive_sleep_state(ActivityType.OTHER, since, ActivityType.SLEEPING, now, cfg)
    assert result == SleepState.AWAKE


def test_sleeping_short_returns_sleepy(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=10)
    result = derive_sleep_state(ActivityType.SLEEPING, since, ActivityType.LEISURE, now, cfg)
    assert result == SleepState.SLEEPY


def test_sleeping_long_returns_sleeping(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=45)
    result = derive_sleep_state(ActivityType.SLEEPING, since, ActivityType.LEISURE, now, cfg)
    assert result == SleepState.SLEEPING
