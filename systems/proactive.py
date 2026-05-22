# systems/proactive.py
from __future__ import annotations
import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from core.state import ActivityType, SleepState
from utils.time_helper import now_utc, is_in_quiet_hours, local_date_str

logger = logging.getLogger(__name__)


@dataclass
class ProactiveGuard:
    global_cooldown_until: datetime
    per_group_cooldown: dict[str, datetime]
    daily_count: int
    daily_date: str
    daily_limit: int
    last_trigger_time: datetime | None
    consecutive_count: int
    consecutive_reset_after_minutes: int
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # nonce -> expire_time (unix timestamp)，有 TTL 自清理
    _nonce_registry: dict[str, float] = field(default_factory=dict)


def _check_guard_conditions(
    guard: ProactiveGuard, stream_id: str, snap: Any, config: Any
) -> bool:
    """检查触发条件，全部通过才返回 True。同步函数，可在锁内调用。"""
    now = now_utc()

    # 睡眠状态检查
    if snap.sleep_state == SleepState.SLEEPING:
        return False

    # quiet hours 检查
    tz = getattr(getattr(config, "plugin", None), "timezone", "Asia/Shanghai")
    qh_start = getattr(config.proactive, "quiet_hours_start", "23:00")
    qh_end = getattr(config.proactive, "quiet_hours_end", "07:00")
    if is_in_quiet_hours(now, qh_start, qh_end, tz):
        return False

    # 全局冷却
    if now < guard.global_cooldown_until:
        return False

    # 群组冷却
    group_cd = guard.per_group_cooldown.get(stream_id)
    if group_cd and now < group_cd:
        return False

    # daily_count 检查（先重置跨天计数）
    today = local_date_str(tz)
    if guard.daily_date != today:
        guard.daily_count = 0
        guard.daily_date = today
    if guard.daily_count >= guard.daily_limit:
        return False

    # 连续触发检查
    if guard.consecutive_count >= config.proactive.max_consecutive:
        if guard.last_trigger_time:
            elapsed_min = (now - guard.last_trigger_time).total_seconds() / 60
            if elapsed_min < guard.consecutive_reset_after_minutes:
                return False
        guard.consecutive_count = 0  # 超时重置

    return True


class ProactiveSystem:
    def __init__(self, db: Any, ctx: Any, manager: Any, budget: Any, config: Any):
        self._db = db
        self._ctx = ctx
        self._manager = manager
        self._budget = budget
        self._config = config
        self._guard = ProactiveGuard(
            global_cooldown_until=datetime(2000, 1, 1, tzinfo=timezone.utc),
            per_group_cooldown={},
            daily_count=0,
            daily_date="",
            daily_limit=config.proactive.daily_limit,
            last_trigger_time=None,
            consecutive_count=0,
            consecutive_reset_after_minutes=config.proactive.consecutive_reset_after_minutes,
        )

    def _make_nonce(self, stream_id: str, transition_id: str | None, source: str) -> str:
        key = f"{stream_id}:{transition_id or ''}:{source}:{local_date_str('UTC')}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    async def trigger(
        self,
        stream_id: str,
        intent: str,
        source: str,
        transition_id: str | None = None,
    ) -> None:
        if not self._config.proactive.enabled:
            return

        # Phase 1（持锁）：检查 + nonce 预注册
        async with self._guard._lock:
            snap = self._manager.snapshot()
            if not _check_guard_conditions(self._guard, stream_id, snap, self._config):
                return

            nonce = self._make_nonce(stream_id, transition_id, source)
            now_ts = time.time()

            # 清理过期 nonce
            self._guard._nonce_registry = {
                k: v for k, v in self._guard._nonce_registry.items() if v > now_ts
            }
            if nonce in self._guard._nonce_registry:
                return
            if await self._db.nonce_exists(nonce):
                return

            # debounce：同一 transition_id 在 N 秒内只触发一次
            debounce_secs = getattr(self._config.proactive, "debounce_seconds", 5)
            if transition_id:
                debounce_key = f"debounce:{transition_id}"
                if debounce_key in self._guard._nonce_registry:
                    return
                self._guard._nonce_registry[debounce_key] = now_ts + debounce_secs

            # 提前注册 nonce（释放锁前）
            self._guard._nonce_registry[nonce] = now_ts + 3600
            await self._db.register_nonce(nonce, stream_id, ttl=3600)
        # 锁释放

        # Phase 2（无锁）：生成 intent（耗时 LLM 调用）
        final_intent = await self._build_intent(intent, snap)
        if final_intent is None:
            # LLM 失败，回滚 nonce
            await self._db.delete_nonce(nonce)
            self._guard._nonce_registry.pop(nonce, None)
            return

        # Phase 3：触发 maisaka
        try:
            await self._ctx.maisaka.proactive.trigger(
                stream_id=stream_id,
                intent=final_intent,
                reason=source,
                metadata={"nonce": nonce, "source": "life_simulation"},
            )
        except Exception as e:
            logger.error("maisaka.proactive.trigger failed: %s", e)
            # 回滚：不消耗 daily quota
            await self._db.delete_nonce(nonce)
            self._guard._nonce_registry.pop(nonce, None)
            return

        # Phase 4（持锁）：更新 guard 状态
        async with self._guard._lock:
            self._update_guard(stream_id)
        await self._db.save_proactive_guard_state(self._guard_to_dict())

    async def _build_intent(self, base_intent: str, snap: Any) -> str | None:
        """生成 intent 文本。若无 prompt 模板，直接返回 base_intent。"""
        prompt_tmpl = getattr(getattr(self._config, "prompts", None), "proactive_intent", "")
        if not prompt_tmpl:
            return base_intent  # 无模板，直接用

        if not self._budget.can_llm_call("proactive_intent"):
            return base_intent  # budget 不足时 fallback 到 base_intent

        prompt_text = (prompt_tmpl
                       .replace("{state}", snap.sleep_state.value)
                       .replace("{activity}", snap.current_activity.value)
                       .replace("{description}", base_intent))

        from utils.llm_helper import generate_json
        result = await generate_json(
            self._ctx,
            prompt=[{"role": "user", "content": prompt_text}],
            schema={"required": ["intent"], "properties": {"intent": {"type": "string"}}},
            budget_key="proactive_intent",
            budget=self._budget,
        )
        if result is None:
            return None  # LLM 彻底失败，取消触发
        return result["intent"]

    def _update_guard(self, stream_id: str) -> None:
        now = now_utc()
        self._guard.global_cooldown_until = now + timedelta(
            minutes=self._config.proactive.global_cooldown_minutes
        )
        self._guard.per_group_cooldown[stream_id] = now + timedelta(
            minutes=self._config.proactive.per_group_cooldown_minutes
        )
        # 清理过期 per_group entries
        self._guard.per_group_cooldown = {
            k: v for k, v in self._guard.per_group_cooldown.items() if v > now
        }
        tz = getattr(getattr(self._config, "plugin", None), "timezone", "Asia/Shanghai")
        today = local_date_str(tz)
        if self._guard.daily_date != today:
            self._guard.daily_count = 0
            self._guard.daily_date = today
        self._guard.daily_count += 1
        self._guard.last_trigger_time = now
        self._guard.consecutive_count += 1

    def _guard_to_dict(self) -> dict:
        return {
            "global_cooldown_until": self._guard.global_cooldown_until.isoformat(),
            "daily_count": self._guard.daily_count,
            "daily_date": self._guard.daily_date,
            "consecutive_count": self._guard.consecutive_count,
            "last_trigger_time": (
                self._guard.last_trigger_time.isoformat()
                if self._guard.last_trigger_time else None
            ),
        }

    def restore_guard(self, data: dict) -> None:
        if data.get("global_cooldown_until"):
            self._guard.global_cooldown_until = datetime.fromisoformat(
                data["global_cooldown_until"]
            )
        tz = getattr(getattr(self._config, "plugin", None), "timezone", "Asia/Shanghai")
        today = local_date_str(tz)
        if data.get("daily_date") == today:
            self._guard.daily_count = data.get("daily_count", 0)
        self._guard.consecutive_count = data.get("consecutive_count", 0)
        if data.get("last_trigger_time"):
            self._guard.last_trigger_time = datetime.fromisoformat(
                data["last_trigger_time"]
            )

    async def on_transition(
        self, old_activity: ActivityType, new_activity: ActivityType, transition_id: str
    ) -> None:
        """Orchestrator transition 时调用，按概率触发主动行为。"""
        if not self._config.proactive.enabled:
            return
        snap = self._manager.snapshot()
        if snap.schedule_is_repair:
            return

        prob = self._config.proactive.schedule_transition_probability
        if snap.sleep_state == SleepState.WAKING:
            prob *= self._config.proactive.waking_probability_factor
        if random.random() > prob:
            return

        intent = f"Just transitioned from {old_activity.value} to {new_activity.value}"

        # 找一个可用的 stream_id
        streams = []
        try:
            group_streams = await self._ctx.chat.get_group_streams()
            streams = [s.get("stream_id") for s in (group_streams or []) if s.get("stream_id")]
        except Exception:
            pass
        if not streams:
            return

        await self.trigger(streams[0], intent, "transition", transition_id)

    async def check_score_trigger(self) -> None:
        """Heartbeat 触发：检查 proactive_score 高的用户，主动发消息。"""
        if not self._config.proactive.enabled:
            return
        try:
            persons = await self._db.get_persons_above_score(
                self._config.proactive.score_threshold
            )
            for person in persons:
                best = await self._db.get_best_stream_for_person(person["person_id"])
                if best is None:
                    continue
                intent = f"Feeling like chatting with {person['person_name']}"
                await self.trigger(
                    stream_id=best["stream_id"],
                    intent=intent,
                    source="heartbeat_score",
                )
        except Exception as e:
            logger.error("check_score_trigger error: %s", e, exc_info=True)
