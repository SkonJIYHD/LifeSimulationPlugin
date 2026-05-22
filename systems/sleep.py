from datetime import datetime
from typing import Any
from core.state import ActivityType, SleepState


def derive_sleep_state(
    activity: ActivityType,
    activity_since: datetime,
    prev_activity: ActivityType,
    now: datetime,
    config: Any,
) -> SleepState:
    """纯函数：从 activity + prev_activity + 持续时长派生 SleepState。无副作用。"""
    if activity != ActivityType.SLEEPING:
        if prev_activity == ActivityType.SLEEPING:
            elapsed = (now - activity_since).total_seconds() / 60
            if elapsed < config.waking_duration_minutes:
                return SleepState.WAKING
        return SleepState.AWAKE
    elapsed = (now - activity_since).total_seconds() / 60
    if elapsed < config.sleepy_duration_minutes:
        return SleepState.SLEEPY
    return SleepState.SLEEPING
