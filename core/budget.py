# core/budget.py
from __future__ import annotations
import time
from collections import defaultdict
from typing import Any


class ResourceBudget:
    """
    per-hour LLM 调用预算（滑动窗口，内存）。
    schedule 使用 per-day 窗口（86400s），其余 per-hour（3600s）。
    proactive daily 预算由 ProactiveGuard 管理，Budget 不重复维护。
    dirty_flush 每 heartbeat 上限通过 get_flush_limit() 获取。
    """

    def __init__(self, config: Any):
        self._config = config
        # call_type -> list of unix timestamps (within sliding window)
        self._hourly: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str) -> None:
        window = 86400 if key == "schedule" else 3600
        cutoff = time.time() - window
        self._hourly[key] = [t for t in self._hourly[key] if t > cutoff]

    def can_llm_call(self, call_type: str) -> bool:
        self._cleanup(call_type)
        limits = {
            "schedule": self._config.llm_schedule_per_day,
            "impression": self._config.llm_impression_per_hour,
            "proactive_intent": self._config.llm_proactive_intent_per_hour,
        }
        limit = limits.get(call_type, 100)
        return len(self._hourly[call_type]) < limit

    def record_llm(self, call_type: str) -> None:
        self._hourly[call_type].append(time.time())

    def get_flush_limit(self) -> int:
        return self._config.dirty_flush_per_heartbeat

    async def restore_from_db(self) -> None:
        pass  # per-hour sliding window: 重启丢失可接受

    async def flush_daily_counters(self) -> None:
        pass  # per-hour budget 不需要持久化
