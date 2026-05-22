# components/hooks.py
# 纯业务逻辑函数，不含任何 SDK 装饰器
# SDK 装饰器方法在 plugin.py 的 LifeSimulationPlugin 中定义
from __future__ import annotations
import logging
from core.state import SleepState

logger = logging.getLogger(__name__)


async def handle_sleep_gate(manager, stream_registry, **kwargs) -> dict:
    """Sleep gate logic: abort if sleeping, register stream otherwise."""
    message = kwargs.get("message", {})
    snap = manager.snapshot()

    if snap.sleep_state == SleepState.SLEEPING:
        return {"action": "abort"}

    stream_id = message.get("stream_id")
    if stream_id:
        stream_registry.register(stream_id)

    kwargs["message"] = message
    return {"action": "continue", "modified_kwargs": kwargs}


async def observe_interaction(relation, registry, **kwargs) -> None:
    """Observe message to mark dirty in relation system."""
    message = kwargs.get("message", {})
    person_id = (message.get("person_id") or
                 message.get("user_info", {}).get("person_id"))
    stream_id = message.get("stream_id")
    if person_id and stream_id:
        registry.create_task(
            relation.mark_interaction(person_id, stream_id, message),
            name=f"mark_interaction:{message.get('message_id', 'unknown')}",
        )
