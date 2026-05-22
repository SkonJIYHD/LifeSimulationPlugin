# Life Simulation Plugin 重设计 设计文档

**日期：** 2026-05-22  
**版本：** v2.0（完全重写）  
**目标 MaiBot SDK：** maibot-plugin-sdk（新版）

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
| **频率控制** | activity transition 时通过 `frequency.set_adjust()` 调整发言频率，Hook 内只读不写 |
| **关系网** | 记录与每个用户的互动印象（基于人格 AI 批量更新），影响回复倾向和主动发消息对象 |
| **主动行为** | 事件驱动触发，含全局限流和完整幂等保护，通过 `maisaka.proactive.trigger()` 让 MaiBot 主动发消息 |
| **Tool（LLM 工具）** | 给 MaiBot 推理引擎提供摘要态状态查询接口，仅返回自然语言 hint |
| **插件 API** | 暴露核心状态 API 供其他插件调用，使用显式 DTO，versioned schema |

### 2.2 全局单人格状态模型（设计决策）

MaiBot 是一个人，不是多个实例。全局只有一套日程、睡眠、activity、proactive 状态，所有群共享。这是 feature，不是 bug：MaiBot 在群 A 吃饭，群 B 就应该也知道它在吃饭。`frequency.set_adjust()` 为全局模式，禁止 per-stream frequency state。

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
│   ├── state.py                # LifeStateManager：并发安全，asyncio.Lock，deep copy snapshot
│   ├── database.py             # SQLite 封装（WAL + checkpoint 策略，single writer queue，原子事务）
│   ├── orchestrator.py         # 调度编排：事件驱动 + transition timer，background task registry
│   └── budget.py               # 资源预算：LLM 调用限额，proactive 限额，dirty flush 限额
├── systems/
│   ├── __init__.py
│   ├── schedule.py             # 日程系统（AI 生成 + 骨架 + schema validate + repair 次数限制 + fallback）
│   ├── sleep.py                # 睡眠状态派生（纯函数，不 import 其他 system）
│   ├── relation.py             # 关系网（dirty 队列 + 去重 + TTL + 批量 AI 更新 + 负反馈 decay）
│   └── proactive.py            # 主动行为（全局/群组限流 + 幂等保护 + nonce registry）
├── components/
│   ├── __init__.py
│   ├── hooks.py                # @HookHandler：blocking 极简，create_task 包裹异常捕获
│   ├── tools.py                # @Tool：摘要态 hint，不暴露底层字段
│   ├── commands.py             # @Command：/life_status 等用户命令
│   └── apis.py                 # @API：显式 DTO，versioned schema，供其他插件调用
└── utils/
    ├── __init__.py
    ├── llm_helper.py           # LLM 调用封装（timeout/retry/schema validate/repair limit/budget check）
    └── time_helper.py          # 时间工具（timezone-aware UTC，展示层转本地时间，monotonic 校验）
```

### 3.2 模块职责边界与通信规则

**核心原则：systems 之间禁止互相 import，所有系统仅通过 LifeStateManager 和 orchestrator 通信。**

```
plugin.py
    └── 持有 LifeStateManager 单例
    └── 初始化 orchestrator（注入 manager + ctx + budget）
    └── 注册所有 components
    └── on_load()  → orchestrator.start()（启动，recovery check，repair missed transitions）
    └── on_unload() → orchestrator.stop()（cancel all tasks，flush DB，cleanup）
    └── on_config_update() → orchestrator.reload_config()（热更新，见 reload policy）

orchestrator ──调用→ systems/*（schedule/sleep/relation/proactive）
orchestrator ──持有→ background_task_registry（统一管理 create_task，done callback，异常捕获）
systems/*    ──通过 manager 读写→ LifeStateManager
components/* ──通过 manager.snapshot() 只读→ LifeStateSnapshot（deep copy，无泄漏）
hooks.py     ──只读 snapshot，不调用任何 system，create_task 用 registry 包裹──
DB 写操作    ──全部通过 single writer queue，避免 sqlite busy──
```

---

## 4. 核心模块详细设计

### 4.1 状态管理（core/state.py）

`LifeStateManager` 是并发安全的状态管理器。所有写操作必须通过方法入口；外部模块只能拿到 deep copy 的不可变 snapshot，防止浅拷贝导致可变对象泄漏。

**snapshot 防泄漏规则：**
- `today_schedule`：返回 `tuple(copy.deepcopy(item) for item in self._state.today_schedule)`
- `recent_events`：返回 `tuple(self._state.recent_events)`（字符串不可变，tuple 化足够）
- 所有 dict/list 字段均 deep copy 或 tuple 化后放入 frozen dataclass

```python
@dataclass(frozen=True)
class LifeStateSnapshot:
    """对外暴露的不可变快照。today_schedule 和 recent_events 均为 tuple，防止外部修改。"""
    sleep_state: SleepState
    current_activity: ActivityType
    activity_since: datetime                    # timezone-aware UTC
    schedule_generated_date: str                # "YYYY-MM-DD"
    today_schedule: tuple[ScheduleItem, ...]    # tuple，不可变
    recent_events: tuple[str, ...]              # tuple，不可变，含 timestamp 和 type

class LifeStateManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._state: LifeState = LifeState()

    def snapshot(self) -> LifeStateSnapshot:
        """返回 deep copy 的不可变快照，无锁（读操作，Python GIL 保护基本字段）。"""
        ...

    async def transition_activity(self, new_activity: ActivityType, transition_id: str) -> bool:
        """唯一的 activity 写入入口。返回 False 表示 transition_id 已处理（幂等）。"""
        async with self._lock:
            if transition_id in self._processed_transitions:
                return False
            self._processed_transitions.add(transition_id)
            # 仅修改状态，不触发副作用（副作用由 orchestrator dispatch）
            ...
            return True

    async def set_schedule(self, items: list[ScheduleItem], is_repair: bool = False) -> None:
        """is_repair=True 时标记为 synthetic transition，proactive 系统不响应。"""
        async with self._lock:
            ...

    async def append_event(self, event: RecentEvent) -> None:
        """追加事件，自动 TTL prune 和最大条数限制。"""
        async with self._lock:
            ...
```

**transition_activity 职责边界（解决膨胀问题）：**
- manager 仅负责：状态修改、sleep_state 派生、transition_id 去重、持久化入队
- 副作用（frequency 调整、proactive 触发）全部由 orchestrator 在 `_on_transition()` 中 dispatch

**睡眠状态枚举（4个，派生状态）：**
```python
class SleepState(Enum):
    AWAKE = "awake"
    SLEEPY = "sleepy"       # 当前 activity=SLEEPING 但未达 sleepy_duration
    SLEEPING = "sleeping"   # 困倦持续超过 sleepy_duration
    WAKING = "waking"       # 从 SLEEPING 切出后的过渡期
```

**活动类型枚举（唯一真相源）：**
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

**内部 LifeState（私有）：**
```python
@dataclass
class LifeState:
    current_activity: ActivityType = ActivityType.OTHER
    activity_since: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    sleep_state: SleepState = SleepState.AWAKE      # 派生字段
    today_schedule: list[ScheduleItem] = field(default_factory=list)
    schedule_generated_date: str = ""
    recent_events: list[RecentEvent] = field(default_factory=list)
    _processed_transitions: set[str] = field(default_factory=set)  # 幂等去重缓存
```

**recent_events 生命周期：**
```python
@dataclass
class RecentEvent:
    event_type: str          # "schedule_transition" / "proactive_trigger" 等
    description: str
    timestamp: datetime      # timezone-aware UTC
    ttl_seconds: int = 3600  # 默认 1 小时后过期

# append_event 时自动清理：
# 1. 移除 timestamp + ttl_seconds < now 的过期事件
# 2. 超过 max_recent_events（config，默认 20）时移除最旧的
```

### 4.2 数据库（core/database.py）

统一 SQLite，WAL 模式，single writer queue 避免并发写冲突：

```python
class Database:
    """所有写操作通过 asyncio.Queue 串行化，避免 sqlite3 OperationalError: database is locked。"""

    async def start(self):
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self):
        """单一 writer task，所有写操作排队执行。"""
        while True:
            op = await self._write_queue.get()
            try:
                async with self._conn.execute("BEGIN"):
                    await op(self._conn)
                    await self._conn.commit()
            except Exception as e:
                logger.error("DB write error: %s", e)
            finally:
                self._write_queue.task_done()

    async def enqueue_write(self, op: Callable) -> None:
        """提交写操作到队列，非阻塞。"""
        await self._write_queue.put(op)
```

**表结构：**
```sql
CREATE TABLE life_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL         -- unix timestamp UTC
);

CREATE TABLE person_impression (
    person_id TEXT PRIMARY KEY,
    person_name TEXT NOT NULL,
    traits TEXT NOT NULL DEFAULT '[]',      -- JSON array
    affinity REAL NOT NULL DEFAULT 0.5,
    proactive_score REAL NOT NULL DEFAULT 0.0,
    proactive_cooldown_until REAL,          -- unix timestamp UTC
    last_interaction REAL,
    last_impression_update REAL,
    dirty INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE proactive_nonce (
    nonce TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL             -- nonce TTL，过期自动清理
);

CREATE TABLE processed_transition (
    transition_id TEXT PRIMARY KEY,
    processed_at REAL NOT NULL,
    expires_at REAL NOT NULL             -- 持久化幂等缓存，重启后仍有效
);
```

**WAL checkpoint 策略：**
- 每隔 `db.checkpoint_interval_minutes`（默认 60 分钟）执行 `PRAGMA wal_checkpoint(PASSIVE)`
- `on_unload` 时执行 `PRAGMA wal_checkpoint(FULL)` 确保干净退出
- DB 文件大小超过 `db.max_size_mb`（默认 50MB）时触发告警日志

### 4.3 调度编排（core/orchestrator.py）

**事件驱动 + transition timer，background task registry 统一管理所有异步任务：**

```python
class BackgroundTaskRegistry:
    """统一管理 create_task，done callback 自动捕获异常，on_unload 时统一 cancel。"""
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
            logger.error("Background task %s raised: %s", task.get_name(), exc, exc_info=exc)

    async def cancel_all(self):
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

class Orchestrator:
    async def start(self):
        await self._recovery_check()         # 启动时恢复检查
        self._registry.create_task(self._run(), name="orchestrator.main")
        self._registry.create_task(self._heartbeat(), name="orchestrator.heartbeat")

    async def stop(self):
        await self._registry.cancel_all()
        await self._db.flush()               # 确保退出前持久化

    async def _run(self):
        while True:
            now = datetime.now(tz=timezone.utc)
            next_transition_time, next_activity = self._calc_next_transition(now)
            sleep_secs = (next_transition_time - now).total_seconds()
            await asyncio.sleep(max(sleep_secs, 0))

            # 醒来后重新校验（防系统休眠漂移）
            actual_now = datetime.now(tz=timezone.utc)
            actual_activity = schedule.get_current_activity(self._manager.snapshot(), actual_now)

            # 处理 missed transitions（系统休眠期间跳过的切换）
            missed = schedule.get_missed_transitions(self._manager.snapshot(), actual_now)
            for missed_activity, missed_time in missed:
                tid = f"transition:{missed_time.isoformat()}:{missed_activity.value}"
                await self._on_transition(missed_activity, tid, is_missed=True)

            tid = f"transition:{actual_now.isoformat()}:{actual_activity.value}"
            await self._on_transition(actual_activity, tid)

    async def _on_transition(self, new_activity: ActivityType, transition_id: str, is_missed: bool = False):
        old_snap = self._manager.snapshot()
        ok = await self._manager.transition_activity(new_activity, transition_id)
        if not ok:
            return  # 已处理，幂等跳过

        # 副作用链（manager 仅改状态，副作用在此 dispatch）
        await self._apply_frequency(new_activity)
        if not is_missed:   # missed transition 不触发 proactive
            await self._proactive.on_transition(old_snap.current_activity, new_activity, transition_id)
        await self._db.enqueue_write(self._persist_state)

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(self._config.heartbeat_seconds)
            await self._relation.flush_dirty_impressions()
            await self._proactive.check_score_trigger()
            await self._db.maybe_checkpoint()

    async def _recovery_check(self):
        """启动时：从 DB 恢复状态，检查跨天日程，repair missed transitions。"""
        snap = await self._db.load_state()
        if snap:
            await self._manager.restore(snap)
        # 检查是否跨天，需要重新生成日程
        today = date.today().isoformat()
        if self._manager.snapshot().schedule_generated_date != today:
            await self._schedule.generate(today, is_recovery=True)
        # repair: 找出从上次保存到现在之间 missed 的所有 transitions
        # repair 产生的 transition 不触发 proactive（is_missed=True）
```

**reload_config policy（配置热更新语义）：**

| 配置项 | 生效时机 |
|--------|---------|
| `frequency.*` | immediate（立即调用一次 set_adjust） |
| `proactive.*`（限流参数） | immediate |
| `prompts.*` | immediate（下次 LLM 调用生效） |
| `llm.*`（timeout/retry） | immediate |
| `relation.min_update_interval` | immediate |
| `schedule.*`（骨架时间） | next-day（次日日程生成时生效） |
| `sleep.*`（过渡时长） | next-transition（下次 transition 时重新派生） |

### 4.4 日程系统（systems/schedule.py）

**数据结构（内部统一 `datetime.time`，UTC-aware）：**
```python
@dataclass(frozen=True)
class ScheduleItem:
    start_time: datetime.time    # timezone-aware
    end_time: datetime.time
    activity: ActivityType
    description: str
    is_skeleton: bool = False    # True=固定骨架，不可被 AI 覆盖
```

**生成流程：**
1. 从 config 构建骨架 items（`is_skeleton=True`）
2. 计算空闲时间段 → 调用 `llm_helper.generate_json(prompt, schema, budget_key="schedule")`
3. schema validate：overlap check、empty gap repair、invalid range repair（repair 最多 2 次，超过则直接 fallback）
4. 生成失败（LLM 超时/JSON 非法/repair 超限）→ fallback 默认模板（骨架 + LEISURE 填充全天）
5. `manager.set_schedule(items)`，`is_repair=False`

**next_transition 计算：**
```python
def calc_next_transition(snap: LifeStateSnapshot, now: datetime) -> tuple[datetime, ActivityType]:
    """返回 (切换时间, 切换后的活动)。支持跨天。使用 timezone-aware datetime。"""
    ...

def get_missed_transitions(snap: LifeStateSnapshot, now: datetime) -> list[tuple[ActivityType, datetime]]:
    """返回 last_transition_time 到 now 之间所有未处理的切换点，按时间排序。"""
    ...
```

**schedule repair/reload 时的 synthetic transition 标记：**
`manager.set_schedule(items, is_repair=True)` 设置标记，orchestrator 在 recovery check 中处理，proactive 系统对 `is_repair=True` 产生的 transition 一律跳过。

### 4.5 睡眠系统（systems/sleep.py）

纯函数模块，不持有状态，不 import 其他 system：

```python
def derive_sleep_state(
    activity: ActivityType,
    activity_since: datetime,
    now: datetime,
    config: SleepConfig,
) -> SleepState:
    """纯函数：从 activity + 持续时长派生 SleepState。"""
    if activity != ActivityType.SLEEPING:
        elapsed = (now - activity_since).total_seconds() / 60
        if elapsed < config.waking_duration_minutes:
            # 需要知道"上一个 activity 是否是 SLEEPING"才能判断 WAKING
            # 由 manager 传入 prev_activity 参数解决
            pass
        return SleepState.AWAKE
    elapsed = (now - activity_since).total_seconds() / 60
    if elapsed < config.sleepy_duration_minutes:
        return SleepState.SLEEPY
    return SleepState.SLEEPING
```

`manager.transition_activity()` 调用此纯函数，同时传入 `prev_activity` 以判断 WAKING 状态。

### 4.6 频率控制

`frequency.set_adjust()` 为全局模式，不传 stream_id（所有群共享同一 activity 状态）：

```python
# orchestrator._apply_frequency() 中调用
factor = self._config.frequency[new_activity]
await self._ctx.frequency.set_adjust(chat_id=None, value=factor)  # None = 全局
```

`on_config_update()` 时立即以当前 activity 重新调用一次 `set_adjust()` 使新配置生效。

| 活动类型 | 频率调整值（默认） |
|---------|-----------------|
| SLEEPING | -1.0 |
| EXERCISING | -0.6 |
| STUDYING / WORKING | -0.4 |
| EATING | -0.2 |
| LEISURE / OTHER | 0.0 |

### 4.7 关系网（systems/relation.py）

**dirty 队列管理：**
```python
class DirtyQueue:
    """去重 + 最大长度 + TTL。"""
    _queue: dict[str, float]    # person_id → marked_at (unix timestamp)
    max_size: int               # config，默认 500
    ttl_seconds: int            # config，默认 7200（2小时）

    def mark(self, person_id: str) -> None:
        if person_id in self._queue:
            return  # 去重
        if len(self._queue) >= self.max_size:
            # 移除最旧的（LRU 式）
            oldest = min(self._queue, key=self._queue.get)
            del self._queue[oldest]
        self._queue[person_id] = time.time()

    def pop_batch(self, limit: int) -> list[str]:
        """单轮处理上限，避免 heartbeat 单次处理过多。"""
        now = time.time()
        # 先清理过期
        expired = [pid for pid, t in self._queue.items() if now - t > self.ttl_seconds]
        for pid in expired:
            del self._queue[pid]
        # 取最旧的 limit 个
        sorted_ids = sorted(self._queue, key=self._queue.get)[:limit]
        for pid in sorted_ids:
            del self._queue[pid]
        return sorted_ids
```

**负反馈 decay 机制：**
```python
# 在 flush_dirty_impressions 中，AI 更新印象时同步更新 proactive_score
def update_proactive_score(impression: PersonImpression, had_response: bool) -> float:
    score = impression.proactive_score
    if not had_response:
        # 用户长期不回复：decay 加速
        days_silent = (now - impression.last_interaction).days
        decay = min(days_silent * 0.05, 0.3)
        score = max(0.0, score - decay)
    # 连续主动触发失败（cooldown 记录中）：延长 cooldown，降低 score
    if impression.proactive_cooldown_until and impression.proactive_cooldown_until > now:
        score = max(0.0, score - 0.1)
    return score
```

**单轮 heartbeat 处理上限：** `dirty_flush_per_heartbeat`（config，默认 10），受 budget 控制。

### 4.8 主动行为（systems/proactive.py）

**完整幂等保护体系：**

```python
@dataclass
class ProactiveGuard:
    # 限流
    global_cooldown_until: datetime
    per_group_cooldown: dict[str, datetime]
    daily_count: int
    daily_limit: int
    last_trigger_time: datetime | None
    consecutive_count: int
    # 幂等
    _lock: asyncio.Lock                         # single-flight protection，防多 task 并发进入
    _nonce_registry: set[str]                   # 内存 nonce 去重（重启前有效）
    # DB 层也有 proactive_nonce 表（重启后幂等）
```

**触发流程（含幂等）：**
```python
async def trigger(self, stream_id: str, intent: str, source: str, transition_id: str | None = None):
    async with self._guard._lock:   # single-flight：同一时刻只有一个 trigger 在执行
        nonce = self._make_nonce(stream_id, intent, transition_id)

        # 1. nonce 去重（内存 + DB）
        if nonce in self._guard._nonce_registry:
            return
        if await self._db.nonce_exists(nonce):
            return

        # 2. 限流检查链（全部通过才继续）
        if not await self._check_guard(stream_id):
            return

        # 3. debounce：若 transition 来源，检查 debounce window
        if transition_id and self._is_in_debounce_window(transition_id):
            return

        # 4. 提前注册 nonce（防 await 期间重复进入）
        self._guard._nonce_registry.add(nonce)
        await self._db.register_nonce(nonce, stream_id, ttl=3600)

        # 5. 生成 intent（LLM 失败则取消，不 fallback 硬编码）
        final_intent = await self._build_intent(intent)
        if final_intent is None:
            await self._db.delete_nonce(nonce)
            self._guard._nonce_registry.discard(nonce)
            return

        # 6. 触发（带 idempotency key 发给 maisaka）
        await self._ctx.maisaka.proactive.trigger(
            stream_id=stream_id,
            intent=final_intent,
            reason=source,
            metadata={"nonce": nonce, "source": "life_simulation"},
        )

        # 7. 更新限流状态
        self._update_guard_after_trigger(stream_id)
```

**nonce 生成规则：**
- transition 来源：`sha256(stream_id + transition_id + activity)`
- heartbeat 来源：`sha256(stream_id + person_id + date + "heartbeat")`
- debounce window：同一 `transition_id` 在 N 秒内（config，默认 5s）只触发一次

**触发前检查链：**
1. `sleep_state` 不是 SLEEPING / WAKING（WAKING 时降低概率，不直接禁止）
2. 当前时间不在 `quiet_hours`
3. `global_cooldown_until` 已过
4. `per_group_cooldown[stream_id]` 已过
5. `daily_count < daily_limit`
6. `consecutive_count < max_consecutive`
7. budget 未超限（`budget.can_proactive()`）

**schedule repair 保护：** `set_schedule(is_repair=True)` 产生的 transition 带 `synthetic=True` 标记，`on_transition` 收到后直接跳过 proactive。

### 4.9 Hook 组件（components/hooks.py）

blocking hook 内只做轻量判断，所有 create_task 通过 registry 包裹确保异常被捕获：

```python
@HookHandler("on_message_before_reasoning", mode="blocking")
async def handle_message(self, message, **kwargs):
    snap = self._manager.snapshot()  # 只读，不加锁，GIL 保护

    # 1. 睡眠拦截（纯判断，无副作用）
    if snap.sleep_state == SleepState.SLEEPING:
        return None

    # 2. 关系网 dirty 标记（后台，通过 registry 包裹）
    self._registry.create_task(
        self._mark_interaction(message),
        name=f"mark_interaction:{message.get('message_id', 'unknown')}"
    )

    return message
    # 频率调整不在此处，由 orchestrator transition 时处理
```

### 4.10 Tool 组件（components/tools.py）

返回摘要态自然语言 hint，不暴露底层数值字段：

```python
# get_life_state 返回
{
    "status_hint": "现在在午休，有点困倦",   # 自然语言，供 LLM 直接引用
    "current_activity": "sleeping",           # 枚举值字符串
    "sleep_state": "sleepy",
    "can_chat": False                         # 是否适合回复
    # 不含：fatigue 数值、activity_since、proactive_score 等底层字段
}

# get_today_schedule 返回
{
    "current_item": {"time": "12:00-13:00", "description": "午休"},
    "upcoming": [
        {"time": "14:00-16:00", "description": "写代码"}
    ]
    # time 字段为展示用本地时间字符串，内部 datetime.time 在此层转换
}

# get_person_impression 返回
{
    "traits": ["热情", "话多"],
    "affinity_hint": "印象不错，聊得比较多"   # 不暴露 affinity 数值
}
```

### 4.11 插件 API（components/apis.py）

使用显式 DTO 和 versioned schema，不直接暴露 `snapshot().__dict__`：

```python
@dataclass
class LifeStateDTO:
    """v1 schema，字段变更需要新版本。"""
    schema_version: str = "v1"
    sleep_state: str = ""
    current_activity: str = ""
    schedule_generated_date: str = ""
    # 不含：fatigue、_processed_transitions 等内部字段

@API("life_sim.get_current_state")
async def get_current_state(self, schema_version: str = "v1", **kwargs) -> dict:
    snap = self._manager.snapshot()
    return LifeStateDTO(
        sleep_state=snap.sleep_state.value,
        current_activity=snap.current_activity.value,
        schedule_generated_date=snap.schedule_generated_date,
    ).__dict__

@API("life_sim.get_schedule")
async def get_schedule(self, **kwargs) -> list[dict]:
    snap = self._manager.snapshot()
    return [
        {
            "start": item.start_time.isoformat(),    # 本地时间字符串
            "end": item.end_time.isoformat(),
            "activity": item.activity.value,
            "description": item.description,
        }
        for item in snap.today_schedule
    ]

@API("life_sim.get_impression")
async def get_impression(self, person_id: str, **kwargs) -> dict | None:
    imp = await self._db.get_impression(person_id)
    if imp is None:
        return None
    return {"traits": imp.traits, "affinity_hint": _affinity_to_hint(imp.affinity)}

@API("life_sim.get_frequency_factor")
async def get_frequency_factor(self, **kwargs) -> float:
    snap = self._manager.snapshot()
    return self._config.frequency.get(snap.current_activity, 0.0)

@API("life_sim.get_sleep_state")
async def get_sleep_state(self, **kwargs) -> str:
    return self._manager.snapshot().sleep_state.value
```

### 4.12 资源预算（core/budget.py）

统一管理资源消耗上限，防止异常情况下无限调用：

```python
class ResourceBudget:
    """所有 LLM 调用和主动行为在执行前检查预算。"""

    def can_llm_call(self, call_type: str) -> bool:
        """检查 LLM 调用预算（per hour，按类型独立计数）。"""
        ...

    def can_proactive(self) -> bool:
        """检查主动行为预算（per day）。"""
        ...

    def can_dirty_flush(self, count: int) -> bool:
        """检查单轮 heartbeat dirty flush 预算。"""
        ...

    def record(self, call_type: str) -> None:
        """记录一次调用，滑动窗口计数。"""
        ...
```

**默认预算（config 可改）：**
| 资源类型 | 默认上限 |
|---------|---------|
| `llm.schedule` | 3 次/天 |
| `llm.impression` | 50 次/小时 |
| `llm.proactive_intent` | 20 次/小时 |
| `proactive.trigger` | 5 次/天（与 proactive.daily_limit 共用） |
| `dirty_flush.per_heartbeat` | 10 条/次 |

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
    """
    返回 None 表示彻底失败，调用方必须处理 fallback。
    repair_attempts：schema validate 失败时尝试让 LLM 修复的次数上限，超过直接返回 None。
    """
    if not budget.can_llm_call(budget_key):
        logger.warning("LLM budget exceeded for %s", budget_key)
        return None
    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.wait_for(
                ctx.llm.generate(prompt=prompt),
                timeout=timeout,
            )
            data = _parse_json(result["response"])
            if data is None:
                continue
            repaired = _validate_and_repair(data, schema, max_repair_attempts)
            if repaired is not None:
                budget.record(budget_key)
                return repaired
        except asyncio.TimeoutError:
            logger.warning("LLM timeout on attempt %d/%d for %s", attempt+1, max_retries+1, budget_key)
        except Exception as e:
            logger.error("LLM error: %s", e)
        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)  # 指数退避
    return None
```

### 4.14 时间工具（utils/time_helper.py）

全部使用 timezone-aware datetime，内部 UTC，展示层转本地时间：

```python
def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)

def to_local(dt: datetime, tz_name: str = "Asia/Shanghai") -> datetime:
    """展示层调用，将 UTC datetime 转为本地时间。"""
    return dt.astimezone(ZoneInfo(tz_name))

def time_to_today_utc(t: datetime.time, local_tz: str = "Asia/Shanghai") -> datetime:
    """将 config 中的本地时间字符串转为今天对应的 UTC datetime。"""
    ...

def is_in_quiet_hours(now: datetime, start: datetime.time, end: datetime.time) -> bool:
    """支持跨天 quiet hours（如 23:00~07:00）。"""
    ...
```

---

## 5. 配置设计（config.toml）

```toml
[plugin]
enabled = true
timezone = "Asia/Shanghai"      # 展示层本地时区

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
# activity transition 时全局 set_adjust 值（-1.0~1.0）
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

[prompts]
# 留空则使用代码内置的默认提示词模板（不重启即可生效）
# 变量：{personality}、{date}、{skeleton}
schedule_generation = ""
# 变量：{personality}、{person_name}、{recent_messages}、{old_impression}
impression_update = ""
# 变量：{state}、{activity}、{description}
proactive_intent = ""
```

---

## 6. 数据流

### 6.1 消息到来时（Hook，极轻量）

```
消息进入 → @HookHandler(blocking)
    → snapshot() 只读（无锁）
    → sleep_state == SLEEPING → 拦截返回 None
    → registry.create_task(_mark_interaction)  ← 后台，异常由 done callback 捕获
    → 放行
    （禁止：调用 LLM、调用 frequency、import 任何 system、await 耗时操作）
```

### 6.2 Orchestrator 主循环（事件驱动）

```
orchestrator._run():
    loop:
        next_time, next_activity = calc_next_transition(snap, now_utc())
        await asyncio.sleep(seconds)
        actual_now = now_utc()
        missed = get_missed_transitions(snap, actual_now)   ← 防系统休眠漂移
        for each missed:
            _on_transition(activity, tid, is_missed=True)   ← 不触发 proactive
        _on_transition(current_activity, tid)

_on_transition(activity, tid):
    ok = manager.transition_activity(activity, tid)   ← 幂等，已处理则跳过
    if not ok: return
    _apply_frequency(activity)                        ← 全局 set_adjust，唯一调用点
    proactive.on_transition(old, new, tid)            ← 检查触发（含完整幂等保护）
    db.enqueue_write(persist_state)                   ← single writer queue
```

### 6.3 Orchestrator Heartbeat（定期）

```
orchestrator._heartbeat():
    loop:
        await sleep(heartbeat_seconds)
        relation.flush_dirty_impressions()   ← 批量 AI 更新，受 budget + dirty_queue 控制
        proactive.check_score_trigger()      ← 检查 proactive_score（含幂等保护）
        db.maybe_checkpoint()               ← WAL checkpoint
```

### 6.4 启动恢复流程

```
on_load():
    orchestrator.start()
        → recovery_check()
            → db.load_state() → manager.restore()
            → 检查 schedule_generated_date，跨天则重新生成（is_repair=True）
            → get_missed_transitions(last_saved, now) → 补偿处理（不触发 proactive）
        → 启动 _run() 和 _heartbeat() task
```

### 6.5 MaiBot 生成回复时（Tool）

```
MaiBot 推理引擎
    → get_life_state() → 摘要态 hint（无底层数值）
    → get_today_schedule() → 当前/即将活动（本地时间字符串）
    → get_person_impression(person_id) → 印象 hint（无数值）
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
    "min_version": "1.0.0",
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
| snapshot 可变对象泄漏 | today_schedule/recent_events 全部 deep copy 或 tuple 化，frozen dataclass |
| background task 管理 | BackgroundTaskRegistry：done callback 捕获异常，on_unload 统一 cancel |
| DB 并发写冲突 | single writer queue（asyncio.Queue），串行化所有写操作 |
| frequency stream_id | 全局模式，不传 stream_id，禁止 per-stream state |
| 全局单状态 | 明确设计为单人格全局状态模型，所有群共享，feature 而非 bug |
| timezone | 全部 UTC，展示层转本地，config 指定 timezone |
| sleep_until 漂移 | 醒来后重新校验，get_missed_transitions 补偿处理 |
| proactive 负反馈 | 用户不回复 decay 加速，连续失败延长 cooldown |
| dirty 队列积压 | 去重 + max_size + TTL + per_heartbeat limit |
| schema validate | 严格 validator，repair 次数上限，超限直接 fallback |
| recent_events 生命周期 | timestamp + TTL + auto prune + event type 分类 |
| create_task 吞异常 | 全部通过 registry，done callback retrieve exception logging |
| orchestrator 恢复模式 | recovery_check：恢复状态，repair missed transitions，跨天重建日程 |
| proactive 幂等 | nonce（内存+DB）+ transition_id + debounce + single-flight lock + processed registry |
| API 安全 | 显式 DTO + versioned schema，不暴露 `__dict__` |
| manager 职责膨胀 | manager 仅改状态，副作用全部由 orchestrator dispatch |
| observability | structured logging，proactive audit log，LLM latency 统计（budget.record） |
| 配置热更新语义 | reload policy table：immediate / next-transition / next-day |
| WAL checkpoint | 定期 PASSIVE checkpoint + on_unload FULL checkpoint + size 监控 |
| 资源预算 | ResourceBudget：LLM/proactive/dirty flush 全部有上限，超限跳过不报错 |
