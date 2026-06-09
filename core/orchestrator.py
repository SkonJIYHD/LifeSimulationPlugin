from __future__ import annotations
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import systems.schedule as schedule_mod
from core.state import ActivityType, RecentEvent
from utils.time_helper import now_utc, local_date_str, is_in_quiet_hours

logger = logging.getLogger(__name__)


class StreamRegistry:
    """维护所有曾出现过消息的 stream_id 列表，供频率调整批量调用使用。"""

    def __init__(self):
        self._streams: set[str] = set()

    def register(self, stream_id: str) -> None:
        self._streams.add(stream_id)

    def get_all(self) -> list[str]:
        return list(self._streams)


class BackgroundTaskRegistry:
    """统一管理 create_task，done callback 自动捕获异常，cancel_all 时统一清理。"""

    def __init__(self):
        self._tasks: set[asyncio.Task] = set()

    def create_task(self, coro, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        task.add_done_callback(self._on_done)
        self._tasks.add(task)
        return task

    def _on_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background task '%s' raised: %s", task.get_name(), exc, exc_info=exc)

    async def cancel_all(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class Orchestrator:
    def __init__(
        self,
        manager: Any,
        db: Any,
        budget: Any,
        schedule_sys: Any,
        relation_sys: Any,
        proactive_sys: Any,
        ctx: Any,
        config: Any,
        stream_registry: StreamRegistry,
    ):
        self._manager = manager
        self._db = db
        self._budget = budget
        self._schedule = schedule_sys
        self._relation = relation_sys
        self._proactive = proactive_sys
        self._ctx = ctx
        self._config = config
        self._stream_registry = stream_registry
        self._registry = BackgroundTaskRegistry()

    async def start(self) -> None:
        await self._db.start()
        await self._recovery_check()
        self._registry.create_task(self._run(), name="orchestrator.main")
        self._registry.create_task(self._heartbeat(), name="orchestrator.heartbeat")

    async def stop(self) -> None:
        # 先 cancel 所有任务（停止产生新写操作），再 drain DB queue
        await self._registry.cancel_all()
        await self._db.stop()

    async def _run(self) -> None:
        """主循环：精确 sleep_until next_transition，醒来后校验漂移。"""
        while True:
            try:
                snap = self._manager.snapshot()
                now = now_utc()
                next_time, _ = schedule_mod.calc_next_transition(snap, now)
                sleep_secs = max((next_time - now).total_seconds(), 0)
                await asyncio.sleep(sleep_secs)

                # 醒来后重新校验（防系统休眠漂移）
                actual_now = now_utc()
                snap = self._manager.snapshot()

                # 处理 missed transitions（以 last_transition_processed_at 为起点）
                missed = schedule_mod.get_missed_transitions(snap, actual_now)
                for missed_act, missed_time in missed:
                    tid = f"transition:{missed_time.isoformat()}:{missed_act.value}"
                    await self._on_transition(missed_act, tid, is_missed=True)

                # 处理当前 transition
                snap = self._manager.snapshot()
                actual_act = schedule_mod.get_current_activity(snap, actual_now)
                tid = f"transition:{actual_now.isoformat()}:{actual_act.value}"
                await self._on_transition(actual_act, tid)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Orchestrator _run error: %s", e, exc_info=True)
                await asyncio.sleep(10)  # 单次迭代异常，短暂退避后继续

    async def _on_transition(
        self, new_activity: ActivityType, transition_id: str, is_missed: bool = False
    ) -> None:
        """activity 切换的副作用链，各步骤独立 try/except。"""
        old_snap = self._manager.snapshot()
        ok = await self._manager.transition_activity(new_activity, transition_id)
        if not ok:
            return  # 幂等跳过

        # 1. 频率调整（对所有已知 stream 批量调用）
        try:
            await self._apply_frequency(new_activity)
        except Exception as e:
            logger.error("apply_frequency failed: %s", e)

        # 2. 主动行为触发（仅非 missed 且非 repair 的 transition）
        try:
            if not is_missed and not old_snap.schedule_is_repair:
                await self._proactive.on_transition(
                    old_snap.current_activity, new_activity, transition_id
                )
        except Exception as e:
            logger.error("proactive.on_transition failed: %s", e)

        # 3. 持久化（必须执行）
        await (await self._db.enqueue_write(self._make_persist_op()))

        # 3.5 持久化 processed_transition（幂等恢复用）
        await self._db.save_processed_transition(transition_id)

        # 4. 追加 recent_event
        await self._manager.append_event(RecentEvent(
            event_type="schedule_transition",
            description=f"{old_snap.current_activity.value} -> {new_activity.value}",
            timestamp=now_utc(),
        ))

    def _make_persist_op(self):
        """生成一个持久化当前状态的写操作（闭包，捕获当前 snapshot）。"""
        snap = self._manager.snapshot()
        data = {
            "current_activity": snap.current_activity.value,
            "prev_activity": snap.prev_activity.value,
            "sleep_state": snap.sleep_state.value,
            "schedule_generated_date": snap.schedule_generated_date,
            "activity_since": snap.activity_since.isoformat(),
            "last_transition_processed_at": snap.last_transition_processed_at.isoformat(),
        }
        serialized = json.dumps(data)
        ts = time.time()

        async def op(conn):
            await conn.execute(
                "INSERT OR REPLACE INTO life_state (key, value, updated_at) VALUES (?, ?, ?)",
                ("main", serialized, ts),
            )
        return op

    async def _apply_frequency(self, activity: ActivityType) -> None:
        """遍历所有已知 stream，批量调用 frequency.set_adjust()。"""
        freq_map = {
            "sleeping": -1.0, "exercising": -0.6,
            "studying": -0.4, "working": -0.4,
            "eating": -0.2, "leisure": 0.0, "other": 0.0,
        }
        # 优先从 config 读取
        if hasattr(self._config, "frequency"):
            cfg_freq = self._config.frequency
            factor = getattr(cfg_freq, activity.value, freq_map.get(activity.value, 0.0))
        else:
            factor = freq_map.get(activity.value, 0.0)

        for stream_id in self._stream_registry.get_all():
            try:
                await self._ctx.frequency.set_adjust(stream_id, factor)
            except Exception as e:
                logger.warning("set_adjust failed for %s: %s", stream_id, e)

    async def _heartbeat(self) -> None:
        """定期心跳：各子任务用 create_task 隔离，互不阻塞。"""
        while True:
            try:
                interval = getattr(getattr(self._config, "heartbeat", None), "interval_seconds", 600)
                await asyncio.sleep(interval)
                self._registry.create_task(
                    self._relation.flush_dirty_impressions(),
                    name="heartbeat.flush_impressions",
                )
                self._registry.create_task(
                    self._proactive.check_score_trigger(),
                    name="heartbeat.score_trigger",
                )
                self._registry.create_task(
                    self._db.maybe_checkpoint(),
                    name="heartbeat.checkpoint",
                )
                self._registry.create_task(
                    self._db.cleanup_expired(),
                    name="heartbeat.cleanup",
                )
                self._registry.create_task(
                    self._budget.flush_daily_counters(),
                    name="heartbeat.budget_flush",
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Orchestrator _heartbeat error: %s", e, exc_info=True)
                await asyncio.sleep(30)

    async def _recovery_check(self) -> None:
        """
        启动时恢复：加载持久化状态 → 恢复幂等缓存 → 检查跨天 → repair missed transitions。
        """
        # 1. 从 DB 恢复 LifeState
        persisted = await self._db.load_state()
        if persisted:
            await self._manager.restore(persisted)

        # 2. 从 DB 恢复 _processed_transitions（重启幂等）
        unexpired = await self._db.load_processed_transitions_unexpired()
        await self._manager.restore_processed_transitions(unexpired)

        # 3. 从 DB 恢复 proactive guard 状态
        guard_state = await self._db.load_proactive_guard_state()
        if guard_state:
            self._proactive.restore_guard(guard_state)

        # 4. 恢复 budget
        await self._budget.restore_from_db()

        # 5. 检查跨天，需重新生成日程
        tz = getattr(getattr(self._config, "plugin", None), "timezone", "Asia/Shanghai")
        local_today = local_date_str(tz)
        if self._manager.snapshot().schedule_generated_date != local_today:
            await self._schedule.generate(local_today, is_recovery=True)
            # 生成新日程后立即同步当前活动
            snap = self._manager.snapshot()
            current_act = schedule_mod.get_current_activity(snap, now_utc())
            tid = f"recovery_sync:{now_utc().isoformat()}:{current_act.value}"
            await self._on_transition(current_act, tid, is_missed=True)

        # 6. repair missed transitions（不触发 proactive）
        snap = self._manager.snapshot()
        missed = schedule_mod.get_missed_transitions(snap, now_utc())
        for act, t in missed:
            tid = f"transition:{t.isoformat()}:{act.value}"
            await self._on_transition(act, tid, is_missed=True)

    def reload_config(self, config: Any) -> None:
        self._config = config
        self._schedule._config = config
        self._relation._config = config
        self._proactive._config = config
        self._budget._config = config
        self._manager._config = config
        logger.info("Orchestrator config reloaded")
