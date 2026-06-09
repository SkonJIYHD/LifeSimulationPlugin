# systems/relation.py
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class DirtyQueue:
    """
    去重 + 最大长度 + TTL 的脏队列。
    key = (person_id, stream_id) 元组。
    asyncio 单线程模型下安全（mark/pop_batch 均为同步，无 await）。
    """

    def __init__(self, max_size: int = 500, ttl_seconds: int = 7200):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._queue: dict[tuple[str, str], float] = {}

    def mark(self, person_id: str, stream_id: str) -> None:
        key = (person_id, stream_id)
        if key in self._queue:
            return  # 去重
        if len(self._queue) >= self.max_size:
            oldest = min(self._queue, key=self._queue.get)
            del self._queue[oldest]
        self._queue[key] = time.time()

    def pop_batch(self, limit: int) -> list[tuple[str, str]]:
        now = time.time()
        # 清理过期
        expired = [k for k, t in self._queue.items() if now - t > self.ttl_seconds]
        for k in expired:
            del self._queue[k]
        # 取最旧的 limit 个
        sorted_keys = sorted(self._queue, key=self._queue.get)[:limit]
        for k in sorted_keys:
            del self._queue[k]
        return sorted_keys


class RelationSystem:
    def __init__(self, db: Any, ctx: Any, budget: Any, config: Any):
        self._db = db
        self._ctx = ctx
        self._budget = budget
        self._config = config
        self._dirty_queue = DirtyQueue(
            max_size=getattr(config, "dirty_queue_max_size", 500),
            ttl_seconds=getattr(config, "dirty_queue_ttl_seconds", 7200),
        )

    async def mark_interaction(
        self, person_id: str, stream_id: str, message: dict
    ) -> None:
        """Hook 触发：记录互动，标记 dirty。纯写操作，不调用 LLM。"""
        try:
            await self._db.update_person_stream(person_id, stream_id, time.time())
            await self._db.mark_dirty(person_id)
            self._dirty_queue.mark(person_id, stream_id)
        except Exception as e:
            logger.error("mark_interaction error: %s", e, exc_info=True)

    async def flush_dirty_impressions(self) -> None:
        """
        Heartbeat 触发：批量 AI 更新印象。
        冷却中的记录放回队列，不丢弃。
        LLM 失败则跳过（不放回，避免反复调用失败的 LLM）。
        """
        from utils.llm_helper import generate_json

        limit = self._budget.get_flush_limit()
        pairs = self._dirty_queue.pop_batch(limit=limit)
        now = datetime.now(tz=timezone.utc)

        for person_id, stream_id in pairs:
            try:
                imp = await self._db.get_impression(person_id)

                # 冷却检查
                if imp and imp.get("last_impression_update"):
                    elapsed_min = (now.timestamp() - imp["last_impression_update"]) / 60
                    min_interval = getattr(self._config, "min_update_interval_minutes", 30)
                    if elapsed_min < min_interval:
                        self._dirty_queue.mark(person_id, stream_id)  # 放回，不丢弃
                        continue

                # Budget 检查
                if not self._budget.can_llm_call("impression"):
                    self._dirty_queue.mark(person_id, stream_id)  # 放回
                    break

                # 拉取最近消息
                recent_msgs = await self._ctx.message.get_recent(
                    chat_id=stream_id, limit=20
                )

                person_name = imp["person_name"] if imp else person_id
                old_imp_str = str({
                    "traits": imp.get("traits", []),
                    "affinity": imp.get("affinity", 0.5),
                }) if imp else "No previous impression"

                prompt_tmpl = getattr(getattr(self._config, "prompts", None), "impression_update", "")
                if prompt_tmpl:
                    prompt_text = (prompt_tmpl
                                   .replace("{person_name}", person_name)
                                   .replace("{recent_messages}", str(recent_msgs))
                                   .replace("{old_impression}", old_imp_str))
                else:
                    prompt_text = (
                        f"Based on recent messages from {person_name}: {recent_msgs}\n"
                        f"Previous impression: {old_imp_str}\n"
                        f"Update the impression. Return JSON:\n"
                        f'{{"traits": ["trait1", "trait2"], '
                        f'"affinity": 0.5, '
                        f'"had_recent_interaction": true}}'
                    )

                schema = {
                    "required": ["traits", "affinity"],
                    "properties": {
                        "traits": {"type": "array"},
                        "affinity": {"type": "number"},
                    },
                }
                result = await generate_json(
                    self._ctx,
                    prompt=[{"role": "user", "content": prompt_text}],
                    schema=schema,
                    budget_key="impression",
                    budget=self._budget,
                )
                if result is None:
                    continue  # LLM 失败，跳过，不放回

                new_score = self._update_proactive_score(imp, result)
                new_imp = {
                    "person_id": person_id,
                    "person_name": person_name,
                    "traits": result.get("traits", []),
                    "affinity": float(result.get("affinity", 0.5)),
                    "proactive_score": new_score,
                    "last_impression_update": now.timestamp(),
                }
                if imp and imp.get("last_interaction"):
                    new_imp["last_interaction"] = imp["last_interaction"]
                await self._db.save_impression(new_imp)

            except Exception as e:
                logger.error(
                    "flush impression for %s failed: %s", person_id, e, exc_info=True
                )

    def _update_proactive_score(self, old_imp: dict | None, new_data: dict) -> float:
        """proactive_score 增减逻辑：正向互动加分，长期沉默衰减。"""
        score = old_imp["proactive_score"] if old_imp else 0.0

        # 正向增长
        if new_data.get("had_recent_interaction"):
            score = min(1.0, score + 0.15)
        if new_data.get("user_replied_to_proactive"):
            score = min(1.0, score + 0.2)
        if float(new_data.get("affinity", 0.5)) > 0.7:
            score = min(1.0, score + 0.05)

        # 负向衰减（基于上次互动时间）
        if old_imp and old_imp.get("last_interaction"):
            days_silent = (time.time() - old_imp["last_interaction"]) / 86400
            decay = min(days_silent * 0.05, 0.3)
            score = max(0.0, score - decay)

        return round(score, 4)
