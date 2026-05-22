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
| **睡眠系统** | 4 个状态：清醒 / 困倦 / 睡着 / 苏醒，睡着时拦截消息 |
| **频率控制** | 根据当前活动类型通过 `frequency.set_adjust()` 调整 MaiBot 发言频率 |
| **关系网** | 记录与每个用户的互动印象（基于人格 AI 生成），影响回复倾向和主动发消息对象 |
| **主动行为** | 调度器定时触发，满足条件时通过 `maisaka.proactive.trigger()` 让 MaiBot 主动发消息 |
| **Tool（LLM 工具）** | 给 MaiBot 的推理引擎提供当前状态查询接口，让 MaiBot 回答"你在干嘛"时有据可依 |
| **插件 API** | 暴露核心状态 API 供其他插件调用 |

### 2.2 不做的功能

- 天气感知
- 节日 API（生日等归入关系网印象）
- 调试命令系统（可后续补充）
- 疾病/健康系统（过于复杂，YAGNI）
- 旧版社交网络亲密度数值系统

---

## 3. 架构设计

### 3.1 目录结构

```
life-simulation/
├── _manifest.json              # 插件清单（manifest_version: 2）
├── plugin.py                   # 入口：继承 MaiBotPlugin，注册所有组件
├── config.toml                 # 默认配置
├── requirements.txt
├── core/
│   ├── __init__.py
│   ├── state.py                # 全局状态对象（日程、睡眠状态、疲劳、当前活动）
│   ├── scheduler.py            # 后台调度器（定时生成日程、触发主动行为）
│   └── database.py             # aiosqlite 封装（关系网持久化）
├── systems/
│   ├── __init__.py
│   ├── schedule.py             # 日程系统（AI 生成 + 固定骨架 + 时间段管理）
│   ├── sleep.py                # 睡眠系统（状态机：清醒/困倦/睡着/苏醒）
│   ├── relation.py             # 关系网（AI 生成印象、好感、记忆碎片）
│   └── proactive.py            # 主动行为（触发条件判断 + maisaka 调用）
├── components/
│   ├── __init__.py
│   ├── hooks.py                # @HookHandler：消息拦截（睡眠）、频率调整
│   ├── tools.py                # @Tool：get_current_state / get_schedule / get_relation
│   ├── commands.py             # @Command：/life_status 等用户命令
│   └── apis.py                 # @API：暴露给其他插件的接口
└── utils/
    ├── __init__.py
    ├── llm_helper.py           # LLM 调用封装（重试、JSON 解析、prompt 构建）
    └── time_helper.py          # 时间工具（当前时段、跨天判断）
```

### 3.2 模块职责边界

每个模块只做一件事，通过 `LifeState`（`core/state.py`）共享状态，不直接互相依赖：

```
plugin.py
    └── 持有 LifeState 单例
    └── 初始化各 system，注入 LifeState + ctx
    └── 注册所有 components

components/* ──读──→ LifeState
systems/*    ──读写→ LifeState
scheduler    ──调用→ systems/*（生成日程、触发主动行为）
```

---

## 4. 核心模块详细设计

### 4.1 状态管理（core/state.py）

`LifeState` 是内存单例，保存所有运行时状态，支持序列化到 JSON 文件持久化：

```python
@dataclass
class LifeState:
    # 睡眠
    sleep_state: SleepState = SleepState.AWAKE

    # 生理
    fatigue: float = 0.0          # 0.0~1.0
    hunger: float = 0.0           # 0.0~1.0

    # 日程
    today_schedule: list[ScheduleItem] = field(default_factory=list)
    schedule_generated_date: str = ""   # "YYYY-MM-DD"

    # 当前活动
    current_activity: ActivityType | None = None
    activity_since: datetime | None = None

    # 最近事件（给 AI 上下文用）
    recent_events: list[str] = field(default_factory=list)  # 最多保留 10 条
```

睡眠状态枚举（4个）：
```python
class SleepState(Enum):
    AWAKE = "awake"
    SLEEPY = "sleepy"       # 困倦：频率降低
    SLEEPING = "sleeping"   # 睡着：拦截消息
    WAKING = "waking"       # 苏醒：过渡状态
```

活动类型枚举：
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

每个活动类型对应一个**频率调整系数**（-1.0 ~ 1.0），在 `config.toml` 中可配置。

### 4.2 日程系统（systems/schedule.py）

**数据结构：**
```python
@dataclass
class ScheduleItem:
    start_time: str      # "HH:MM"
    end_time: str        # "HH:MM"
    activity: ActivityType
    description: str     # 具体描述，如"去健身房跑步"
```

**生成流程：**
1. 固定骨架：从 config 读取睡眠时间段、三餐时间段，写入固定 ScheduleItem
2. AI 填充：将剩余空闲时间段发给 LLM，附上人格信息，让 AI 生成具体活动
3. 合并排序，确保覆盖全天 00:00~24:00，无空隙（用 OTHER 填充）
4. 写入 `LifeState.today_schedule`

**当前活动查找：**
根据当前时间在 `today_schedule` 中找到对应 `ScheduleItem`，支持跨天（00:00 前后）。

**重新生成触发条件：**
- 每天 00:00（调度器触发）
- 手动命令触发（`/life_status` 的一部分）

### 4.3 睡眠系统（systems/sleep.py）

**状态转换：**
```
AWAKE ──(日程进入睡觉时段)──→ SLEEPY ──(30分钟后)──→ SLEEPING
SLEEPING ──(日程睡觉时段结束)──→ WAKING ──(15分钟后)──→ AWAKE
```

- `SLEEPY`：`frequency.set_adjust()` 设为较低值，但不拦截消息
- `SLEEPING`：通过 `@HookHandler` 拦截消息，不回复
- `WAKING`：频率恢复正常，可回复消息

**与日程同步：** 调度器每分钟检查当前活动，如果是 `SLEEPING` 活动则驱动睡眠状态机。

### 4.4 频率控制（components/hooks.py）

使用 `@HookHandler("on_message_before_reasoning", mode="blocking")` 拦截消息管线：
- 睡眠状态（`SLEEPING`）：直接返回 `None` 终止消息处理
- 其他状态：根据 `LifeState.current_activity` 调用 `frequency.set_adjust()`，然后放行

每条消息到来时，根据 `LifeState.current_activity` 调用 `frequency.set_adjust()`：

| 活动类型 | 频率调整值（默认，config 可改） |
|---------|-------------------------------|
| SLEEPING | -1.0（完全不回，由拦截处理）  |
| EXERCISING | -0.6 |
| STUDYING / WORKING | -0.4 |
| EATING | -0.2 |
| LEISURE / OTHER | 0.0（正常）|

### 4.5 关系网（systems/relation.py）

**数据结构（aiosqlite 持久化）：**
```python
@dataclass
class PersonImpression:
    person_id: str
    person_name: str
    # AI 生成的印象
    traits: list[str]          # 性格标签，如 ["善良", "幽默"]
    affinity: float            # 好感度 0.0~1.0
    memories: list[str]        # 记忆碎片，最多 10 条
    # 主动社交意愿
    want_to_talk: bool         # 是否想主动发消息
    last_updated: datetime
```

**印象更新触发：**
- 每次与该用户有消息互动后，有一定概率（config 可配置）触发 AI 重新评估印象
- AI 输入：MaiBot 人格 + 最近几条对话 + 旧印象 → 新印象

**对行为的影响：**
- `affinity > 0.7`：`want_to_talk = True`，主动行为系统可能选择此人发消息
- 印象通过 `get_relation` Tool 暴露给 MaiBot 推理引擎，影响回复语气

### 4.6 主动行为（systems/proactive.py）

**触发条件（调度器每 N 分钟检查）：**
1. 日程切换时（如"刚开始吃饭"、"吃完饭了"）
2. 特殊时刻（如早上起床后第一次发消息）
3. 关系网中有 `want_to_talk = True` 的人，且距上次主动发消息超过阈值

**触发方式：**
```python
await ctx.maisaka.proactive.trigger(
    stream_id=stream_id,
    intent="刚吃完午饭，心情不错",
    reason="schedule_transition",
    metadata={"activity": "eating", "source": "life_simulation"},
)
```

intent 由当前状态 + 关系网自动构建，让 MaiBot 用自己的语言表达，不硬编码文本。

**目标群选择：** 优先选择有活跃互动的群，或 `want_to_talk = True` 对应的私聊。

### 4.7 Tool 组件（components/tools.py）

暴露给 MaiBot LLM 推理引擎的工具，让 MaiBot 在生成回复时能查询自身状态：

| Tool 名称 | 说明 | 关键返回字段 |
|-----------|------|-------------|
| `get_life_state` | 当前状态概览 | sleep_state, current_activity, fatigue, hunger, recent_events |
| `get_today_schedule` | 今日日程 | schedule 列表, current_item |
| `get_person_impression` | 对某用户的印象 | traits, affinity, memories |

### 4.8 插件 API（components/apis.py）

通过 `@API` 装饰器暴露，供其他插件调用：

| API 名称 | 说明 | 返回 |
|----------|------|------|
| `life_sim.get_current_state` | 获取当前完整状态 | LifeState dict |
| `life_sim.get_schedule` | 获取今日日程 | list[ScheduleItem dict] |
| `life_sim.get_impression` | 查询对某用户印象 | PersonImpression dict |
| `life_sim.get_frequency_factor` | 获取当前频率调整值 | float |
| `life_sim.get_sleep_state` | 获取当前睡眠状态 | str |

---

## 5. 配置设计（config.toml）

```toml
[plugin]
enabled = true

[schedule]
# 固定骨架时间段
sleep_start = "23:00"
sleep_end = "07:00"
breakfast_start = "07:30"
breakfast_end = "08:00"
lunch_start = "12:00"
lunch_end = "12:30"
dinner_start = "18:00"
dinner_end = "18:30"

[sleep]
# 困倦→睡着的过渡时间（分钟）
sleepy_duration_minutes = 30
# 睡着→苏醒后过渡时间（分钟）
waking_duration_minutes = 15

[frequency]
# 各活动类型的频率调整值（-1.0~1.0）
sleeping = -1.0
exercising = -0.6
studying = -0.4
working = -0.4
eating = -0.2
leisure = 0.0
other = 0.0

[relation]
# 触发 AI 更新印象的概率（每次互动）
update_probability = 0.2
# 记忆碎片最大条数
max_memories = 10
# 主动发消息的最小间隔（分钟）
proactive_min_interval_minutes = 60

[proactive]
# 是否启用主动行为
enabled = true
# 日程切换时触发主动行为的概率
schedule_transition_probability = 0.4

[prompts]
# 留空则使用代码内置的默认提示词模板
# 日程生成提示词（支持 {personality}、{date}、{skeleton} 变量）
schedule_generation = ""
# 关系印象更新提示词（支持 {personality}、{person_name}、{recent_messages}、{old_impression} 变量）
impression_update = ""
# 主动行为 intent 生成提示词（支持 {state}、{activity} 变量）
proactive_intent = ""
```

---

## 6. 数据流

### 6.1 消息到来时

```
消息进入
    → hooks.py @HookHandler
        → 检查 sleep_state
            → SLEEPING: 拦截，返回 None（不继续处理）
            → 其他: 继续
        → 根据 current_activity 调用 frequency.set_adjust()
        → 触发关系网印象更新（异步，不阻塞消息）
```

### 6.2 调度器循环（每分钟）

```
scheduler.py
    → 检查是否需要生成今日日程
    → 更新 current_activity（根据当前时间查日程）
    → 驱动睡眠状态机
    → 检查主动行为触发条件
        → 满足条件 → proactive.py → maisaka.proactive.trigger()
    → 持久化 LifeState
```

### 6.3 MaiBot 生成回复时

```
MaiBot 推理引擎
    → 调用 get_life_state Tool → 得到当前状态
    → 调用 get_today_schedule Tool → 得到日程
    → 调用 get_person_impression Tool（可选）→ 得到对用户的印象
    → 综合状态 + 人格 → 生成自然回复
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

## 8. 不做的东西（明确排除）

- 天气感知
- 节日 API（生日等归入关系网 memories）
- 调试命令系统（后续可补充）
- 疾病/健康系统
- 旧版社交网络亲密度数值体系
- 习惯系统（过于复杂）
