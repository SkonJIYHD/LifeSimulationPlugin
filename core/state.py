from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SleepState(Enum):
    AWAKE = "awake"
    SLEEPY = "sleepy"
    SLEEPING = "sleeping"
    WAKING = "waking"


class ActivityType(Enum):
    SLEEPING = "sleeping"
    EATING = "eating"
    STUDYING = "studying"
    EXERCISING = "exercising"
    LEISURE = "leisure"
    WORKING = "working"
    OTHER = "other"


@dataclass(frozen=True)
class ScheduleItem:
    start_time: datetime
    end_time: datetime
    activity: ActivityType
    description: str
    is_skeleton: bool = False


@dataclass(frozen=True)
class RecentEvent:
    event_type: str
    description: str
    timestamp: datetime
    ttl_seconds: int = 3600


@dataclass(frozen=True)
class LifeStateSnapshot:
    sleep_state: SleepState
    current_activity: ActivityType
    prev_activity: ActivityType
    activity_since: datetime
    last_transition_processed_at: datetime
    schedule_generated_date: str
    schedule_is_repair: bool
    today_schedule: tuple
    recent_events: tuple


@dataclass
class LifeState:
    current_activity: ActivityType = ActivityType.OTHER
    prev_activity: ActivityType = ActivityType.OTHER
    activity_since: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc))
    last_transition_processed_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc))
    sleep_state: SleepState = SleepState.AWAKE
    today_schedule: list = field(default_factory=list)
    schedule_generated_date: str = ""
    schedule_is_repair: bool = False
    recent_events: list = field(default_factory=list)


class LifeStateManager:
    def __init__(self, config: Any):
        self._config = config
        self._lock = asyncio.Lock()
        self._state = LifeState()
        self._processed_transitions: dict[str, float] = {}

    def snapshot(self) -> LifeStateSnapshot:
        s = self._state
        return LifeStateSnapshot(
            sleep_state=s.sleep_state,
            current_activity=s.current_activity,
            prev_activity=s.prev_activity,
            activity_since=s.activity_since,
            last_transition_processed_at=s.last_transition_processed_at,
            schedule_generated_date=s.schedule_generated_date,
            schedule_is_repair=s.schedule_is_repair,
            today_schedule=tuple(s.today_schedule),
            recent_events=tuple(s.recent_events),
        )

    async def transition_activity(
        self, new_activity: ActivityType, transition_id: str
    ) -> bool:
        from systems.sleep import derive_sleep_state
        async with self._lock:
            now_ts = time.time()
            self._processed_transitions = {
                k: v for k, v in self._processed_transitions.items() if v > now_ts
            }
            if transition_id in self._processed_transitions:
                return False
            self._processed_transitions[transition_id] = now_ts + 86400
            now = datetime.now(tz=timezone.utc)
            prev = self._state.current_activity
            self._state.prev_activity = prev
            self._state.current_activity = new_activity
            self._state.activity_since = now
            self._state.last_transition_processed_at = now
            self._state.sleep_state = derive_sleep_state(
                activity=new_activity,
                activity_since=now,
                prev_activity=prev,
                now=now,
                config=self._config.sleep,
            )
            return True

    async def set_schedule(self, items: list, is_repair: bool = False) -> None:
        async with self._lock:
            self._state.today_schedule = list(items)
            self._state.schedule_is_repair = is_repair

    async def set_schedule_generated_date(self, date_str: str) -> None:
        async with self._lock:
            self._state.schedule_generated_date = date_str

    async def append_event(self, event: RecentEvent) -> None:
        async with self._lock:
            now = datetime.now(tz=timezone.utc)
            self._state.recent_events = [
                e for e in self._state.recent_events
                if (now - e.timestamp).total_seconds() < e.ttl_seconds
            ]
            self._state.recent_events.append(event)
            max_e = self._config.max_recent_events
            if len(self._state.recent_events) > max_e:
                self._state.recent_events = self._state.recent_events[-max_e:]

    async def restore(self, data: dict) -> None:
        async with self._lock:
            s = self._state
            s.current_activity = ActivityType(data.get("current_activity", "other"))
            s.prev_activity = ActivityType(data.get("prev_activity", "other"))
            s.sleep_state = SleepState(data.get("sleep_state", "awake"))
            s.schedule_generated_date = data.get("schedule_generated_date", "")

    async def restore_processed_transitions(
        self, transitions: dict[str, float]
    ) -> None:
        async with self._lock:
            self._processed_transitions.update(transitions)
