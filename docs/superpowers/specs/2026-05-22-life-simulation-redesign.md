# Life Simulation Plugin 重设计 设计文档

**日期：** 2026-05-22  
**版本：** v2.0（完全重写）  
**目标 MaiBot SDK：** maibot-plugin-sdk（新版，SDK 2.0）

---

## 1. 目标与初衷

让 MaiBot 更拟人：有自己的日常生活节奏，会因为"在忙"减少发言，被问时能根据当前状态和人格 AI 生成自然的回答，偶尔主动发消息，并对群里的人形成基于自身人格的印象和关系。

---

## 2. 功能范围

### 2.1 包含功能

| 功能 | 说明 |
|------|------|
| **日程系统** | 每天 AI 生成一份日程，固定骨架（睡眠/三餐）+ AI 填充其余时间段 |
| **睡眠系统** | 4 个状态：清醒 / 困倦 / 睡着 / 苏醒，派生自日程活动，睡着时拦截消息 |
| **频率控制** | activity transition 时通过 `frequency.set_adjust()` 调整发言频率，对所有已知 stream 批量调用，Hook 内只读不写 |
| **关系网** | 记录与每个用户的互动印象（基于人格 AI 批量更新），影响回复倾向和主动发消息对象 |
| **主动行为** | 事件驱动触发，含全局限流和完整幂等保护，通过 `maisaka.proactive.trigger()` 让 MaiBot 主动发消息 |
| **Tool（LLM 工具）** | 给 MaiBot 推理引擎提供摘要态状态查询接口，仅返回自然语言 hint |
| **插件 API** | 暴露核心状态 API 供其他插件调用，使用显式 DTO，versioned schema |

### 2.2 全局单人格状态模型（设计决策）

MaiBot 是一个人，不是多个实例。全局只有一套日程、睡眠、activity、proactive 状态，所有群共享。这是 feature，不是 bug：MaiBot 在群 A 吃饭，群 B 就应该也知道它在吃饭。

`frequency.set_adjust(chat_id, value)` SDK 要求传入 `chat_id`，无全局模式。`_apply_frequency()` 在每次 transition 时遍历所有已知 stream_id 批量调用，stream 列表由 `stream_registry` 维护（每收到一条消息时更新）。

### 2.3 不做的功能

- 天气感知
- 节日 API
- 记忆系统（归 MaiBot 宿主负责）
- 调试命令系统（可后续补充）
- 疾病/健康系统（YAGNI）
- 旧版社交网络亲密度数值体系
- 习惯系统

---

## 3. 架构设计

### 3.1 目录结构

```
life-simulation/
├── _manifest.json
├── plugin.py                   # 入口：继承 MaiBotPlugin，注册所有组件，管理生命周期
├── config.toml
├── requirements.txt
├── core/
│   ├── __init__.py
│   ├── state.py                # LifeStateManager：asyncio.Lock，对外只暴露 frozen snapshot
│   ├── database.py             # SQLite 封装（WAL，读写分离双连接，single writer queue，原子事务）
│   ├── orchestrator.py         # 调度编排：事件驱动 + transition timer，background task registry
│   └── budget.py               # 资源预算：LLM 调用限额，proactive 限额，dirty flush 限额（daily 持久化）
├── systems/
│   ├── __init__.py
│   ├── schedule.py             # 日程系统（AI 生成 + 骨架 + schema validate + repair 次数限制 + fallback）
│   ├── sleep.py                # 睡眠状态派生（纯函数，不 import 其他 system）
│   ├── relation.py             # 关系网（dirty 队列 + 去重 + TTL + 批量 AI 更新 + score 增减）
│   └── proactive.py            # 主动行为（全局/群组限流 + 幂等保护 + nonce registry + guard 持久化）
├── components/
│   ├── __init__.py
│   ├── hooks.py                # @HookHandler：blocking 极简，后台任务通过 registry 管理
│   ├── tools.py                # @Tool：摘要态 hint，不暴露底层字段
│   ├── commands.py             # @Command：/life_status 等用户命令
│   └── apis.py                 # @API：显式 DTO，versioned schema，供其他插件调用
└── utils/
    ├── __init__.py
    ├── llm_helper.py           # LLM 调用封装（timeout/retry/schema validate/repair limit/budget check）
    └── time_helper.py          # 时间工具（timezone-aware UTC，展示层转本地时间）
```

### 3.2 模块职责边界与通信规则

**核心原则：systems 之间禁止互相 import，所有系统仅通过 LifeStateManager 和 orchestrator 通信。**

```
plugin.py
    └── 持有 LifeStateManager 单例（on_load 中初始化，组件方法体运行时已可用）
    └── 初始化 orchestrator（注入 manager + ctx + budget）
    └── 注册所有 components（装饰器声明式，方法体在被调用时执行）
    └── on_load()  → orchestrator.start()（recovery check → 启动 task）
    └── on_unload() → orchestrator.stop()（drain write queue → cancel tasks → FULL checkpoint）
    └── on_config_update() → orchestrator.reload_config()（热更新，见 reload policy）

orchestrator ──调用→ systems/*（schedule/sleep/relation/proactive）
orchestrator ──持有→ background_task_registry（统一管理 create_task，done callback 捕获异常）
systems/*    ──通过 manager 读写→ LifeStateManager
components/* ──通过 manager.snapshot() 只读→ LifeStateSnapshot（frozen，tuple 化字段）
hooks.py     ──只读 snapshot，不调用任何 system，后台任务通过 registry 包裹──
DB 写操作    ──全部通过 single writer queue，reader 使用独立连接──
```

---

## 4. 核心模块详细设计

### 4.1 状态管理（core/state.py）

`LifeStateManager` 是并发安全的状态管理器。所有写操作必须通过方法入口；外部模块只能拿到不可变的 frozen snapshot，所有 list/dict 字段均 tuple 化或 deep copy。

**snapshot 防泄漏规则：**
- `today_schedule`：`ScheduleItem` 是 frozen dataclass，所有字段不可变（`datetime`、`ActivityType`、`str`、`bool`），直接 `tuple(self._state.today_schedule)` 即可，无需 deep copy。
- `recent_events`：`RecentEvent` 改为 `frozen=True`，直接 `tuple(self._state.recent_events)`。
- `snapshot()` 是同步方法，无 `await`，asyncio 单线程协作调度保证不被协程切换打断（注意：安全保证来自 asyncio 单线程模型，而非 GIL）。

```python
@dataclass(frozen=True)
class LifeStateSnapshot:
    """对外暴露的不可变快照。所有 list/dict 字段均 tuple 化，防止外部修改。"""
    sleep_state: SleepState
    current_activity: ActivityType
    prev_activity: ActivityType                 # 用于 WAKING 状态派生
    activity_since: datetime                    # timezone-aware UTC
    last_transition_processed_at: datetime      # 用于 get_missed_transitions 的起点
    schedule_generated_date: str                # 本地时区日期 "YYYY-MM-DD"
    today_schedule: tuple[ScheduleItem, ...]    # frozen item，tuple 化
    recent_events: tuple[RecentEvent, ...]      # frozen item，tuple 化

class LifeStateManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._state: LifeState = LifeState()
        # _processed_transitions 在 manager 层，不在 LifeState 里
        # 使用 dict[str, float]（transition_id → expire_time），heartbeat 定期清理过期
        self._processed_transitions: dict[str, float] = {}

    def snapshot(self) -> LifeStateSnapshot:
        """同步方法，返回不可变快照。asyncio 单线程模型保证无并发修改。"""
        s = self._state
        return LifeStateSnapshot(
            sleep_state=s.sleep_state,
            current_activity=s.current_activity,
            prev_activity=s.prev_activity,
            activity_since=s.activity_since,
            last_transition_processed_at=s.last_transition_processed_at,
            schedule_generated_date=s.schedule_generated_date,
            today_schedule=tuple(s.today_schedule),
            recent_events=tuple(s.recent_events),
        )

    async def transition_activity(self, new_activity: ActivityType, transition_id: str) -> bool:
        """
        唯一的 activity 写入入口。返回 False 表示 transition_id 已处理（幂等）。
        仅修改状态，不触发副作用——副作用由 orchestrator dispatch。
        内部不调用任何其他 async 方法，避免 asyncio.Lock 死锁。
        """
        async with self._lock:
            now = time.time()
            # 清理过期 transition_id（24小时TTL）
            self._processed_transitions = {
                k: v for k, v in self._processed_transitions.items() if v > now
            }
            if transition_id in self._processed_transitions:
                return False
            self._processed_transitions[transition_id] = now + 86400  # 24h TTL

            prev = self._state.current_activity
            self._state.prev_activity = prev
            self._state.current_activity = new_activity
            self._state.activity_since = datetime.now(tz=timezone.utc)
            self._state.last_transition_processed_at = self._state.activity_since
            # sleep_state 派生（纯函数调用，无 await）
            self._state.sleep_state = sleep.derive_sleep_state(
                new_activity, self._state.activity_since, prev, self._state.activity_since, config
            )
            return True

    async def set_schedule(self, items: list[ScheduleItem], is_repair: bool = False) -> None:
        """is_repair=True 时标记为 synthetic，proactive 系统不响应。"""
        async with self._lock:
            self._state.today_schedule = list(items)
            self._state.schedule_is_repair = is_repair

    async def append_event(self, event: RecentEvent) -> None:
        """追加事件，自动 TTL prune 和最大条数限制。"""
        async with self._lock:
            now_utc = datetime.now(tz=timezone.utc)
            # 清理过期
            self._state.recent_events = [
                e for e in self._state.recent_events
                if (now_utc - e.timestamp).total_seconds() < e.ttl_seconds
            ]
            self._state.recent_events.append(event)
            # 超上限移除最旧
            if len(self._state.recent_events) > self._config.max_recent_events:
                self._state.recent_events = self._state.recent_events[-self._config.max_recent_events:]

    async def restore(self, persisted: dict) -> None:
        """从 DB 恢复状态，同时从 DB 恢复 _processed_transitions（重启幂等）。"""
        async with self._lock:
            # 恢复 LifeState 字段
            ...
            # 恢复 _processed_transitions（从 processed_transition 表加载未过期记录）
            # 由调用方（orchestrator._recovery_check）负责传入

    async def restore_processed_transitions(self, transitions: dict[str, float]) -> None:
        async with self._lock:
            self._processed_transitions.update(transitions)
```

**内部 LifeState（私有，含所有必要字段）：**
```python
@dataclass
class LifeState:
    current_activity: ActivityType = ActivityType.OTHER
    prev_activity: ActivityType = ActivityType.OTHER          # 用于 WAKING 判断
    activity_since: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    last_transition_processed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    sleep_state: SleepState = SleepState.AWAKE               # 派生字段
    today_schedule: list[ScheduleItem] = field(default_factory=list)
    schedule_generated_date: str = ""                         # 本地时区日期
    schedule_is_repair: bool = False
    recent_events: list[RecentEvent] = field(default_factory=list)
```

**RecentEvent（frozen）：**
```python
@dataclass(frozen=True)
class RecentEvent:
    event_type: str          # "schedule_transition" / "proactive_trigger" 等
    description: str
    timestamp: datetime      # timezone-aware UTC
    ttl_seconds: int = 3600
```

**睡眠状态枚举（4个，派生状态）：**
```python
class SleepState(Enum):
    AWAKE = "awake"
    SLEEPY = "sleepy"       # activity=SLEEPING 但未达 sleepy_duration
    SLEEPING = "sleeping"   # 困倦持续超过 sleepy_duration
    WAKING = "waking"       # 从 SLEEPING 切出后的过渡期（依赖 prev_activity）
```

**活动类型枚举（唯一真相源，SleepState 完全派生自它）：**
```python
class ActivityType(Enum):
    SLEEPING = "sleeping"
    EATING = "eating"
    STUDYING = "studying"
    EXERCISING = "exercising"
    LEISURE = "leisure"
    WORKING = "working"
    OTHER = "other"
```

### 4.2 数据库（core/database.py）

统一 SQLite，WAL 模式，**读写分离双连接**，single writer queue：

```python
class Database:
    """
    写连接（_write_conn）：writer_loop 独占，通过 asyncio.Queue 串行化所有写操作。
    读连接（_read_conn）：所有读操作直接使用，WAL 模式下读写互不阻塞。
    checkpoint 通过 writer queue 执行，确保在事务间隙运行。
    """
    async def start(self):
        self._write_conn = await aiosqlite.connect(self._path)
        self._read_conn = await aiosqlite.connect(self._path)
        for conn in (self._write_conn, self._read_conn):
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self):
        """单一 writer task。CancelledError 时正确 rollback 并 drain 队列。"""
        try:
            while True:
                op = await self._write_queue.get()
                try:
                    await self._write_conn.execute("BEGIN")
                    await op(self._write_conn)
                    await self._write_conn.commit()
                except asyncio.CancelledError:
                    await self._write_conn.rollback()
                    raise
                except Exception as e:
                    logger.error("DB write error: %s", e, exc_info=True)
                    try:
                        await self._write_conn.rollback()
                    except Exception:
                        logger.error("DB rollback failed, connection may be corrupt")
                finally:
                    self._write_queue.task_done()
        except asyncio.CancelledError:
            pass  # 正常退出

    async def stop(self):
        """on_unload 时调用：drain queue → cancel writer → FULL checkpoint → 关闭连接。"""
        await self._write_queue.join()          # 等待队列排空
        self._writer_task.cancel()
        await asyncio.gather(self._writer_task, return_exceptions=True)
        await self._write_conn.execute("PRAGMA wal_checkpoint(FULL);")
        await self._write_conn.close()
        await self._read_conn.close()

    async def enqueue_write(self, op: Callable) -> asyncio.Future:
        """提交写操作到队列，返回 Future 供调用方选择性 await。"""
        fut = asyncio.get_event_loop().create_future()
        async def wrapped(conn):
            await op(conn)
            fut.set_result(True)
        await self._write_queue.put(wrapped)
        return fut

    async def maybe_checkpoint(self):
        """PASSIVE checkpoint 通过 writer queue 执行，确保在事务间隙运行。"""
        await self.enqueue_write(lambda conn: conn.execute("PRAGMA wal_checkpoint(PASSIVE);"))
```

**表结构（新增 `person_stream` 和 `budget_counter`）：**
```sql
CREATE TABLE life_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE person_impression (
    person_id TEXT PRIMARY KEY,
    person_name TEXT NOT NULL,
    traits TEXT NOT NULL DEFAULT '[]',
    affinity REAL NOT NULL DEFAULT 0.5,
    proactive_score REAL NOT NULL DEFAULT 0.0,
    proactive_cooldown_until REAL,
    last_interaction REAL,
    last_impression_update REAL,
    dirty INTEGER NOT NULL DEFAULT 0
);

-- person_id 与 stream_id 的多对多映射，解决"查谁的消息/发给哪个群"问题
CREATE TABLE person_stream (
    person_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    last_seen REAL NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (person_id, stream_id)
);

CREATE TABLE proactive_nonce (
    nonce TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE processed_transition (
    transition_id TEXT PRIMARY KEY,
    processed_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

-- budget daily 计数持久化（重启后恢复，防 daily_limit 失效）
CREATE TABLE budget_counter (
    key TEXT PRIMARY KEY,       -- "llm.schedule", "proactive.trigger" 等
    count INTEGER NOT NULL DEFAULT 0,
    window_start TEXT NOT NULL, -- ISO date（daily）或 ISO hour（hourly）
    updated_at REAL NOT NULL
);

-- proactive guard 状态持久化（重启后恢复限流状态）
CREATE TABLE proactive_guard_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,        -- JSON
    updated_at REAL NOT NULL
);
```

**WAL checkpoint 策略：**
- 定期 PASSIVE：通过 writer queue 执行（`maybe_checkpoint()`），默认每 60 分钟
- `on_unload` FULL：`stop()` 中 drain queue 后执行
- DB 文件大小超过 `db.max_size_mb`（默认 50MB）时告警日志
- 过期记录清理：heartbeat 中批量清理 `proactive_nonce` 和 `processed_transition` 表

### 4.3 调度编排（core/orchestrator.py）

**事件驱动 + transition timer，background task registry 统一管理所有后台任务：**

```python
class BackgroundTaskRegistry:
    """统一管理 create_task，done callback 自动捕获异常，cancel_all 时统一清理。"""
    def create_task(self, coro, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        task.add_done_callback(self._on_done)
        self._tasks.add(task)
        return task

    def _on_done(self, task: asyncio.Task):
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background task '%s' raised: %s", task.get_name(), exc, exc_info=exc)

    async def cancel_all(self):
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

class Orchestrator:
    async def start(self):
        await self._db.start()
        await self._recovery_check()
        self._registry.create_task(self._run(), name="orchestrator.main")
        self._registry.create_task(self._heartbeat(), name="orchestrator.heartbeat")

    async def stop(self):
        # 正确顺序：先停止产生新写操作，再 drain queue，再 checkpoint
        await self._registry.cancel_all()   # cancel _run 和 _heartbeat（停止新写操作）
        await self._db.stop()               # drain write queue → FULL checkpoint → 关闭连接

    async def _run(self):
        """主循环：精确 sleep_until，醒来后校验漂移，处理 missed transitions。"""
        while True:
            try:
                snap = self._manager.snapshot()
                now = now_utc()
                next_time, next_activity = schedule.calc_next_transition(snap, now)
                sleep_secs = max((next_time - now).total_seconds(), 0)
                await asyncio.sleep(sleep_secs)

                # 醒来后重新校验（防系统休眠漂移）
                actual_now = now_utc()
                snap = self._manager.snapshot()

                # 处理 missed transitions（以 last_transition_processed_at 为起点）
                missed = schedule.get_missed_transitions(snap, actual_now)
                for missed_activity, missed_time in missed:
                    tid = f"transition:{missed_time.isoformat()}:{missed_activity.value}"
                    await self._on_transition(missed_activity, tid, is_missed=True)

                # 处理当前 transition
                actual_activity = schedule.get_current_activity(snap, actual_now)
                # 如果与 missed 最后一个相同则跳过（幂等保护处理）
                tid = f"transition:{actual_now.isoformat()}:{actual_activity.value}"
                await self._on_transition(actual_activity, tid)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                # 单次迭代异常不终止主循环，短暂退避后继续
                logger.error("Orchestrator _run error: %s", e, exc_info=True)
                await asyncio.sleep(10)

    async def _on_transition(self, new_activity: ActivityType, transition_id: str, is_missed: bool = False):
        old_snap = self._manager.snapshot()
        ok = await self._manager.transition_activity(new_activity, transition_id)
        if not ok:
            return  # 幂等跳过

        # 副作用链：各步骤独立 try/except，单步失败不影响后续
        try:
            await self._apply_frequency(new_activity)
        except Exception as e:
            logger.error("apply_frequency failed: %s", e)

        try:
            if not is_missed and not old_snap.schedule_is_repair:
                await self._proactive.on_transition(
                    old_snap.current_activity, new_activity, transition_id
                )
        except Exception as e:
            logger.error("proactive.on_transition failed: %s", e)

        # DB 持久化必须执行（不 try/except，失败会被 registry done callback 记录）
        await self._db.enqueue_write(self._persist_state)

        # 追加 recent_event
        await self._manager.append_event(RecentEvent(
            event_type="schedule_transition",
            description=f"{old_snap.current_activity.value} → {new_activity.value}",
            timestamp=now_utc(),
        ))

    async def _apply_frequency(self, new_activity: ActivityType):
        """遍历所有已知 stream，批量调用 set_adjust。SDK 无全局模式。"""
        factor = self._config.frequency.get(new_activity.value, 0.0)
        for stream_id in self._stream_registry.get_all():
            await self._ctx.frequency.set_adjust(stream_id, factor)

    async def _heartbeat(self):
        """各子任务用 create_task 隔离，互不阻塞。"""
        while True:
            try:
                await asyncio.sleep(self._config.heartbeat_seconds)
                # 各子任务后台执行，不阻塞 heartbeat 主循环
                self._registry.create_task(
                    self._relation.flush_dirty_impressions(),
                    name="heartbeat.flush_impressions"
                )
                self._registry.create_task(
                    self._proactive.check_score_trigger(),
                    name="heartbeat.score_trigger"
                )
                self._registry.create_task(
                    self._db.maybe_checkpoint(),
                    name="heartbeat.checkpoint"
                )
                self._registry.create_task(
                    self._cleanup_expired_records(),
                    name="heartbeat.cleanup"
                )
                self._registry.create_task(
                    self._budget.flush_daily_counters(),
                    name="heartbeat.budget_flush"
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Orchestrator _heartbeat error: %s", e, exc_info=True)
                await asyncio.sleep(30)

    async def _recovery_check(self):
        """
        启动时恢复：加载持久化状态 → 恢复幂等缓存 → 检查跨天 → repair missed transitions。
        recovery_check 完成前 hook 组件已注册但 orchestrator 未启动，行为安全。
        """
        # 1. 从 DB 恢复 LifeState
        persisted_state = await self._db.load_state()
        if persisted_state:
            await self._manager.restore(persisted_state)

        # 2. 从 DB 恢复 _processed_transitions（重启幂等）
        unexpired = await self._db.load_processed_transitions_unexpired()
        await self._manager.restore_processed_transitions(unexpired)

        # 3. 从 DB 恢复 proactive guard 状态（daily_count、cooldown 等）
        guard_state = await self._db.load_proactive_guard_state()
        if guard_state:
            self._proactive.restore_guard(guard_state)

        # 4. 从 DB 恢复 budget daily 计数
        await self._budget.restore_from_db()

        # 5. 检查跨天，需重新生成日程
        local_today = local_date_str(self._config.timezone)
        if self._manager.snapshot().schedule_generated_date != local_today:
            await self._schedule.generate(local_today, is_recovery=True)

        # 6. repair missed transitions（不触发 proactive）
        snap = self._manager.snapshot()
        missed = schedule.get_missed_transitions(snap, now_utc())
        for missed_activity, missed_time in missed:
            tid = f"transition:{missed_time.isoformat()}:{missed_activity.value}"
            await self._on_transition(missed_activity, tid, is_missed=True)
```

**reload_config policy（配置热更新语义）：**

| 配置项 | 生效时机 |
|--------|---------|
| `frequency.*` | immediate（立即对所有 stream 调用一次 `set_adjust`） |
| `proactive.*`（限流参数） | immediate |
| `prompts.*` | immediate（下次 LLM 调用生效） |
| `llm.*`（timeout/retry） | immediate |
| `relation.min_update_interval` | immediate |
| `sleep.*`（过渡时长） | next-transition |
| `schedule.*`（骨架时间） | next-day（次日日程生成时生效） |

### 4.4 日程系统（systems/schedule.py）

**数据结构（内部统一 timezone-aware UTC `datetime`，不用 `datetime.time`）：**

`datetime.time` 无法正确携带 timezone 语义，config 中的本地时间在进入系统时立即转换为当天对应的 UTC `datetime`。

```python
@dataclass(frozen=True)
class ScheduleItem:
    start_time: datetime    # timezone-aware UTC datetime（不是 time 对象）
    end_time: datetime      # timezone-aware UTC datetime
    activity: ActivityType
    description: str
    is_skeleton: bool = False
```

**生成流程：**
1. 从 config 读取骨架时间（本地时间字符串）→ `time_helper.local_time_to_utc_datetime(today, time_str, tz)` 转为 UTC datetime
2. 构建骨架 items（`is_skeleton=True`），跨天骨架（如 23:00~07:00 睡觉）拆为两段：`[23:00 today, 00:00 tomorrow)` 和 `[00:00 tomorrow, 07:00 tomorrow)`
3. 计算空闲时间段 → 调用 `llm_helper.generate_json(prompt, schema, budget_key="schedule")`
4. schema validate：overlap check、empty gap repair、invalid range repair（repair 最多 2 次，超过则 fallback）
5. 失败 → fallback 默认模板（骨架 + 分时段 STUDYING/WORKING/LEISURE 填充，不全用 LEISURE）
6. `manager.set_schedule(items, is_repair=False)`

**关键函数：**
```python
def calc_next_transition(snap: LifeStateSnapshot, now: datetime) -> tuple[datetime, ActivityType]:
    """返回 (下一切换时间 UTC datetime, 切换后活动)。基于 snap.today_schedule 计算。"""
    ...

def get_current_activity(snap: LifeStateSnapshot, now: datetime) -> ActivityType:
    """返回 now 对应的当前活动。"""
    ...

def get_missed_transitions(snap: LifeStateSnapshot, now: datetime) -> list[tuple[ActivityType, datetime]]:
    """
    从 snap.last_transition_processed_at 到 now 之间的所有切换点，按时间排序。
    依赖 LifeState 中的 last_transition_processed_at 字段（非 activity_since）。
    """
    ...
```

### 4.5 睡眠系统（systems/sleep.py）

纯函数模块，不持有状态，不 import 其他 system，不含 `await`：

```python
def derive_sleep_state(
    activity: ActivityType,
    activity_since: datetime,
    prev_activity: ActivityType,    # 由 manager 传入，用于判断 WAKING
    now: datetime,
    config: SleepConfig,
) -> SleepState:
    """纯函数：从 activity + prev_activity + 持续时长派生 SleepState。"""
    if activity != ActivityType.SLEEPING:
        if prev_activity == ActivityType.SLEEPING:
            elapsed = (now - activity_since).total_seconds() / 60
            if elapsed < config.waking_duration_minutes:
                return SleepState.WAKING
        return SleepState.AWAKE
    elapsed = (now - activity_since).total_seconds() / 60
    if elapsed < config.sleepy_duration_minutes:
        return SleepState.SLEEPY
    return SleepState.SLEEPING
```

### 4.6 频率控制

`frequency.set_adjust(chat_id, value)` 需要 `chat_id`，SDK 无全局模式。通过 `StreamRegistry` 维护已知 stream 列表，每次 transition 时批量调用：

```python
class StreamRegistry:
    """维护所有曾出现过消息的 stream_id 列表。由 Hook 在收到消息时更新。"""
    _streams: set[str] = set()

    def register(self, stream_id: str) -> None:
        self._streams.add(stream_id)

    def get_all(self) -> list[str]:
        return list(self._streams)
```

`on_config_update()` 时立即对所有已知 stream 调用一次 `set_adjust()` 使新配置生效。

| 活动类型 | 频率调整值（默认） |
|---------|-----------------|
| SLEEPING | -1.0 |
| EXERCISING | -0.6 |
| STUDYING / WORKING | -0.4 |
| EATING | -0.2 |
| LEISURE / OTHER | 0.0 |

### 4.7 关系网（systems/relation.py）

**person_id ↔ stream_id 映射通过 `person_stream` 表解决：**

Hook 在 `_mark_interaction` 中同时更新 `person_stream` 表（`person_id, stream_id, last_seen, message_count`）。`flush_dirty_impressions` 通过此表找到该 person 最活跃的 stream 来拉取历史消息。

**DirtyQueue（`(person_id, stream_id)` 元组去重）：**
```python
class DirtyQueue:
    _queue: dict[tuple[str, str], float]  # (person_id, stream_id) → marked_at
    max_size: int = 500
    ttl_seconds: int = 7200

    def mark(self, person_id: str, stream_id: str) -> None:
        key = (person_id, stream_id)
        if key in self._queue:
            return
        if len(self._queue) >= self.max_size:
            oldest = min(self._queue, key=self._queue.get)
            del self._queue[oldest]
        self._queue[key] = time.time()

    def pop_batch(self, limit: int) -> list[tuple[str, str]]:
        now = time.time()
        expired = [k for k, t in self._queue.items() if now - t > self.ttl_seconds]
        for k in expired:
            del self._queue[k]
        sorted_keys = sorted(self._queue, key=self._queue.get)[:limit]
        for k in sorted_keys:
            del self._queue[k]
        return sorted_keys
```

**批量 AI 印象更新（冷却中的记录放回队列，不丢弃）：**
```python
async def flush_dirty_impressions(self):
    pairs = self._dirty_queue.pop_batch(limit=self._budget.dirty_flush_per_heartbeat)
    for person_id, stream_id in pairs:
        imp = await self._db.get_impression(person_id)
        now = now_utc()
        if imp and (now - imp.last_impression_update).total_seconds() < self._config.min_update_interval:
            self._dirty_queue.mark(person_id, stream_id)  # 放回，不丢弃
            continue
        if not self._budget.can_llm_call("impression"):
            self._dirty_queue.mark(person_id, stream_id)  # 放回
            break
        recent_msgs = await self._ctx.message.get_recent(chat_id=stream_id, limit=20)
        new_imp = await llm_helper.generate_json(
            self._ctx, prompt, schema, budget_key="impression", budget=self._budget
        )
        if new_imp is None:
            continue  # LLM 失败跳过，不放回（避免反复调用失败的 LLM）
        new_imp["proactive_score"] = self._update_proactive_score(imp, new_imp)
        await self._db.save_impression(new_imp)
```

**proactive_score 完整生命周期（增长 + 衰减）：**
```python
def _update_proactive_score(old_imp: dict | None, new_imp: dict) -> float:
    score = old_imp["proactive_score"] if old_imp else 0.0

    # 正向增长（在印象更新时基于 last_interaction 频率计算）
    if new_imp.get("had_recent_interaction"):       # 最近有互动
        score = min(1.0, score + 0.15)
    if new_imp.get("user_replied_to_proactive"):    # 用户回复了主动消息
        score = min(1.0, score + 0.2)
    if new_imp.get("affinity", 0.5) > 0.7:         # 高好感度有 bonus
        score = min(1.0, score + 0.05)

    # 负向衰减
    days_silent = new_imp.get("days_since_interaction", 0)
    decay = min(days_silent * 0.05, 0.3)
    score = max(0.0, score - decay)

    # 连续主动失败时降低
    if new_imp.get("in_cooldown"):
        score = max(0.0, score - 0.1)

    return score
```

### 4.8 主动行为（systems/proactive.py）

**ProactiveGuard（含持久化恢复）：**
```python
@dataclass
class ProactiveGuard:
    global_cooldown_until: datetime
    per_group_cooldown: dict[str, datetime]     # 定期清理过期 entry
    daily_count: int
    daily_date: str                             # 记录 daily_count 对应的本地日期
    daily_limit: int
    last_trigger_time: datetime | None
    consecutive_count: int
    consecutive_reset_after_minutes: int        # 超过此时间无触发则重置 consecutive_count
    _lock: asyncio.Lock
    _nonce_registry: dict[str, float]           # nonce → expire_time，有 TTL 清理
```

**guard 持久化与恢复（重启后不丢失限流状态）：**
- `_update_guard_after_trigger()` 后异步持久化到 `proactive_guard_state` 表
- `restore_guard(state)` 在 `recovery_check` 中从 DB 恢复
- `daily_count` 恢复时检查 `daily_date`，如果不是今天则重置为 0

**per_group_cooldown 定期清理：**
```python
def _cleanup_guard(self):
    now = now_utc()
    expired = [k for k, v in self._guard.per_group_cooldown.items() if v < now]
    for k in expired:
        del self._guard.per_group_cooldown[k]
```

**consecutive_count 重置条件：**
1. 用户回复了主动消息（由 `_mark_interaction` 检测后通知）
2. `last_trigger_time` 距现在超过 `consecutive_reset_after_minutes`（config，默认 120 分钟）
3. 跨天重置

**触发流程（完整幂等保护，缩小锁持有范围）：**
```python
async def trigger(self, stream_id: str, intent: str, source: str, transition_id: str | None = None):
    # Phase 1（持锁）：检查 + nonce 预注册
    async with self._guard._lock:
        nonce = self._make_nonce(stream_id, intent, transition_id)
        now = time.time()
        # 清理过期 nonce
        self._guard._nonce_registry = {k: v for k, v in self._guard._nonce_registry.items() if v > now}

        if nonce in self._guard._nonce_registry:
            return
        if await self._db.nonce_exists(nonce):
            return
        if not self._check_guard_sync(stream_id):  # 同步检查，无 await
            return
        if transition_id and self._is_in_debounce_window(transition_id):
            return

        # 提前注册 nonce（释放锁前）
        self._guard._nonce_registry[nonce] = now + 3600
        await self._db.register_nonce(nonce, stream_id, ttl=3600)
    # 锁释放

    # Phase 2（无锁）：LLM 生成 intent（耗时操作）
    final_intent = await self._build_intent(intent)
    if final_intent is None:
        # 回滚 nonce
        await self._db.delete_nonce(nonce)
        self._guard._nonce_registry.pop(nonce, None)
        return

    # Phase 3：触发 + 回滚保护
    try:
        await self._ctx.maisaka.proactive.trigger(
            stream_id=stream_id,
            intent=final_intent,
            reason=source,
            metadata={"nonce": nonce, "source": "life_simulation"},
        )
    except Exception as e:
        logger.error("maisaka.proactive.trigger failed: %s", e)
        # 回滚：删除 nonce，不更新 guard（不消耗 daily quota）
        await self._db.delete_nonce(nonce)
        self._guard._nonce_registry.pop(nonce, None)
        return

    # Phase 4（持锁）：更新 guard 状态并持久化
    async with self._guard._lock:
        self._update_guard_after_trigger(stream_id)
    await self._db.enqueue_write(self._persist_guard_state)
```

**check_score_trigger 的目标群选择：**
```python
async def check_score_trigger(self):
    high_score_persons = await self._db.get_persons_above_score(self._config.score_threshold)
    for person in high_score_persons:
        # 从 person_stream 表找最近活跃的 stream
        best_stream = await self._db.get_best_stream_for_person(person.person_id)
        if best_stream is None:
            continue
        intent = f"想跟{person.person_name}聊聊"
        await self.trigger(
            stream_id=best_stream.stream_id,
            intent=intent,
            source="heartbeat_score",
        )
```

### 4.9 Hook 组件（components/hooks.py）

使用正确的 SDK Hook 名称，blocking hook 极简：

```python
from maibot_sdk import MaiBotPlugin, HookHandler
from maibot_sdk.types import HookMode, HookOrder, ErrorPolicy

class LifeSimHooks:
    """hooks.py 中的 Handler 方法注入 plugin 实例访问 _manager 和 _registry。"""

    @HookHandler(
        "chat.receive.before_process",
        name="life_sim_sleep_gate",
        description="睡眠期间拦截消息",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def handle_sleep_gate(self, **kwargs):
        snap = self._plugin._manager.snapshot()
        if snap.sleep_state == SleepState.SLEEPING:
            return {"action": "abort"}   # SDK BLOCKING 模式的拦截方式
        # 更新 stream_registry（全局 set_adjust 需要 stream 列表）
        stream_id = kwargs.get("message", {}).get("stream_id")
        if stream_id:
            self._plugin._stream_registry.register(stream_id)
        return {"action": "continue", "modified_kwargs": kwargs}

    @HookHandler(
        "chat.receive.after_process",
        name="life_sim_interaction_observer",
        description="观察消息，更新关系网 dirty 标记",
        mode=HookMode.OBSERVE,
        order=HookOrder.NORMAL,
    )
    async def observe_interaction(self, **kwargs):
        message = kwargs.get("message", {})
        person_id = message.get("person_id") or message.get("user_info", {}).get("person_id")
        stream_id = message.get("stream_id")
        if person_id and stream_id:
            # OBSERVE 模式：后台任务，通过 registry 管理异常
            self._plugin._registry.create_task(
                self._plugin._relation.mark_interaction(person_id, stream_id, message),
                name=f"mark_interaction:{message.get('message_id', 'unknown')}"
            )
        # OBSERVE 模式返回值被忽略
```

### 4.10 Tool 组件（components/tools.py）

返回摘要态自然语言 hint，`status_hint` 使用硬编码模板映射（非 LLM 生成，避免 Tool 调用触发 LLM 嵌套）：

```python
_ACTIVITY_SLEEP_HINTS: dict[tuple[ActivityType, SleepState], str] = {
    (ActivityType.SLEEPING, SleepState.SLEEPY):   "正准备睡觉，有点困了",
    (ActivityType.SLEEPING, SleepState.SLEEPING): "正在睡觉",
    (ActivityType.SLEEPING, SleepState.WAKING):   "刚睡醒，还有点迷糊",
    (ActivityType.EATING,   SleepState.AWAKE):    "正在吃饭",
    (ActivityType.STUDYING, SleepState.AWAKE):    "正在学习，比较专注",
    (ActivityType.EXERCISING, SleepState.AWAKE):  "正在运动",
    (ActivityType.WORKING,  SleepState.AWAKE):    "正在忙",
    (ActivityType.LEISURE,  SleepState.AWAKE):    "在休闲放松",
    (ActivityType.OTHER,    SleepState.AWAKE):    "在做一些事情",
}

# get_life_state 返回
{
    "status_hint": "正在学习，比较专注",  # 硬编码模板，可附加 description 使其更自然
    "current_activity": "studying",
    "sleep_state": "awake",
    "can_chat": True
}

# get_today_schedule 返回（upcoming 最多 3 条，4 小时内）
{
    "current_item": {"time": "14:00-16:00", "description": "写代码"},
    "upcoming": [{"time": "18:00-18:30", "description": "吃晚饭"}]
}

# get_person_impression（person_name 参数，内部通过 person_api 解析 person_id）
{
    "traits": ["热情", "话多"],
    "affinity_hint": "印象不错，聊得比较多"
}
```

`get_person_impression` 接受 `person_name: str`，内部调用 `ctx.person.get_id_by_name(person_name)` 解析 person_id，对 LLM 更友好。

### 4.11 插件 API（components/apis.py）

使用显式 DTO，`dataclasses.asdict()` 替代 `.__dict__`，versioned schema 有实际路由：

```python
@dataclass
class LifeStateDTO_v1:
    schema_version: str = "v1"
    sleep_state: str = ""
    current_activity: str = ""
    schedule_generated_date: str = ""

_DTO_BUILDERS = {
    "v1": lambda snap: LifeStateDTO_v1(
        sleep_state=snap.sleep_state.value,
        current_activity=snap.current_activity.value,
        schedule_generated_date=snap.schedule_generated_date,
    ),
}

@API("life_sim.get_current_state")
async def get_current_state(self, schema_version: str = "v1", **kwargs) -> dict:
    snap = self._plugin._manager.snapshot()
    builder = _DTO_BUILDERS.get(schema_version)
    if builder is None:
        raise ValueError(f"Unknown schema_version: {schema_version}")
    return dataclasses.asdict(builder(snap))

@API("life_sim.get_schedule")
async def get_schedule(self, **kwargs) -> list[dict]:
    snap = self._plugin._manager.snapshot()
    return [
        {
            "start": to_local(item.start_time, self._config.timezone).strftime("%H:%M"),
            "end": to_local(item.end_time, self._config.timezone).strftime("%H:%M"),
            "activity": item.activity.value,
            "description": item.description,
        }
        for item in snap.today_schedule
    ]

@API("life_sim.get_impression")
async def get_impression(self, person_id: str, **kwargs) -> dict | None:
    imp = await self._plugin._db.get_impression(person_id)
    if imp is None:
        return None
    return {"traits": imp["traits"], "affinity_hint": _affinity_to_hint(imp["affinity"])}
    # _affinity_to_hint 与 tools.py 共享 utils/hint_helper.py 中的实现

@API("life_sim.get_frequency_factor")
async def get_frequency_factor(self, **kwargs) -> float:
    snap = self._plugin._manager.snapshot()
    return self._config.frequency.get(snap.current_activity.value, 0.0)

@API("life_sim.get_sleep_state")
async def get_sleep_state(self, **kwargs) -> str:
    return self._plugin._manager.snapshot().sleep_state.value
```

### 4.12 资源预算（core/budget.py）

**daily 计数持久化，重启后从 `budget_counter` 表恢复：**

```python
class ResourceBudget:
    """
    per-hour 预算使用滑动窗口（内存，重启丢失可接受）。
    per-day 预算持久化到 DB（重启后恢复，防 daily_limit 失效）。
    proactive daily 预算与 ProactiveGuard.daily_count 统一由 Guard 管理，Budget 不重复维护。
    """
    def can_llm_call(self, call_type: str) -> bool:
        """per-hour 滑动窗口检查。"""
        ...

    def get_flush_limit(self) -> int:
        """返回本次 heartbeat 允许处理的 dirty impression 条数。"""
        return self._config.dirty_flush_per_heartbeat

    def record_llm(self, call_type: str) -> None:
        """记录一次 LLM 调用（滑动窗口 + daily 计数）。"""
        ...

    async def restore_from_db(self) -> None:
        """从 DB 恢复 daily 计数，重启后调用。"""
        ...

    async def flush_daily_counters(self) -> None:
        """heartbeat 中调用，持久化当前 daily 计数到 DB。"""
        ...
```

**注意：proactive daily_limit 统一由 `ProactiveGuard.daily_count` 管理，`ResourceBudget` 不再单独维护 `can_proactive()`，避免双重计数。**

### 4.13 LLM 辅助（utils/llm_helper.py）

```python
async def generate_json(
    ctx,
    prompt: list[dict],
    schema: dict,
    budget_key: str,
    budget: ResourceBudget,
    timeout: float = 30.0,
    max_retries: int = 2,
    max_repair_attempts: int = 2,
) -> dict | None:
    """返回 None 表示彻底失败，调用方必须处理 fallback。"""
    if not budget.can_llm_call(budget_key):
        logger.warning("LLM budget exceeded for %s", budget_key)
        return None
    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.wait_for(
                ctx.llm.generate(prompt=prompt),
                timeout=timeout,
            )
            if not result.get("success"):
                continue
            data = _parse_json(result["response"])
            if data is None:
                continue
            repaired = _validate_and_repair(data, schema, max_repair_attempts)
            if repaired is not None:
                budget.record_llm(budget_key)
                return repaired
        except asyncio.TimeoutError:
            logger.warning("LLM timeout attempt %d/%d for %s", attempt + 1, max_retries + 1, budget_key)
        except asyncio.CancelledError:
            raise  # 不吞 CancelledError
        except Exception as e:
            logger.error("LLM error: %s", e, exc_info=True)
        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)
    return None
```

### 4.14 时间工具（utils/time_helper.py）

```python
def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)

def to_local(dt: datetime, tz_name: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz_name))

def local_time_to_utc_datetime(date: date, time_str: str, tz_name: str) -> datetime:
    """将 config 中的本地时间字符串 'HH:MM' + 日期转为 UTC datetime。"""
    local_dt = datetime.combine(date, time.fromisoformat(time_str), tzinfo=ZoneInfo(tz_name))
    return local_dt.astimezone(timezone.utc)

def local_date_str(tz_name: str) -> str:
    """返回本地时区的今天日期字符串 'YYYY-MM-DD'，用于 schedule_generated_date 比较。"""
    return datetime.now(tz=ZoneInfo(tz_name)).date().isoformat()

def is_in_quiet_hours(now: datetime, start_str: str, end_str: str, tz_name: str) -> bool:
    """支持跨天 quiet hours（如 23:00~07:00）。now 为 UTC datetime。"""
    local_now = to_local(now, tz_name).time()
    start = time.fromisoformat(start_str)
    end = time.fromisoformat(end_str)
    if start <= end:
        return start <= local_now < end
    else:  # 跨天
        return local_now >= start or local_now < end
```

---

## 5. 配置设计（config.toml）

```toml
[plugin]
enabled = true
timezone = "Asia/Shanghai"

[schedule]
sleep_start = "23:00"
sleep_end = "07:00"
breakfast_start = "07:30"
breakfast_end = "08:00"
lunch_start = "12:00"
lunch_end = "12:30"
dinner_start = "18:00"
dinner_end = "18:30"

[sleep]
sleepy_duration_minutes = 30
waking_duration_minutes = 15

[frequency]
# activity transition 时对所有已知 stream 调用 set_adjust 的值（-1.0~1.0）
sleeping = -1.0
exercising = -0.6
studying = -0.4
working = -0.4
eating = -0.2
leisure = 0.0
other = 0.0

[relation]
min_update_interval_minutes = 30
dirty_queue_max_size = 500
dirty_queue_ttl_seconds = 7200

[proactive]
enabled = true
schedule_transition_probability = 0.4
waking_probability_factor = 0.3
global_cooldown_minutes = 30
per_group_cooldown_minutes = 60
quiet_hours_start = "23:00"
quiet_hours_end = "07:00"
daily_limit = 5
max_consecutive = 2
consecutive_reset_after_minutes = 120
score_threshold = 0.7
debounce_seconds = 5

[llm]
timeout_seconds = 30
max_retries = 2
max_repair_attempts = 2

[budget]
llm_schedule_per_day = 3
llm_impression_per_hour = 50
llm_proactive_intent_per_hour = 20
dirty_flush_per_heartbeat = 10

[db]
checkpoint_interval_minutes = 60
max_size_mb = 50

[heartbeat]
interval_seconds = 600

[tool]
upcoming_count = 3            # get_today_schedule 返回的 upcoming 条数上限
upcoming_hours_ahead = 4      # 只返回 N 小时内的 upcoming

[prompts]
# 留空则使用代码内置的默认提示词模板
# 变量：{personality}、{date}、{skeleton}
schedule_generation = ""
# 变量：{personality}、{person_name}、{recent_messages}、{old_impression}
impression_update = ""
# 变量：{state}、{activity}、{description}
proactive_intent = ""
```

---

## 6. 数据流

### 6.1 消息到来时（Hook）

```
消息进入
→ @HookHandler("chat.receive.before_process", BLOCKING, EARLY)
    → snapshot() 只读（同步，asyncio 单线程安全）
    → sleep_state == SLEEPING → {"action": "abort"}（拦截）
    → stream_registry.register(stream_id)（同步，无 await）
    → {"action": "continue"}（放行）

→ @HookHandler("chat.receive.after_process", OBSERVE)
    → registry.create_task(relation.mark_interaction)  ← 后台，异常由 done callback 捕获
    （OBSERVE 模式返回值被忽略，不阻塞主流程）
```

### 6.2 Orchestrator 主循环（事件驱动）

```
orchestrator._run():
    loop（内部 try/except，单次异常不终止循环）:
        snap = manager.snapshot()
        next_time, next_activity = calc_next_transition(snap, now_utc())
        await asyncio.sleep(seconds)
        actual_now = now_utc()
        snap = manager.snapshot()                          ← 醒来后重新取
        missed = get_missed_transitions(snap, actual_now)  ← 以 last_transition_processed_at 为起点
        for each missed:
            _on_transition(activity, tid, is_missed=True)
        _on_transition(get_current_activity(snap, actual_now), tid)

_on_transition(activity, tid, is_missed):
    ok = manager.transition_activity(activity, tid)  ← 幂等
    if not ok: return
    try: _apply_frequency(activity)                  ← 遍历所有 stream 调用 set_adjust
    try: proactive.on_transition(...)                ← 检查触发（仅非 missed 且非 repair）
    db.enqueue_write(persist_state)                  ← 必须执行
    manager.append_event(...)
```

### 6.3 Orchestrator Heartbeat（定期，各子任务 create_task 隔离）

```
orchestrator._heartbeat():
    loop（内部 try/except）:
        await sleep(heartbeat_seconds)
        registry.create_task(relation.flush_dirty_impressions)  ← 批量更新，不阻塞
        registry.create_task(proactive.check_score_trigger)     ← score 触发
        registry.create_task(db.maybe_checkpoint)               ← WAL checkpoint
        registry.create_task(cleanup_expired_records)           ← 清理过期 nonce/transition
        registry.create_task(budget.flush_daily_counters)       ← 持久化 daily 计数
```

### 6.4 启动恢复流程

```
on_load():
    orchestrator.start():
        db.start()
        recovery_check():
            db.load_state() → manager.restore()
            db.load_processed_transitions_unexpired() → manager.restore_processed_transitions()
            db.load_proactive_guard_state() → proactive.restore_guard()
            budget.restore_from_db()
            检查 local_date_str(tz) != schedule_generated_date → schedule.generate(is_recovery=True)
            get_missed_transitions(snap, now_utc()) → _on_transition(..., is_missed=True)
        registry.create_task(_run)
        registry.create_task(_heartbeat)
```

### 6.5 关闭流程（on_unload）

```
on_unload():
    orchestrator.stop():
        registry.cancel_all()       ← 取消 _run 和 _heartbeat（停止新写操作）
        db.stop():
            write_queue.join()      ← drain 剩余写操作
            writer_task.cancel()
            FULL checkpoint
            关闭读写连接
```

### 6.6 MaiBot 生成回复时（Tool）

```
MaiBot 推理引擎
    → get_life_state() → 硬编码 hint + activity + sleep_state + can_chat
    → get_today_schedule() → 当前活动 + 最多 3 条 4 小时内 upcoming（本地时间字符串）
    → get_person_impression(person_name) → traits + affinity_hint（内部解析 person_id）
    → 综合人格 + hint → 自然回复
```

---

## 7. Manifest（_manifest.json）

```json
{
  "manifest_version": 2,
  "id": "com.lifesim.life-simulation",
  "version": "2.0.0",
  "name": "Life Simulation",
  "description": "让 MaiBot 更拟人：日程、睡眠、频率控制、关系网、主动行为",
  "capabilities": ["send_message"],
  "host_application": {
    "min_version": "1.0.0",
    "max_version": "1.99.99"
  },
  "sdk": {
    "min_version": "2.0.0",
    "max_version": "2.99.99"
  }
}
```

---

## 8. 明确排除

- 记忆系统（归 MaiBot 宿主负责）
- 天气感知
- 节日 API
- 调试命令系统（后续可补充）
- 疾病/健康系统
- 旧版社交网络亲密度数值体系
- 习惯系统

---

## 9. 关键设计决策汇总

| 问题 | 决策 |
|------|------|
| snapshot 可变对象泄漏 | ScheduleItem/RecentEvent 均为 frozen dataclass，直接 tuple() 化，无需 deep copy |
| snapshot 并发安全 | asyncio 单线程协作调度（非 GIL）保证同步代码段不被切换打断 |
| background task 管理 | BackgroundTaskRegistry：done callback 捕获异常，cancel_all 时统一清理 |
| DB 并发写冲突 | single writer queue（asyncio.Queue），读写分离双连接，WAL 模式 |
| DB 事务正确性 | 手动 BEGIN/COMMIT/ROLLBACK，CancelledError 时正确 rollback |
| on_unload 顺序 | cancel tasks → drain write queue → FULL checkpoint → 关闭连接 |
| writer_loop 异常 | 可恢复错误 log+rollback+continue，不可恢复错误 stop+通知 orchestrator |
| frequency 全局模式 | SDK 无全局模式，StreamRegistry 维护 stream 列表，transition 时批量调用 |
| 全局单状态 | 单人格全局状态模型，所有群共享，feature 而非 bug |
| timezone | 全部 UTC，展示层/config 转本地，local_date_str() 用于日程日期比较 |
| ScheduleItem 时间表示 | 内部统一 timezone-aware UTC datetime（不用 datetime.time），骨架跨天拆为两段 |
| sleep_until 漂移 | 醒来后重新取 snap，get_missed_transitions 以 last_transition_processed_at 为起点 |
| prev_activity | LifeState 新增字段，transition 时更新，derive_sleep_state 用于判断 WAKING |
| last_transition_processed_at | LifeState 新增字段，get_missed_transitions 的起点 |
| proactive 负反馈 | proactive_score 有完整增减逻辑，用户不回复 decay，用户回复加分 |
| proactive_score 增长 | 互动频率/用户回应主动消息/高 affinity → score 上升 |
| dirty 队列 | (person_id, stream_id) 元组去重 + max_size + TTL；冷却中记录放回队列不丢弃 |
| person↔stream 映射 | person_stream 表：多对多映射，flush_impressions 和 check_score_trigger 依赖此表 |
| schema validate | 严格 validator，repair 次数上限，超限直接 fallback |
| fallback 日程 | 骨架 + 分时段活动（非全 LEISURE），保证基本活动节奏 |
| orchestrator 主循环 | 内部 try/except，单次异常不终止循环，短暂退避后继续 |
| heartbeat 子任务隔离 | 各子任务 create_task 后台执行，互不阻塞 |
| orchestrator 恢复 | recovery_check 恢复 state + processed_transitions + guard + budget，再 repair missed |
| proactive 幂等 | nonce dict（TTL 清理）+ DB nonce 表 + transition_id + debounce + single-flight（分阶段锁） |
| proactive guard 持久化 | daily_count/cooldown 持久化到 DB，重启后恢复，防 daily_limit 失效 |
| consecutive_count 重置 | 用户回复主动消息 / 超时无触发 / 跨天 三种条件均可重置 |
| maisaka 失败回滚 | trigger 失败时删除 nonce、不更新 guard（不消耗 daily quota） |
| proactive lock 范围 | Phase 1 持锁检查+nonce 注册，Phase 2 无锁 LLM，Phase 3 持锁更新 guard |
| API 安全 | 显式 DTO + versioned schema 路由 + dataclasses.asdict()，不暴露 `__dict__` |
| _affinity_to_hint 共享 | 提取到 utils/hint_helper.py，tools.py 和 apis.py 共用 |
| manager 职责 | 仅改状态 + transition_id 去重，副作用全部由 orchestrator dispatch |
| Budget 与 Guard 不重复 | proactive daily_limit 统一由 ProactiveGuard 管理，Budget 不再维护 can_proactive() |
| budget daily 持久化 | budget_counter 表，重启后恢复，防 daily 计数归零 |
| Hook 名称 | 拦截用 `chat.receive.before_process`(BLOCKING)，观察用 `chat.receive.after_process`(OBSERVE) |
| Tool person 参数 | get_person_impression 接受 person_name，内部用 person_api 解析，对 LLM 更友好 |
| status_hint 生成 | 硬编码模板映射（ActivityType × SleepState），不调用 LLM，可附加 description 增加多样性 |
| upcoming 数量 | 最多 3 条、4 小时内，config 可调 |
| WAL checkpoint | PASSIVE 通过 writer queue 执行 + on_unload FULL + size 监控 |
| 过期记录清理 | heartbeat 中批量清理 proactive_nonce 和 processed_transition 表 |
