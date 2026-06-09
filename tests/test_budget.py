# tests/test_budget.py
import pytest
import time
from unittest.mock import MagicMock
from core.budget import ResourceBudget


@pytest.fixture
def config():
    c = MagicMock()
    c.llm_schedule_per_day = 3
    c.llm_impression_per_hour = 50
    c.llm_proactive_intent_per_hour = 20
    c.dirty_flush_per_heartbeat = 10
    return c


def test_schedule_uses_daily_window(config):
    """Fix 5: schedule budget should use 86400s window, not 3600s."""
    budget = ResourceBudget(config)
    # Record 3 schedule calls (at limit)
    for _ in range(3):
        budget.record_llm("schedule")
    assert budget.can_llm_call("schedule") is False

    # After 1 hour, hourly window would reset, but daily should NOT
    budget._hourly["schedule"] = [t - 3601 for t in budget._hourly["schedule"]]
    assert budget.can_llm_call("schedule") is False


def test_impression_uses_hourly_window(config):
    """Impression budget should use 3600s window."""
    budget = ResourceBudget(config)
    for _ in range(50):
        budget.record_llm("impression")
    assert budget.can_llm_call("impression") is False

    # After 1 hour, should be allowed again
    budget._hourly["impression"] = [t - 3601 for t in budget._hourly["impression"]]
    assert budget.can_llm_call("impression") is True


def test_schedule_window_resets_after_day(config):
    """Fix 5: schedule budget should reset after 86400s."""
    budget = ResourceBudget(config)
    for _ in range(3):
        budget.record_llm("schedule")
    assert budget.can_llm_call("schedule") is False

    # After 24 hours, should be allowed again
    budget._hourly["schedule"] = [t - 86401 for t in budget._hourly["schedule"]]
    assert budget.can_llm_call("schedule") is True
