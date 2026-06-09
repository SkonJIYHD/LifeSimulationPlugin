# tests/test_orchestrator.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from core.orchestrator import Orchestrator, StreamRegistry


@pytest.fixture
def orchestrator():
    manager = MagicMock()
    db = MagicMock()
    budget = MagicMock()
    schedule_sys = MagicMock()
    relation_sys = MagicMock()
    proactive_sys = MagicMock()
    ctx = MagicMock()
    config = MagicMock()
    stream_registry = StreamRegistry()

    return Orchestrator(
        manager=manager,
        db=db,
        budget=budget,
        schedule_sys=schedule_sys,
        relation_sys=relation_sys,
        proactive_sys=proactive_sys,
        ctx=ctx,
        config=config,
        stream_registry=stream_registry,
    )


def test_reload_config_propagates_to_subsystems(orchestrator):
    """Fix 9: reload_config should push new config to all subsystems."""
    new_config = MagicMock()
    orchestrator.reload_config(new_config)

    assert orchestrator._config is new_config
    assert orchestrator._schedule._config is new_config
    assert orchestrator._relation._config is new_config
    assert orchestrator._proactive._config is new_config
    assert orchestrator._budget._config is new_config
    assert orchestrator._manager._config is new_config
