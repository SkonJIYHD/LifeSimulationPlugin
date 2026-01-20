# LifeSimulationPlugin - 事件及人体模拟插件

一个基于 AI 驱动的事件及人体模拟插件，让机器人具有真实人类的生理状态、日常活动、社交行为和环境感知能力，使机器人更加拟人化和生动。

> 本 README 由 GLM-4.7 编写，Claude sonnet 协助润色。
[![许可证](https://img.shields.io/badge/许可证-AGPL--3.0-green.svg)](/LICENSE)
[![MaiBot](https://img.shields.io/badge/MaiBot-0.12.0+-orange.svg)](https://github.com/MaiM-with-u/MaiBot)

## 🚀 快速开始

### 安装

1. 将插件目录放置在 `plugins/LifeSimulationPlugin/`
2. 在 WebUI 中启用插件
3. 首次运行自动生成配置文件
4. 根据需要调整 `config.toml` 配置

### 基础命令

```
/life_status     # 查询当前状态
/life_schedule   # 查询日程安排
/life_social     # 查询社交网络
```

## ✨ 核心特性

<details>
<summary><b>🤖 AI 驱动系统</b></summary>

- **日程生成**: AI 根据人格、习惯和状态生成个性化日程
- **随机事件**: AI 根据情境生成随机事件
- **情绪判断**: AI 多维度判断情绪状态
- **习惯生成**: AI 根据人格特点生成个人习惯
- **疾病诊断**: AI 自动诊断疾病并调整日程

</details>

<details>
<summary><b>😴 完整睡眠系统</b></summary>

- **6种睡眠状态**: 清醒 → 困倦 → 入睡中 → 浅睡 → 深睡 → 醒来中
- **日程联动**: 根据日程自动入睡/醒来
- **智能回复**: AI 判断是否在睡眠中回复
- **打扰唤醒**: 重要消息/紧急关键词可能唤醒
- **状态恢复**: 睡眠期间疲劳度和健康度自动恢复

</details>

<details>
<summary><b>👥 社交网络系统</b></summary>

- **9种关系类型**: 陌生人、熟人、朋友、好友、挚友、家人、伴侣、敌人、拉黑
- **亲密度系统**: 互动增长、时间衰减
- **AI判断**: AI 根据互动内容智能调整亲密度
- **关系管理**: LLM 可设置用户关系类型
- **个性化行为**: 根据关系调整回复风格

</details>

<details>
<summary><b>🏥 生病系统</b></summary>

- **AI诊断**: 自动诊断疾病名称、原因、症状、治疗
- **健康状态**: 5个等级（健康 → 康复中 → 轻微不适 → 生病 → 严重生病）
- **日程调整**: 生病后自动生成包含医疗活动的日程
- **多维判断**: 根据疲劳、饥饿、情绪等综合判断

</details>

<details>
<summary><b>🔧 工具系统</b></summary>

LLM 可调用以下工具获取信息:

- `get_life_simulation_habits` - 获取个人习惯
- `get_social_network_info` - 获取社交网络信息
- `set_user_relationship` - 设置用户关系类型
- `get_life_simulation_schedule` - 获取日程信息
- `get_life_simulation_status` - 获取当前状态

</details>

## ⚙️ 配置说明

<details>
<summary><b>AI 模型配置</b></summary>

支持 9 种模型配置类型,可指定具体模型:

```toml
[ai]
schedule_model = "replyer:gpt-4"           # 日程生成
event_model = "tool_use:gpt-4-turbo"       # 随机事件
emotion_model = "planner:claude-3-sonnet"  # 情绪判断
habit_model = "replyer"                    # 习惯生成
temperature = 0.7
max_tokens = 2500
```

**可用模型类型**: `utils`, `tool_use`, `replyer`, `planner`, `vlm`, `voice`, `embedding`, `lpmm_entity_extract`, `lpmm_rdf_build`

</details>

<details>
<summary><b>睡眠系统配置</b></summary>

```toml
[sleep]
enabled = true                     # 启用睡眠系统
min_sleep_hours = 4                # 最短睡眠时间
max_sleep_hours = 10               # 最长睡眠时间

# AI自动回复
ai_reply_enabled = true            # 启用AI判断回复
ai_reply_probability = 0.3         # 回复概率

# 打扰唤醒
disturbance_enabled = true         # 启用打扰唤醒
light_sleep_wake_prob = 0.5        # 浅睡唤醒概率
intimacy_wake_threshold = 60       # 亲密度唤醒阈值
emergency_keywords = "紧急,救命,快点,重要,急事"  # 紧急关键词
```

</details>

<details>
<summary><b>社交网络配置</b></summary>

```toml
[social_network]
enabled = true                      # 启用社交网络
intimacy_growth_method = "ai"       # 亲密度增长方式 (ai/probability/fixed)
intimacy_ai_model = "replyer"       # AI判断模型
intimacy_decay_rate = 0.1           # 衰减率
decay_interval = 86400              # 衰减间隔(秒)
```

**亲密度增长方式**:
- `ai` - AI根据互动内容判断 (推荐)
- `probability` - 按概率增长
- `fixed` - 固定增长

</details>

<details>
<summary><b>功能开关配置</b></summary>

```toml
[features]
startup_enabled = true              # 启动处理器
state_update_enabled = true         # 状态更新
message_event_enabled = true        # 消息事件
social_network_enabled = true       # 社交网络
sleep_system_enabled = true         # 睡眠系统
activity_execution_enabled = true   # 活动执行
event_handling_enabled = true       # 随机事件
commands_enabled = true             # 命令功能
tools_enabled = true                # 工具功能
```

</details>

<details>
<summary><b>其他配置</b></summary>

```toml
[schedule]
regenerate_daily = true                  # 每天重新生成日程
illness_system_enabled = true            # 启用生病系统
auto_regenerate_on_illness = true        # 生病时自动重新生成日程

[state]
message_state_update_probability = 0.7   # 消息状态更新概率

[reply_reduction]
enabled = true                           # 回复频率降低
reduction_activities = "work,study,exercise,medical"
reduction_factor = 0.5                   # 降低因子
```

</details>

## 📖 使用指南

<details>
<summary><b>命令列表</b></summary>

### `/life_status` - 查询当前状态

显示所有生理状态、当前活动、节日信息和情绪。

```
📊 我的状态：
😴 睡眠状态: awake
😫 疲劳度: 15/100
🍔 饥饿度: 22/100
❤️ 健康度: 85/100 (healthy)
😊 情绪: calm (30/100)
🏃 当前活动: idle - 空闲
🎉 节日: 无
```

### `/life_schedule` - 查询日程安排

显示 AI 生成的日程安排。

```
📅 日程安排 (2026-01-13):

⏰ 08:00-09:00 breakfast (早餐) [优先级: 5]
⏰ 09:00-12:00 work (工作) [优先级: 4]
⏰ 12:00-13:00 meal (午餐) [优先级: 5]
...
```

### `/life_social` - 查询社交网络

显示社交网络中的用户关系信息。

```
👥 社交网络概览（共 3 人）：

1. 张三
   🔗 朋友 | 💕 45/100 | 💬 12次互动

2. 李四
   🔗 熟人 | 💕 25/100 | 💬 5次互动
...
```

</details>

<details>
<summary><b>LLM 工具调用</b></summary>

### `get_life_simulation_habits` - 获取习惯信息

LLM 可调用此工具获取机器人的个人习惯,根据习惯调整回复风格。

### `get_social_network_info` - 获取社交网络信息

LLM 可调用此工具获取用户关系、亲密度和互动历史,根据关系调整回复。

### `set_user_relationship` - 设置用户关系

LLM 可根据互动内容设置用户关系类型,包括敌人和拉黑。

**参数**:
- `user_id` - 用户ID
- `relationship_type` - 关系类型 (stranger/acquaintance/friend/close_friend/best_friend/family/partner/enemy/blocked)
- `reason` - 设置原因

### `get_life_simulation_schedule` - 获取日程信息

LLM 可调用此工具了解当前正在做什么,根据活动调整回复。

### `get_life_simulation_status` - 获取状态信息

LLM 可调用此工具了解当前状态,根据疲劳度、饥饿度、情绪等调整回复。

</details>

## 📝 更新历史

<details>
<summary><b>v1.7.0 (2026-01-21) - 稳定性增强版本</b></summary>

### 主要更新
- ✅ 添加功能开关配置 `[features]`,所有主要功能可独立开关
- ✅ 优化时间显示,显示昨天/今天/明天/后天的日期
- ✅ 增强JSON解析:正则提取、中文标点替换、尾随逗号修复
- ✅ 动态max_tokens计算,防止JSON截断(自动调整到3500 tokens)
- ✅ 修复睡眠处理器日程同步:双向同步(入睡/唤醒)
- ✅ 修复数据库初始化:确保父目录存在
- ✅ 修复跨天时间处理:支持23:00-07:00等跨午夜时间段
- ✅ 增强社交网络工具:支持user_name查找
- ✅ 修复Union类型导入

### 技术细节
- JSON解析支持AI包裹文本的提取
- 中文标点自动转换为英文标点
- 睡眠状态与日程完全同步
- 数据库目录自动创建
- 跨天时间正确处理

</details>

<details>
<summary><b>v1.6.0 (2026-01-15) - 工具修复与完善版本</b></summary>

- ✅ 修复工具参数格式,符合BaseTool要求
- ✅ 完整睡眠系统:6种状态、日程联动、AI回复、打扰唤醒
- ✅ 添加GetScheduleTool和GetStatusTool
- ✅ JSON解析智能修复
- ✅ 习惯持久化
- ✅ 疾病诊断系统
- ✅ 日程时间段形式
- ✅ 紧急关键词可配置
- ✅ Dream消息过滤
- ✅ 回复频率降低功能

</details>

<details>
<summary><b>v1.5.0 (2026-01-14) - 社交网络版本</b></summary>

- ✅ 实现社交网络功能
- ✅ 9种关系类型
- ✅ 亲密度系统
- ✅ 自动互动记录

</details>

<details>
<summary><b>v1.4.0 (2026-01-14) - 亲密度优化版本</b></summary>

- ✅ AI判断亲密度增长
- ✅ 支持3种增长方式
- ✅ 添加intimacy_judgment提示词

</details>

<details>
<summary><b>v1.3.0 (2026-01-14) - 关系管理增强版本</b></summary>

- ✅ 添加SetRelationshipTool
- ✅ AI可设置敌人和拉黑
- ✅ 关系变更原因跟踪

</details>

<details>
<summary><b>v1.2.0 (2026-01-14) - 优化版本</b></summary>

- ✅ 概率更新机制
- ✅ 避免状态过快增长

</details>

<details>
<summary><b>v1.1.0 (2026-01-13) - 增强版本</b></summary>

- ✅ 移除i18n系统
- ✅ 提示词移到配置文件
- ✅ 9种AI模型配置
- ✅ 自定义时间API
- ✅ 生病系统

</details>

<details>
<summary><b>v1.0.0 (2026-01-13) - 初始版本</b></summary>

- ✅ AI驱动架构
- ✅ 日程生成
- ✅ 随机事件
- ✅ 习惯系统
- ✅ 节日API
- ✅ 情绪判断

</details>

## 🤝 贡献

欢迎通过以下方式参与贡献:

- **Pull Requests**: 功能改进、bug修复、文档更新
- **Issues**: 问题反馈和建议
- **分支开发**: 创建新分支进行开发

## 📄 许可证

AGPL-3.0 LICENSE - 详见 [LICENSE](/LICENSE) 文件

## 👥 作者

GLM-4.7,Claude sonnet 4.5 和讨论出这个项目的所有群友

## 🙏 致谢

感谢所有为本项目做出贡献的开发者!