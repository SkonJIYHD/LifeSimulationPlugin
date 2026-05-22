# Life Simulation Plugin v2.0

让 MaiBot 更拟人的插件：有自己的日程、会因为"在忙"减少发言、被问时根据当前状态 AI 生成回答、偶尔主动发消息、对群里的人形成印象和关系。

[![许可证](https://img.shields.io/badge/License-AGPL--3.0-green.svg)](/LICENSE)
[![MaiBot SDK](https://img.shields.io/badge/maibot--plugin--sdk-2.0+-orange.svg)](https://docs.mai-mai.org/develop/plugin-dev/)

---

## 功能

- **日程系统**：每天 AI 生成一份日程，固定骨架（睡眠/三餐）+ AI 填充其余时间段
- **睡眠系统**：4 个状态（清醒/困倦/睡着/苏醒），睡着时拦截消息
- **频率控制**：根据当前活动调整 MaiBot 的发言频率（睡觉不回、学习/工作减少、休闲正常）
- **关系网**：记录与每个用户的互动印象（AI 生成），影响回复语气和主动发消息对象
- **主动行为**：日程切换时或关系分数触发，通过 Maisaka 让 MaiBot 主动发消息
- **LLM 工具**：向 MaiBot 推理引擎暴露当前状态，让它在回答"你在干嘛"时有据可依
- **插件 API**：暴露给其他插件调用的接口（见下文）

---

## 安装

**要求：** MaiBot with maibot-plugin-sdk 2.0+

1. 将插件目录放到 `plugins/life-simulation/`
2. 安装依赖：

   ```bash
   pip install aiosqlite>=0.20.0
   ```

3. 在 WebUI 中启用插件，首次启动自动生成数据库和配置

---

## 配置

配置文件：`config.toml`，所有字段均有默认值，按需修改。

```toml
[plugin]
timezone = "Asia/Shanghai"      # 展示层时区

[schedule]
sleep_start = "23:00"           # 睡觉开始时间（本地时间）
sleep_end = "07:00"             # 起床时间

[sleep]
sleepy_duration_minutes = 30    # 进入睡眠状态前的困倦时长
waking_duration_minutes = 15    # 睡醒后的苏醒过渡时长

[frequency]
# 各活动类型对应的发言频率调整值（-1.0 ~ 1.0）
sleeping = -1.0
working = -0.4
eating = -0.2
leisure = 0.0

[proactive]
enabled = true
daily_limit = 5                 # 每天最多主动发消息次数
quiet_hours_start = "23:00"     # 安静时段（不主动发消息）
quiet_hours_end = "07:00"

[prompts]
# 留空使用内置提示词模板；填写则覆盖
# 可用变量：{personality} {date} {skeleton}
schedule_generation = ""
# 可用变量：{personality} {person_name} {recent_messages} {old_impression}
impression_update = ""
# 可用变量：{state} {activity} {description}
proactive_intent = ""
```

完整配置项参见 `config.toml`。

---

## LLM 工具（Tool）

插件向 MaiBot 推理引擎注册 3 个工具：

| 工具名 | 说明 |
|--------|------|
| `get_life_state` | 当前状态概览（活动、睡眠状态、自然语言描述、是否适合回复） |
| `get_today_schedule` | 今日日程（当前活动、即将到来的安排） |
| `get_person_impression` | 对某个用户的印象（性格标签、好感度描述） |

---

## 插件 API

其他插件可通过 `ctx.api.call()` 调用：

| API 名称 | 参数 | 返回 |
|----------|------|------|
| `life_sim.get_current_state` | `schema_version="v1"` | 当前状态 dict |
| `life_sim.get_schedule` | — | 今日日程列表 |
| `life_sim.get_impression` | `person_id: str` | 对该用户的印象 dict |
| `life_sim.get_frequency_factor` | — | 当前频率调整值 float |
| `life_sim.get_sleep_state` | — | 当前睡眠状态字符串 |

示例：

```python
result = await ctx.api.call("life_sim.get_sleep_state")
# -> "awake" | "sleepy" | "sleeping" | "waking"

state = await ctx.api.call("life_sim.get_current_state")
# -> {"schema_version": "v1", "sleep_state": "awake", "current_activity": "studying", ...}
```

---

## 命令

| 命令 | 说明 |
|------|------|
| `/life_status` | 查看当前状态（睡眠、活动、今日日程概览） |

---

## 数据文件

- `data/life_simulation.db` — SQLite 数据库（状态、关系网、日程持久化）

---

## 项目结构

```
life-simulation/
├── plugin.py               # 入口（所有 SDK 组件在此注册）
├── config.toml             # 默认配置
├── core/
│   ├── state.py            # 状态管理（LifeStateManager）
│   ├── database.py         # SQLite WAL 数据库
│   ├── orchestrator.py     # 调度编排（事件驱动）
│   └── budget.py           # LLM 调用预算
├── systems/
│   ├── schedule.py         # 日程系统
│   ├── sleep.py            # 睡眠状态派生（纯函数）
│   ├── relation.py         # 关系网
│   └── proactive.py        # 主动行为
├── components/             # 纯业务逻辑（无 SDK 依赖）
│   ├── hooks.py
│   ├── tools.py
│   ├── apis.py
│   └── commands.py
└── utils/
    ├── time_helper.py
    ├── hint_helper.py
    └── llm_helper.py
```

---

## 许可证

[AGPL-3.0](/LICENSE)
