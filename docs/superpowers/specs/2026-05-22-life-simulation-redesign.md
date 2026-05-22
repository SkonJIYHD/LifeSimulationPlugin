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
| **主动行为** | 事件驱动触发，含全局限流，通过 `maisaka.proactive.trigger()` 让 MaiBot 主动发消息 |
| **Tool（LLM 工具）** | 给 MaiBot 推理引擎提供摘要态状态查询接口，仅返回自然语言 hint |
| **插件 API** | 暴露核心状态 API 供其他插件调用 |

### 2.2 不做的功能

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
│   ├── state.py                # LifeStateManager：并发安全的状态管理，asyncio.Lock，对外只暴露 snapshot
│   ├── database.py             # SQLite 封装（WAL 模式，原子事务，统一持久化 state/relation）
│   └── orchestrator.py         # 调度编排：事件驱动 + transition timer，统一调度所有系统
├── systems/
│   ├── __init__.py
│   ├── schedule.py             # 日程系统（AI 生成 + 固定骨架 + 合法性校验 + fallback 模板）
│   ├── sleep.py                # 睡眠状态派生（从 activity 派生，非独立维护）
│   ├── relation.py             # 关系网（dirty 标记 + 批量 AI 更新 + min_update_interval）
│   └── proactive.py            # 主动行为（全局/群组限流 + quiet hours + daily limit）
├── components/
│   ├── __init__.py
│   ├── hooks.py                # @HookHandler：blocking 仅做轻量判断，耗时任务全部后台队列化
│   ├── tools.py                # @Tool：返回摘要态自然语言 hint，不暴露底层字段
│   ├── commands.py             # @Command：/life_status 等用户命令
│   └── apis.py                 # @API：暴露给其他插件的接口
└── utils/
    ├── __init__.py
    ├── llm_helper.py           # LLM 调用封装（timeout/retry/json fallback/schema validate）
    └── time_helper.py          # 时间工具（datetime/time 对象，跨天判断，monotonic 校验）
```

### 3.2 模块职责边界与通信规则

**核心原则：systems 之间禁止互相 import，所有系统仅通过 LifeStateManager 和 orchestrator 通信。**

```
plugin.py
    └── 持有 LifeStateManager 单例
    └── 初始化 orchestrator，注入 manager + ctx
    └── 注册所有 components
    └── on_load() → orchestrator.start()
    └── on_unload() → orchestrator.stop()（正确 cancel task，避免 orphan）

orchestrator ──调用→ systems/*（schedule/sleep/relation/proactive）
systems/*    ──通过 manager 读写→ LifeStateManager
components/* ──通过 manager.snapshot() 只读→ LifeStateSnapshot
hooks.py     ──只读 snapshot，不调用任何 system──

on_config_update() → orchestrator.reload_config()（热更新，不重启插件）
```

---

## 4. 核心模块详细设计

### 4.1 状态管理（core/state.py）

`LifeStateManager` 是线程安全的状态管理器，所有写操作必须通过其方法入口，外部模块只能拿到不可变的 snapshot 副本：

```python
@dataclass(frozen=True)
class LifeStateSnapshot:
    """对外暴露的不可变快照，禁止外部模块持有可变状态对象。"""
    sleep_state: SleepState
    current_activity: ActivityType
    fatigue: float                          # 0.0~1.0，仅内部使用，不暴露给 Tool
    schedule_generated_date: str            # "YYYY-MM-DD"
    recent_events: list[str]                # 最多 10 条，给主动行为用

class LifeStateManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._state: LifeState = LifeState()

    def snapshot(self) -> LifeStateSnapshot:
        """返回当前状态的不可变副本，供只读场景使用。"""
        ...

    async def transition_activity(self, new_activity: ActivityType) -> None:
        """唯一的 activity 写入入口，触发后续副作用（频率调整、睡眠派生）。"""
        async with self._lock:
            ...

    async def set_schedule(self, items: list[ScheduleItem]) -> None:
        async with self._lock:
            ...

    async def append_event(self, event: str) -> None:
        async with self._lock:
            ...
```

**睡眠状态枚举（4个，派生状态，不独立维护）：**
```python
class SleepState(Enum):
    AWAKE = "awake"
    SLEEPY = "sleepy"       # 困倦：当前活动是 SLEEPING 但未达过渡时长
    SLEEPING = "sleeping"   # 睡着：困倦持续超过 sleepy_duration_minutes
    WAKING = "waking"       # 苏醒：活动从 SLEEPING 切出后的过渡期
```

**活动类型枚举（唯一真相源，sleep_state 由此派生）：**
```python
class ActivityType(Enum):
    SLEEPING = "sleeping"   # 此类型触发睡眠状态机，是 SleepState 的唯一驱动源
    EATING = "eating"
    STUDYING = "studying"
    EXERCISING = "exercising"
    LEISURE = "leisure"
    WORKING = "working"
    OTHER = "other"
```

**内部 LifeState（私有，不对外暴露）：**
```python
@dataclass
class LifeState:
    current_activity: ActivityType = ActivityType.OTHER
    activity_since: datetime = field(default_factory=datetime.now)
    sleep_state: SleepState = SleepState.AWAKE   # 派生，由 transition_activity 维护
    fatigue: float = 0.0
    today_schedule: list[ScheduleItem] = field(default_factory=list)
    schedule_generated_date: str = ""
    recent_events: list[str] = field(default_factory=list)
```

### 4.2 数据库（core/database.py）

统一使用 SQLite（WAL 模式），不使用 JSON 持久化，所有写操作使用原子事务：

```python
# 表结构
CREATE TABLE life_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,        -- JSON 序列化
    updated_at REAL NOT NULL
);

CREATE TABLE person_impression (
    person_id TEXT PRIMARY KEY,
    person_name TEXT NOT NULL,
    traits TEXT NOT NULL,       -- JSON array
    affinity REAL NOT NULL DEFAULT 0.5,
    proactive_score REAL NOT NULL DEFAULT 0.0,   -- 替代 want_to_talk bool
    proactive_cooldown_until REAL,               -- unix timestamp
    last_interaction REAL,
    last_impression_update REAL,
    dirty INTEGER NOT NULL DEFAULT 0             -- 0/1，标记待批量更新
);
```

启动时开启 WAL：`PRAGMA journal_mode=WAL;`

### 4.3 调度编排（core/orchestrator.py）

**事件驱动 + transition timer 架构，取代每分钟轮询：**

```python
class Orchestrator:
    async def start(self):
        self._main_task = asyncio.create_task(self._run())
        self._heartbeat_task = asyncio.create_task(self._heartbeat())  # 仅主动行为用

    async def stop(self):
        self._main_task.cancel()
        self._heartbeat_task.cancel()
        await asyncio.gather(self._main_task, self._heartbeat_task, return_exceptions=True)
        await self._flush_db()  # 确保退出前持久化

    async def _run(self):
        while True:
            now = datetime.now()
            next_transition = self._calc_next_transition(now)  # 计算下一个活动切换时间点
            await asyncio.sleep((next_transition - now).total_seconds())
            await self._on_transition()

    async def _heartbeat(self):
        """仅用于主动行为的定期检查，间隔较长（默认 10 分钟）。"""
        while True:
            await asyncio.sleep(self._config.proactive_heartbeat_seconds)
            await self._check_proactive()
```

**transition 时触发的副作用链（统一入口，避免各系统互相耦合）：**
1. `manager.transition_activity(new_activity)` — 更新状态 + 派生 sleep_state
2. `frequency.set_adjust(stream_id, factor)` — 更新频率（仅此处调用，Hook 不调用）
3. `proactive.on_transition(old, new)` — 判断是否触发主动行为
4. `db.save_state()` — 持久化

**日程生成触发：** 每天第一次 transition 时检查 `schedule_generated_date`，不同则重新生成。

### 4.4 日程系统（systems/schedule.py）

**数据结构（内部使用 `datetime.time`，仅展示层转字符串）：**
```python
@dataclass
class ScheduleItem:
    start_time: datetime.time    # 内部统一 time 对象，避免跨天字符串比较错误
    end_time: datetime.time
    activity: ActivityType
    description: str
```

**生成流程：**
1. 从 config 构建固定骨架 items（睡眠、三餐），使用 `datetime.time` 对象
2. 计算空闲时间段，拼 prompt 调用 LLM（带 timeout/retry）
3. LLM 输出做 schema validate（overlap check、empty gap repair、invalid range repair）
4. 合法性校验失败或 LLM 调用失败 → fallback 默认模板（仅骨架 + LEISURE 填充）
5. 写入 `manager.set_schedule(items)`

**当前活动查找：** `find_current_item(schedule, now)` 支持跨天（e.g. 23:00 睡觉跨越 00:00）。

**next_transition 计算：** 返回当前 item 的 `end_time` 对应的下一个 datetime，供 orchestrator sleep_until。

### 4.5 睡眠系统（systems/sleep.py）

**sleep_state 完全派生自 ActivityType，不独立维护活动状态：**

```
activity = SLEEPING，且持续时长 < sleepy_duration  →  sleep_state = SLEEPY
activity = SLEEPING，且持续时长 ≥ sleepy_duration  →  sleep_state = SLEEPING
activity 从 SLEEPING 切出，且持续时长 < waking_duration  →  sleep_state = WAKING
其他  →  sleep_state = AWAKE
```

派生逻辑集中在 `LifeStateManager.transition_activity()` 中，sleep.py 仅提供纯函数 `derive_sleep_state(activity, activity_since, config)` 供其调用。sleep.py 不 import 任何其他 system。

### 4.6 频率控制

`frequency.set_adjust()` 仅在 orchestrator 的 transition 副作用链中调用，**不在 Hook 内调用**。

| 活动类型 | 频率调整值（默认，config 可改） |
|---------|-------------------------------|
| SLEEPING | -1.0 |
| EXERCISING | -0.6 |
| STUDYING / WORKING | -0.4 |
| EATING | -0.2 |
| LEISURE / OTHER | 0.0 |

`on_config_update()` 时重新读取 frequency 配置并立即调用一次 `set_adjust()` 使其生效。

### 4.7 关系网（systems/relation.py）

**数据结构（见 4.2 数据库 `person_impression` 表）：**

`want_to_talk: bool` 改为 `proactive_score: float`（0.0~1.0）+ `proactive_cooldown_until: datetime | None`，并有 decay 机制：

```python
# proactive_score 更新规则（在 AI 印象更新时一并计算）
# - 正向互动 → score 上升
# - 无互动一段时间 → score decay
# - 触发过一次主动行为 → 进入 cooldown，cooldown 期间 score 不影响触发
proactive_score: float = 0.0
```

**interaction 处理（Hook 触发，后台队列化）：**
- Hook 内仅做：`db.mark_dirty(person_id)` + `db.update_last_interaction(person_id)`
- 不在 Hook 内调用 LLM

**批量 AI 印象更新（orchestrator heartbeat 触发）：**
```python
async def _flush_dirty_impressions(self):
    dirty_persons = await db.get_dirty_persons()
    for person in dirty_persons:
        if now - person.last_impression_update < min_update_interval:
            continue   # 冷却中，跳过
        recent_msgs = await ctx.message.get_recent(...)
        new_impression = await llm_helper.update_impression(person, recent_msgs)
        if new_impression is None:
            continue   # LLM 失败，跳过，不影响其他
        await db.save_impression(new_impression)
```

**min_update_interval：** config 可配置，默认 30 分钟，防止 LLM 调用风暴。

### 4.8 主动行为（systems/proactive.py）

**全局限流设计：**
```python
@dataclass
class ProactiveGuard:
    global_cooldown_until: datetime         # 全局冷却（两次主动行为之间）
    per_group_cooldown: dict[str, datetime] # 每个群单独冷却
    daily_count: int                        # 今日已触发次数
    daily_limit: int                        # 今日上限（config）
    last_trigger_time: datetime | None
    consecutive_count: int                  # 连续触发计数，超过阈值强制冷却
```

**触发前检查链（全部通过才触发）：**
1. `sleep_state` 不是 SLEEPING / WAKING
2. 当前时间不在 `quiet_hours`（config：如 23:00~07:00）
3. `global_cooldown_until` 已过
4. `per_group_cooldown[stream_id]` 已过
5. `daily_count < daily_limit`
6. `consecutive_count < max_consecutive`（防连续刷屏）

**触发来源：**
- **transition 触发**：activity 切换时，按 `schedule_transition_probability` 概率触发
- **heartbeat 触发**：定期检查 `proactive_score > threshold` 的用户

**proactive intent 生成：**
- 优先使用 config 中自定义 prompt 模板
- LLM 生成失败 → 取消本次触发（不 fallback 到硬编码文本）

**WAKING 状态下降低概率：** `schedule_transition_probability * waking_probability_factor`（config，默认 0.3）

### 4.9 Hook 组件（components/hooks.py）

`@HookHandler(mode="blocking")` 内只做轻量操作，耗时任务全部后台队列化：

```python
@HookHandler("on_message_before_reasoning", mode="blocking")
async def handle_message(self, message, **kwargs):
    snap = self._manager.snapshot()  # 只读，不加锁

    # 1. 睡眠拦截（轻量判断）
    if snap.sleep_state == SleepState.SLEEPING:
        return None   # 拦截

    # 2. 关系网 dirty 标记（后台，不 await）
    asyncio.create_task(self._mark_interaction(message))

    return message  # 放行
    # 注意：频率调整不在此处，由 orchestrator transition 时处理
```

`_mark_interaction` 仅写 DB 两个字段，极快，但仍用 create_task 避免阻塞消息链。

### 4.10 Tool 组件（components/tools.py）

Tool 返回摘要态，**不暴露 fatigue、activity_since 等底层数值字段**，返回自然语言 hint：

```python
# get_life_state 返回示例
{
    "status_hint": "现在在午休，有点困倦",   # 自然语言摘要，供 LLM 直接引用
    "current_activity": "sleeping",
    "sleep_state": "sleepy",
    "can_chat": False                         # 是否适合回复
}

# get_today_schedule 返回示例
{
    "current_item": {"time": "12:00-13:00", "description": "午休"},
    "upcoming": [{"time": "14:00-16:00", "description": "写代码"}]
}

# get_person_impression 返回示例
{
    "traits": ["热情", "话多"],
    "affinity_hint": "印象不错，聊得比较多"  # 不暴露 affinity 数值
}
```

### 4.11 插件 API（components/apis.py）

```python
@API("life_sim.get_current_state")
async def get_current_state(self, **kwargs) -> dict:
    return self._manager.snapshot().__dict__

@API("life_sim.get_schedule")
async def get_schedule(self, **kwargs) -> list[dict]:
    snap = self._manager.snapshot()
    return [item_to_dict(i) for i in snap.today_schedule]  # time 对象转字符串

@API("life_sim.get_impression")
async def get_impression(self, person_id: str, **kwargs) -> dict | None:
    return await self._db.get_impression(person_id)

@API("life_sim.get_frequency_factor")
async def get_frequency_factor(self, **kwargs) -> float:
    snap = self._manager.snapshot()
    return self._config.frequency[snap.current_activity]

@API("life_sim.get_sleep_state")
async def get_sleep_state(self, **kwargs) -> str:
    return self._manager.snapshot().sleep_state.value
```

### 4.12 LLM 辅助（utils/llm_helper.py）

所有 LLM 调用的统一封装，包含：
- **timeout**：每次调用设置最大等待时间（config，默认 30s）
- **retry**：最多重试 N 次（config，默认 2 次），指数退避
- **json fallback**：解析失败时返回 `None`，由调用方处理
- **schema validate**：日程生成结果使用 schema 校验，不合法则触发 fallback

```python
async def generate_json(
    prompt: list[dict],
    schema: dict,
    timeout: float = 30.0,
    max_retries: int = 2,
) -> dict | None:
    """返回 None 表示彻底失败，调用方必须处理 fallback。"""
    ...
```

### 4.13 配置热更新

`plugin.py` 实现 `on_config_update()`，支持不重启插件即可生效：

```python
async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
    if scope == "self":
        self._orchestrator.reload_config(config_data)
        # 立即生效：frequency 调整值、proactive 限流参数、prompt 模板
        # 不立即生效：schedule 骨架时间（次日日程生成时才生效）
```

---

## 5. 配置设计（config.toml）

```toml
[plugin]
enabled = true

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
# activity transition 时设置的频率调整值（-1.0~1.0）
sleeping = -1.0
exercising = -0.6
studying = -0.4
working = -0.4
eating = -0.2
leisure = 0.0
other = 0.0

[relation]
# dirty impression 的最小更新间隔（分钟）
min_update_interval_minutes = 30
# heartbeat 间隔（秒），用于批量更新印象和检查主动行为
heartbeat_seconds = 600

[proactive]
enabled = true
schedule_transition_probability = 0.4
waking_probability_factor = 0.3
# 全局冷却（分钟）
global_cooldown_minutes = 30
# 每群冷却（分钟）
per_group_cooldown_minutes = 60
# quiet hours（不主动发消息的时间段）
quiet_hours_start = "23:00"
quiet_hours_end = "07:00"
# 每日主动发消息上限
daily_limit = 5
# 连续触发上限（超过后强制全局冷却）
max_consecutive = 2
# proactive_score 触发阈值
score_threshold = 0.7

[llm]
timeout_seconds = 30
max_retries = 2

[prompts]
# 留空则使用代码内置的默认提示词模板
# 支持变量：{personality}、{date}、{skeleton}
schedule_generation = ""
# 支持变量：{personality}、{person_name}、{recent_messages}、{old_impression}
impression_update = ""
# 支持变量：{state}、{activity}、{description}
proactive_intent = ""
```

---

## 6. 数据流

### 6.1 消息到来时（Hook，轻量）

```
消息进入 → @HookHandler(blocking)
    → snapshot() 只读
    → sleep_state == SLEEPING → 拦截返回 None
    → 其他 → create_task(_mark_interaction) → 放行
    （不调用 LLM，不调用 frequency，不 import 任何 system）
```

### 6.2 Orchestrator 主循环（事件驱动）

```
orchestrator._run():
    loop:
        next_transition = schedule.calc_next_transition(now)
        await sleep_until(next_transition)       ← 精确 sleep，无 polling
        new_activity = schedule.get_current(now)
        await manager.transition_activity(new_activity)
            → derive_sleep_state()               ← sleep.py 纯函数
            → 写 DB（原子事务）
        await frequency.set_adjust(factor)       ← 唯一调用点
        await proactive.on_transition(old, new)  ← 检查触发条件
```

### 6.3 Orchestrator Heartbeat（定期，主动行为 + 印象更新）

```
orchestrator._heartbeat():
    loop:
        await sleep(heartbeat_seconds)
        await relation._flush_dirty_impressions()   ← 批量 AI 更新
        await proactive._check_score_trigger()      ← 检查 proactive_score
```

### 6.4 MaiBot 生成回复时（Tool）

```
MaiBot 推理引擎
    → get_life_state() → 摘要态 hint（无底层数值）
    → get_today_schedule() → 当前/即将活动描述
    → get_person_impression(person_id) → 印象 hint（可选）
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

- 记忆系统（归 MaiBot 宿主负责，不是本插件职责）
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
| 并发安全 | `LifeStateManager` + `asyncio.Lock`，外部只拿 frozen snapshot |
| 调度架构 | 事件驱动 + `sleep_until(next_transition)`，仅 heartbeat 保留轮询 |
| 双状态源冲突 | `ActivityType` 为唯一真相源，`SleepState` 完全派生 |
| 频率调用时机 | 仅 transition 时调用，Hook 内禁止 |
| LLM 调用风暴 | dirty 标记 + 批量更新 + `min_update_interval` 冷却 |
| 主动行为失控 | 全局/群组 cooldown + quiet hours + daily limit + consecutive 保护 |
| 持久化可靠性 | 统一 SQLite WAL + 原子事务，废弃 JSON |
| Tool 污染推理 | 仅返回摘要态自然语言 hint，不暴露底层数值 |
| LLM 失败处理 | 日程 fallback 默认模板，印象/主动行为失败直接跳过 |
| Hook 阻塞 | blocking hook 极简，耗时任务全 `create_task` 后台化 |
| 系统耦合 | systems 禁止互相 import，全部通过 orchestrator/manager 通信 |
| 生命周期 | `on_load` 启动，`on_unload` cancel + cleanup，无 orphan task |
| proactive_score | float + decay + cooldown，替代粗糙的 bool |
| 时间表示 | 内部统一 `datetime.time`，仅展示层转字符串 |
| 日程合法性 | overlap check + gap repair + schema validate，失败走 fallback |
| activity 时间漂移 | transition 直接计算，不依赖分钟级扫描，monotonic 校验 |
| 主动行为与睡眠冲突 | trigger 前强制检查 sleep_state + quiet hours |
| 配置热更新 | `on_config_update()` 动态刷新 frequency/proactive/prompt，骨架次日生效 |
