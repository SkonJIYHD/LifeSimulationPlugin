# config_model.py — Life Simulation Plugin v2.0
# 声明式配置模型，Runner 自动生成 WebUI Schema 并补齐缺失字段。
from __future__ import annotations

from maibot_sdk import PluginConfigBase, Field


class PluginSection(PluginConfigBase):
    """基础设置"""
    __ui_label__ = "基础设置"

    enabled: bool = Field(default=True, description="是否启用插件")
    timezone: str = Field(default="Asia/Shanghai", description="时区（如 Asia/Shanghai）")
    max_recent_events: int = Field(default=20, description="内存中保留的最近事件条数")


class ScheduleSection(PluginConfigBase):
    """日程设置"""
    __ui_label__ = "日程设置"

    sleep_start: str = Field(default="23:00", description="睡眠开始时间（HH:MM）")
    sleep_end: str = Field(default="07:00", description="睡眠结束时间（HH:MM）")
    breakfast_start: str = Field(default="07:30", description="早餐开始时间（HH:MM）")
    breakfast_end: str = Field(default="08:00", description="早餐结束时间（HH:MM）")
    lunch_start: str = Field(default="12:00", description="午餐开始时间（HH:MM）")
    lunch_end: str = Field(default="12:30", description="午餐结束时间（HH:MM）")
    dinner_start: str = Field(default="18:00", description="晚餐开始时间（HH:MM）")
    dinner_end: str = Field(default="18:30", description="晚餐结束时间（HH:MM）")


class SleepSection(PluginConfigBase):
    """睡眠系统"""
    __ui_label__ = "睡眠系统"

    sleepy_duration_minutes: int = Field(default=30, description="困倦过渡时长（分钟）")
    waking_duration_minutes: int = Field(default=15, description="苏醒过渡时长（分钟）")


class FrequencySection(PluginConfigBase):
    """发言频率调整"""
    __ui_label__ = "发言频率调整"

    sleeping: float = Field(default=-1.0, description="睡眠中的频率调整值（-1.0 = 完全屏蔽）")
    exercising: float = Field(default=-0.6, description="运动中的频率调整值")
    studying: float = Field(default=-0.4, description="学习中的频率调整值")
    working: float = Field(default=-0.4, description="工作中的频率调整值")
    eating: float = Field(default=-0.2, description="进食中的频率调整值")
    leisure: float = Field(default=0.0, description="休闲时的频率调整值")
    other: float = Field(default=0.0, description="其他活动的频率调整值")


class RelationSection(PluginConfigBase):
    """关系网设置"""
    __ui_label__ = "关系网设置"

    min_update_interval_minutes: int = Field(default=30, description="印象最短更新间隔（分钟）")
    dirty_queue_max_size: int = Field(default=500, description="待更新队列最大长度")
    dirty_queue_ttl_seconds: int = Field(default=7200, description="队列条目 TTL（秒）")


class ProactiveSection(PluginConfigBase):
    """主动行为设置"""
    __ui_label__ = "主动行为设置"

    enabled: bool = Field(default=True, description="是否启用主动发消息")
    schedule_transition_probability: float = Field(default=0.4, description="日程切换时主动触发概率")
    waking_probability_factor: float = Field(default=0.3, description="苏醒时概率倍率")
    global_cooldown_minutes: int = Field(default=30, description="全局冷却时间（分钟）")
    per_group_cooldown_minutes: int = Field(default=60, description="单群组冷却时间（分钟）")
    quiet_hours_start: str = Field(default="23:00", description="静默时段开始（HH:MM）")
    quiet_hours_end: str = Field(default="07:00", description="静默时段结束（HH:MM）")
    daily_limit: int = Field(default=5, description="每日主动消息上限")
    max_consecutive: int = Field(default=2, description="最大连续主动次数")
    consecutive_reset_after_minutes: int = Field(default=120, description="连续计数重置间隔（分钟）")
    score_threshold: float = Field(default=0.7, description="触发意图分析的分数阈值")
    debounce_seconds: int = Field(default=5, description="防抖延迟（秒）")


class LLMSection(PluginConfigBase):
    """LLM 调用设置"""
    __ui_label__ = "LLM 调用设置"

    timeout_seconds: int = Field(default=30, description="LLM 请求超时（秒）")
    max_retries: int = Field(default=2, description="最大重试次数")
    max_repair_attempts: int = Field(default=2, description="JSON 修复最大尝试次数")


class BudgetSection(PluginConfigBase):
    """调用预算"""
    __ui_label__ = "调用预算"

    llm_schedule_per_day: int = Field(default=3, description="日程生成每天最多调用 LLM 次数")
    llm_impression_per_hour: int = Field(default=50, description="印象更新每小时最多调用 LLM 次数")
    llm_proactive_intent_per_hour: int = Field(default=20, description="主动意图判断每小时最多调用 LLM 次数")
    dirty_flush_per_heartbeat: int = Field(default=10, description="每次心跳最多落盘条目数")


class DBSection(PluginConfigBase):
    """数据库设置"""
    __ui_label__ = "数据库设置"

    checkpoint_interval_minutes: int = Field(default=60, description="WAL checkpoint 间隔（分钟）")
    max_size_mb: int = Field(default=50, description="数据库最大体积（MB）")


class HeartbeatSection(PluginConfigBase):
    """心跳设置"""
    __ui_label__ = "心跳设置"

    interval_seconds: int = Field(default=600, description="心跳间隔（秒）")


class ToolSection(PluginConfigBase):
    """Tool 输出设置"""
    __ui_label__ = "Tool 输出设置"

    upcoming_count: int = Field(default=3, description="get_today_schedule 返回的即将到来条目数")
    upcoming_hours_ahead: int = Field(default=4, description="get_today_schedule 的前瞻时间范围（小时）")


class PromptsSection(PluginConfigBase):
    """自定义提示词（留空则使用内置模板）"""
    __ui_label__ = "自定义提示词"

    schedule_generation: str = Field(
        default="",
        description="日程生成提示词（可用变量：{personality}, {date}, {skeleton}）",
        json_schema_extra={"placeholder": "留空使用内置提示词"},
    )
    impression_update: str = Field(
        default="",
        description="印象更新提示词（可用变量：{personality}, {person_name}, {recent_messages}, {old_impression}）",
        json_schema_extra={"placeholder": "留空使用内置提示词"},
    )
    proactive_intent: str = Field(
        default="",
        description="主动意图判断提示词（可用变量：{state}, {activity}, {description}）",
        json_schema_extra={"placeholder": "留空使用内置提示词"},
    )


class LifeSimConfig(PluginConfigBase):
    """Life Simulation 插件完整配置"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    schedule: ScheduleSection = Field(default_factory=ScheduleSection)
    sleep: SleepSection = Field(default_factory=SleepSection)
    frequency: FrequencySection = Field(default_factory=FrequencySection)
    relation: RelationSection = Field(default_factory=RelationSection)
    proactive: ProactiveSection = Field(default_factory=ProactiveSection)
    llm: LLMSection = Field(default_factory=LLMSection)
    budget: BudgetSection = Field(default_factory=BudgetSection)
    db: DBSection = Field(default_factory=DBSection)
    heartbeat: HeartbeatSection = Field(default_factory=HeartbeatSection)
    tool: ToolSection = Field(default_factory=ToolSection)
    prompts: PromptsSection = Field(default_factory=PromptsSection)
