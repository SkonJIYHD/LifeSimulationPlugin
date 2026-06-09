# tests/test_proactive.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock
from core.state import SleepState, ActivityType
from systems.proactive import ProactiveGuard, _check_guard_conditions, ProactiveSystem


@pytest.fixture
def config():
    c = MagicMock()
    c.proactive.enabled = True
    c.proactive.global_cooldown_minutes = 30
    c.proactive.per_group_cooldown_minutes = 60
    c.proactive.daily_limit = 5
    c.proactive.max_consecutive = 2
    c.proactive.consecutive_reset_after_minutes = 120
    c.proactive.score_threshold = 0.7
    c.proactive.debounce_seconds = 5
    c.proactive.schedule_transition_probability = 1.0
    c.proactive.waking_probability_factor = 0.3
    c.proactive.quiet_hours_start = "02:00"   # 使用不太可能命中的时间避免测试时序问题
    c.proactive.quiet_hours_end = "03:00"
    c.plugin.timezone = "Asia/Shanghai"
    return c


@pytest.fixture
def fresh_guard():
    return ProactiveGuard(
        global_cooldown_until=datetime(2000, 1, 1, tzinfo=timezone.utc),
        per_group_cooldown={},
        daily_count=0,
        daily_date="2000-01-01",
        daily_limit=5,
        last_trigger_time=None,
        consecutive_count=0,
        consecutive_reset_after_minutes=120,
    )


def test_guard_passes_when_fresh(fresh_guard, config):
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    ok = _check_guard_conditions(fresh_guard, "stream-1", snap, config)
    assert ok is True


def test_guard_fails_when_sleeping(fresh_guard, config):
    snap = MagicMock()
    snap.sleep_state = SleepState.SLEEPING
    ok = _check_guard_conditions(fresh_guard, "stream-1", snap, config)
    assert ok is False


def test_guard_fails_when_daily_limit_reached(fresh_guard, config):
    fresh_guard.daily_count = 5
    fresh_guard.daily_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    ok = _check_guard_conditions(fresh_guard, "stream-1", snap, config)
    assert ok is False


def test_guard_fails_when_global_cooldown(fresh_guard, config):
    fresh_guard.global_cooldown_until = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    ok = _check_guard_conditions(fresh_guard, "stream-1", snap, config)
    assert ok is False


@pytest.mark.asyncio
async def test_trigger_calls_maisaka(config):
    db = MagicMock()
    db.nonce_exists = AsyncMock(return_value=False)
    db.register_nonce = AsyncMock()
    db.delete_nonce = AsyncMock()
    db.save_proactive_guard_state = AsyncMock()
    db.enqueue_write = AsyncMock(return_value=AsyncMock())
    ctx = MagicMock()
    ctx.maisaka.proactive.trigger = AsyncMock()
    # prompts.proactive_intent 为空 -> 直接用 base_intent，不调用 LLM
    config.prompts.proactive_intent = ""
    manager = MagicMock()
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    snap.schedule_is_repair = False
    manager.snapshot.return_value = snap
    budget = MagicMock()
    budget.can_llm_call.return_value = True
    budget.record_llm = MagicMock()

    sys = ProactiveSystem(db=db, ctx=ctx, manager=manager, budget=budget, config=config)
    await sys.trigger("stream-1", "Just finished lunch", "transition", "tid-001")
    ctx.maisaka.proactive.trigger.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_rechecks_guards_before_send(config):
    """Fix 8: trigger should re-check guard conditions after LLM call."""
    db = MagicMock()
    db.nonce_exists = AsyncMock(return_value=False)
    db.register_nonce = AsyncMock()
    db.delete_nonce = AsyncMock()
    db.save_proactive_guard_state = AsyncMock()
    ctx = MagicMock()
    ctx.maisaka.proactive.trigger = AsyncMock()

    config.prompts.proactive_intent = ""

    manager = MagicMock()
    # First snapshot: AWAKE (passes guard)
    snap_awake = MagicMock()
    snap_awake.sleep_state = SleepState.AWAKE
    snap_awake.schedule_is_repair = False
    # Second snapshot: SLEEPING (fails re-check)
    snap_sleeping = MagicMock()
    snap_sleeping.sleep_state = SleepState.SLEEPING

    call_count = 0
    def mock_snapshot():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return snap_awake
        return snap_sleeping

    manager.snapshot.side_effect = mock_snapshot
    budget = MagicMock()

    sys = ProactiveSystem(db=db, ctx=ctx, manager=manager, budget=budget, config=config)
    await sys.trigger("stream-1", "Hello", "transition", "tid-002")

    # Should NOT have called maisaka because re-check found SLEEPING
    ctx.maisaka.proactive.trigger.assert_not_called()
    # Should have cleaned up nonce
    db.delete_nonce.assert_awaited()


@pytest.mark.asyncio
async def test_trigger_succeeds_when_recheck_passes(config):
    """Fix 8: trigger should send when re-check also passes."""
    db = MagicMock()
    db.nonce_exists = AsyncMock(return_value=False)
    db.register_nonce = AsyncMock()
    db.delete_nonce = AsyncMock()
    db.save_proactive_guard_state = AsyncMock()
    ctx = MagicMock()
    ctx.maisaka.proactive.trigger = AsyncMock()

    config.prompts.proactive_intent = ""

    manager = MagicMock()
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    snap.schedule_is_repair = False
    manager.snapshot.return_value = snap
    budget = MagicMock()

    sys = ProactiveSystem(db=db, ctx=ctx, manager=manager, budget=budget, config=config)
    await sys.trigger("stream-1", "Hello", "transition", "tid-003")

    ctx.maisaka.proactive.trigger.assert_awaited_once()
