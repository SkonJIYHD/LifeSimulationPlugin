# tests/test_hooks.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from core.state import SleepState, ActivityType, LifeStateSnapshot
from datetime import datetime, timezone


def make_snap(sleep_state=SleepState.AWAKE):
    return LifeStateSnapshot(
        sleep_state=sleep_state,
        current_activity=ActivityType.OTHER,
        prev_activity=ActivityType.OTHER,
        activity_since=datetime.now(tz=timezone.utc),
        last_transition_processed_at=datetime.now(tz=timezone.utc),
        schedule_generated_date="2026-05-22",
        schedule_is_repair=False,
        today_schedule=tuple(),
        recent_events=tuple(),
    )


@pytest.mark.asyncio
async def test_sleep_gate_aborts_when_sleeping():
    from components.hooks import handle_sleep_gate
    manager = MagicMock()
    manager.snapshot.return_value = make_snap(SleepState.SLEEPING)
    stream_registry = MagicMock()
    result = await handle_sleep_gate(manager, stream_registry,
                                     message={"stream_id": "s1", "message_id": "m1"})
    assert result == {"action": "abort"}


@pytest.mark.asyncio
async def test_sleep_gate_continues_when_awake():
    from components.hooks import handle_sleep_gate
    manager = MagicMock()
    manager.snapshot.return_value = make_snap(SleepState.AWAKE)
    stream_registry = MagicMock()
    msg = {"stream_id": "s1", "message_id": "m1"}
    result = await handle_sleep_gate(manager, stream_registry, message=msg)
    assert result["action"] == "continue"
    stream_registry.register.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_observe_interaction_creates_task():
    from components.hooks import observe_interaction
    relation = MagicMock()
    relation.mark_interaction = AsyncMock()
    registry = MagicMock()
    registry.create_task = MagicMock()
    msg = {"stream_id": "s1", "person_id": "p1", "message_id": "m1"}
    await observe_interaction(relation, registry, message=msg)
    registry.create_task.assert_called_once()
