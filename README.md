# LifeSimulationPlugin - 事件及人体模拟插件

一个基于 AI 驱动的事件及人体模拟插件，让机器人具有真实人类的生理状态、日常活动、社交行为和环境感知能力，使机器人更加拟人化和生动。

> 本 README 由 GLM-4.7 编写

## 🤝 贡献

欢迎通过以下方式参与贡献：

- **Pull Requests (PR)**: 欢迎提交功能改进、bug修复或文档更新
- **Issues**: 遇到问题或有建议，欢迎提出 Issue
- **分支开发**: 欢迎创建新分支进行开发工作

## ✨ 特性

- 🤖 **AI 驱动的日程生成** - AI 根据人格、习惯和当前状态生成日程
- 🎲 **AI 驱动的随机事件生成** - AI 根据当前情境生成随机事件
- 🏥 **生病系统** - AI 多维度判断是否生病，生病后自动调整日程
- 💚 **健康状态由事件决定** - 健康状态由随机事件和日程决定
- 🎯 **习惯系统** - 习惯可以配置或由 AI 根据人格生成
- 🎉 **节日 API 集成** - 通过 API 动态获取节假日信息
- 😊 **AI 驱动的情绪判断** - AI 根据多方面因素判断情绪
- 📝 **可编辑的 AI 提示词** - 提示词在配置文件中，可自定义
- 💬 **AI 生成话语** - 所有对话由 AI 生成，不固定
- 🔒 **只读生理状态** - 生理状态数据不能通过命令修改
- ⏰ **自定义时间/日期 API** - 支持用户自定义时间日期获取方式
- 🔧 **可配置 AI 模型** - 支持 9 种模型配置类型
- 🛠️ **习惯工具** - LLM 可调用工具获取习惯信息

## 📋 功能概览

### 生理状态模拟
- **睡眠/清醒状态**: 模拟人类的睡眠周期
- **疲劳度**: 模拟人类的疲劳程度（0-100）
- **饥饿度**: 模拟人类的饥饿程度（0-100）
- **健康状态**: 模拟人类的健康状态，包含生病系统
- **情绪状态**: 模拟人类的情绪状态

### 日常活动模拟
- **日程生成**: AI 根据当前情况生成日程安排
- **活动执行**: 执行日程中的各种活动

### 事件触发系统
- **随机事件**: AI 根据当前情境生成随机事件
- **事件影响**: 事件会影响健康、疲劳、饥饿、情绪等状态

### 习惯系统
- **习惯配置**: 手动配置个人习惯
- **AI 生成习惯**: AI 根据人格特点生成习惯
- **习惯访问**: LLM 可通过工具调用访问习惯信息

### 环境感知
- **时间感知**: 感知当前时间（支持自定义 API）
- **节日感知**: 感知节日，调整行为

## 🚀 安装

### 前置要求
- Python 3.10+
- MaiBot 0.12.0+

### 安装步骤

1. 将插件目录放置在 `plugins/LifeSimulationPlugin/`

2. 确保 `plugins/LifeSimulationPlugin/` 目录包含以下文件：
   ```
   plugins/LifeSimulationPlugin/
   ├── plugin.py
   ├── _manifest.json
   ├── config.toml
   ├── requirements.txt
   └── data/
   ```

3. 在 WebUI 中启用插件

4. 首次运行时，插件会自动生成包含默认提示词的配置文件

## ⚙️ 配置

### 配置文件位置
- 配置文件: `plugins/LifeSimulationPlugin/config.toml`

### 主要配置项

#### [plugin] - 插件基础配置
```toml
[plugin]
enabled = true              # 是否启用插件
update_interval = 60       # 状态更新间隔（秒）
data_dir = "data"            # 数据目录
```

#### [ai] - AI 模型配置
```toml
[ai]
schedule_model = "replyer"  # 日程生成模型
event_model = "tool_use"     # 随机事件生成模型
emotion_model = "planner"   # 情绪判断模型
habit_model = "replyer"     # 习惯生成模型
temperature = 0.7           # AI 温度
max_tokens = 1000           # AI 最大 token 数
```

**可用模型配置类型**:
- `utils` - 工具模型（表情包、取名、关系、情绪等）
- `tool_use` - 工具调用模型
- `replyer` - 回复生成模型
- `planner` - 决策模型
- `vlm` - 图像识别模型
- `voice` - 语音识别模型
- `embedding` - 嵌入模型
- `lpmm_entity_extract` - 实体提取模型
- `lpmm_rdf_build` - RDF 构建模型

#### [prompts] - AI 提示词配置
```toml
[prompts]
schedule_generation = "..."    # 日程生成提示词
random_event_generation = "..."  # 随机事件生成提示词
emotion_judgment = "..."      # 情绪判断提示词
habit_generation = "..."        # 习惯生成提示词
```

提示词支持变量替换：
- `{current_time}` - 当前时间
- `{current_date}` - 当前日期
- `{day_of_week}` - 星期
- `{is_weekend}` - 是否周末
- `{is_holiday}` - 是否节假日
- `{holiday_name}` - 节日名称
- `{health_status}` - 健康状态
- `{fatigue_level}` - 疲劳度
- `{hunger_level}` - 饥饿度
- `{personality}` - 人格特点
- `{habits}` - 个人习惯
- `{recent_messages}` - 最近消息

#### [schedule] - 日程配置
```toml
[schedule]
regenerate_daily = true                 # 每天重新生成日程
random_event_probability = 0.1          # 随机事件触发概率
illness_system_enabled = true             # 启用生病系统
illness_probability_multiplier = 1.0     # 生病概率倍数
auto_regenerate_on_illness = true        # 生病时自动重新生成日程
```

#### [time_api] - 时间/日期 API 配置
```toml
[time_api]
method = "builtin"    # 时间获取方式（builtin/custom）
url = ""             # 自定义时间 API URL
timeout = 5          # 请求超时（秒）
```

#### [holiday_api] - 节日 API 配置
```toml
[holiday_api]
enabled = true                              # 启用节日检测
url = "https://timor.tech/api/holiday/info/{date}"  # 节日 API URL
cache_duration = 86400                       # 缓存时长（秒）
timeout = 5                                  # 请求超时（秒）
```

#### [habits] - 习惯配置
```toml
[habits]
use_ai_generation = true    # 使用 AI 生成习惯
speaking_habits = []       # 说话习惯
behavior_habits = []       # 行为习惯
interests = []             # 兴趣爱好
```

#### [commands] - 命令配置
```toml
[commands]
enabled = true    # 启用所有命令
```

## 💻 使用方法

### 命令列表

#### `/life_status` - 查询当前状态
显示所有生理状态、当前活动、节日信息和情绪。

**示例**:
```
用户: /life_status
机器人: 📊 我的状态：
😴 睡眠状态: awake
😫 疲劳度: 15/100
🍔 饥饿度: 22/100
❤️ 健康度: 85/100 (healthy)
😊 情绪: calm (30/100)
🏃 当前活动: idle - 空闲
🎉 节日: 无
```

#### `/life_schedule` - 查询日程安排
显示 AI 生成的日程安排。

**示例**:
```
用户: /life_schedule
机器人: 📅 日程安排 (2026-01-13):

⏰ 08:00 - breakfast (早餐) [优先级: 5]
⏰ 09:00 - work (工作) [优先级: 4]
⏰ 12:00 - meal (午餐) [优先级: 5]
⏰ 18:00 - meal (晚餐) [优先级: 5]
⏰ 20:00 - leisure (娱乐) [优先级: 3]
⏰ 23:00 - sleep (睡觉) [优先级: 5]
```

### 工具列表

#### `get_life_simulation_habits` - 获取习惯信息
LLM 可调用此工具获取机器人的个人习惯信息。

**参数**: 无

**返回内容**:
```json
{
  "name": "get_life_simulation_habits",
  "content": "说话习惯: 喜欢用表情, 偶尔使用语气词\n行为习惯: 早起, 爱运动\n兴趣爱好: 音乐, 电影, 游戏\n偏好设置: food_preference: 甜食, music_preference: 流行音乐",
  "habits": {
    "speaking_habits": ["喜欢用表情", "偶尔使用语气词"],
    "behavior_habits": ["早起", "爱运动"],
    "interests": ["音乐", "电影", "游戏"],
    "preferences": {"food_preference": "甜食", "music_preference": "流行音乐"}
  }
}
```

**使用场景**: LLM 可以在生成回复时调用此工具，根据习惯信息调整回复风格。

## 🏥 生病系统

### 健康状态
- **healthy (80-100)**: 健康
- **recovering (60-79)**: 康复中
- **slightly_ill (40-59)**: 轻微不适
- **ill (20-39)**: 生病
- **seriously_ill (0-19)**: 严重生病

### 生病判断因素
AI 会根据以下因素综合判断是否生病：
- 疲劳度（>70 容易生病）
- 饥饿度（>70 容易生病）
- 情绪状态（持续低落容易生病）
- 当前活动
- 人格特点

### 生病后行为
- 自动重新生成符合病情的日程
- 根据健康状态调整活动强度
- 康复后自动恢复正常日程

### 生病配置
```toml
[schedule]
illness_system_enabled = true             # 启用生病系统
illness_probability_multiplier = 1.0     # 生病概率倍数（0.0-2.0）
auto_regenerate_on_illness = true        # 生病时自动重新生成日程
```

## 📁 文件结构

```
plugins/LifeSimulationPlugin/
├── plugin.py              # 插件主文件
├── _manifest.json         # 插件清单
├── config.toml            # 配置文件（包含所有提示词）
├── requirements.txt       # 依赖文件
└── data/                  # 数据目录
    └── state.json        # 状态保存文件
```

## 🔧 配置文件详解

### 提示词配置

所有提示词都在 `config.toml` 的 `[prompts]` 部分：

```toml
[prompts]
# 日程生成提示词
schedule_generation = """你是一个生活规划助手，需要为机器人生成今天的日程安排。
...
"""

# 随机事件生成提示词
random_event_generation = """你是一个生活事件生成器，需要根据当前情况生成一个随机事件。
...
"""

# 情绪判断提示词
emotion_judgment = """你是一个情绪分析助手，需要判断机器人的当前情绪状态。
...
"""

# 习惯生成提示词
habit_generation = """你是一个习惯分析助手，需要根据人格特点生成个人习惯。
...
"""
```

### 首次运行

插件首次运行时，会自动：
1. 检查 `config.toml` 是否存在
2. 如果不存在，创建包含默认提示词的配置文件
3. 如果提示词为空，重新生成提示词

## ❓ 常见问题

### Q: 如何自定义提示词？
A: 直接编辑 `config.toml` 文件中的 `[prompts]` 部分，修改对应的提示词内容。

### Q: 如何调整生病概率？
A: 修改 `[schedule]` 部分的 `illness_probability_multiplier` 值：
- `0.5` - 降低生病概率
- `1.0` - 正常概率
- `2.0` - 提高生病概率

### Q: 如何禁用生病系统？
A: 修改 `[schedule]` 部分的 `illness_system_enabled` 为 `false`。

### Q: 如何使用自定义时间 API？
A: 修改 `[time_api]` 部分：
```toml
[time_api]
method = "custom"
url = "https://worldtimeapi.org/api/timezone/Asia/Shanghai"
timeout = 5
```

### Q: 为什么提示词在配置文件中？
A: 为了让用户可以轻松自定义提示词，而不需要修改代码。首次运行时会自动生成包含默认提示词的配置文件。

### Q: LLM 如何访问习惯信息？
A: LLM 可以调用 `get_life_simulation_habits` 工具获取习惯信息，然后根据习惯调整回复风格。

### Q: 健康度越高越健康吗？
A: 是的，健康度范围是 0-100，数值越高表示越健康。

### Q: 生病后会自动调整日程吗？
A: 是的，如果启用了 `auto_regenerate_on_illness`，生病后会自动重新生成符合病情的日程。

## 📝 更新日志

### v1.1.0 (2026-01-13) - 增强版本
- ✅ 移除 i18n 系统
- ✅ 提示词移到配置文件中
- ✅ 支持 9 种 AI 模型配置类型
- ✅ 支持自定义时间/日期 API
- ✅ 实现生病系统
- ✅ 修正健康度逻辑（越高越健康）
- ✅ 生病后自动重新生成日程
- ✅ 添加 GetHabitsTool 工具组件
- ✅ 配置文件更易于人类修改和查看

### v1.0.0 (2026-01-13) - 初始版本
- ✅ 初始版本发布（AI 驱动架构）
- ✅ 实现AI驱动的日程生成系统
- ✅ 实现AI驱动的随机事件生成
- ✅ 实现健康状态由事件决定
- ✅ 实现习惯系统（配置+AI生成）
- ✅ 实现节日API集成
- ✅ 实现AI驱动的情绪判断
- ✅ 实现可编辑的AI提示词系统
- ✅ 实现生理状态模拟
- ✅ 实现 2 个 Action 组件
- ✅ 实现 2 个 Command 组件
- ✅ 实现 4 个 EventHandler 组件

## 🤝 贡献

欢迎贡献！请遵循以下步骤：

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

MIT License - 详见 [LICENSE](/LICENSE) 文件

## 👥 作者

GLM-4.7和讨论出这个项目的所有群友

## 🙏 致谢

感谢所有为本项目做出贡献的开发者！