# systems/schedule.py
from __future__ import annotations
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Any, TYPE_CHECKING

from core.state import ActivityType, ScheduleItem
from utils.time_helper import local_time_to_utc_datetime, now_utc

if TYPE_CHECKING:
    from core.state import LifeStateSnapshot

logger = logging.getLogger(__name__)

# fallback 默认时段：骨架之外的时间用这些填充
_FALLBACK_SLOTS = [
    ("07:00", "09:00", ActivityType.STUDYING, "Morning study"),
    ("09:00", "12:00", ActivityType.WORKING, "Morning work"),
    ("13:00", "18:00", ActivityType.WORKING, "Afternoon work"),
    ("19:00", "22:00", ActivityType.LEISURE, "Evening leisure"),
]


def build_skeleton(d: date, cfg: Any, tz: str) -> list[ScheduleItem]:
    """
    构建固定骨架 items（睡眠、三餐），使用 timezone-aware UTC datetime。
    睡眠跨天（如 23:00~07:00）拆为两段：
      - 凌晨部分：00:00 local -> sleep_end local (当天)
      - 夜间部分：sleep_start local -> 00:00 local (次日)
    """
    items = []

    # 睡眠：跨天处理
    sleep_end_today = local_time_to_utc_datetime(d, cfg.sleep_end, tz)
    sleep_start_today = local_time_to_utc_datetime(d, cfg.sleep_start, tz)
    local_midnight = local_time_to_utc_datetime(d, "00:00", tz)
    local_midnight_next = local_time_to_utc_datetime(d + timedelta(days=1), "00:00", tz)

    # 凌晨部分：00:00 local today ~ sleep_end local today
    if sleep_end_today > local_midnight:
        items.append(ScheduleItem(
            start_time=local_midnight,
            end_time=sleep_end_today,
            activity=ActivityType.SLEEPING,
            description="Sleep (morning)",
            is_skeleton=True,
        ))
    # 夜间部分：sleep_start today ~ midnight next day (local)
    if sleep_start_today < local_midnight_next:
        items.append(ScheduleItem(
            start_time=sleep_start_today,
            end_time=local_midnight_next,
            activity=ActivityType.SLEEPING,
            description="Sleep (evening)",
            is_skeleton=True,
        ))

    # 三餐
    for start_key, end_key, desc in [
        (cfg.breakfast_start, cfg.breakfast_end, "Breakfast"),
        (cfg.lunch_start, cfg.lunch_end, "Lunch"),
        (cfg.dinner_start, cfg.dinner_end, "Dinner"),
    ]:
        start = local_time_to_utc_datetime(d, start_key, tz)
        end = local_time_to_utc_datetime(d, end_key, tz)
        items.append(ScheduleItem(
            start_time=start, end_time=end,
            activity=ActivityType.EATING, description=desc,
            is_skeleton=True,
        ))

    return sorted(items, key=lambda x: x.start_time)


def build_fallback_schedule(d: date, cfg: Any, tz: str) -> list[ScheduleItem]:
    """骨架 + 预设 fallback 时段，AI 不可用时使用。"""
    skeleton = build_skeleton(d, cfg, tz)
    skeleton_ranges = [(i.start_time, i.end_time) for i in skeleton]
    result = list(skeleton)

    for start_str, end_str, act, desc in _FALLBACK_SLOTS:
        start = local_time_to_utc_datetime(d, start_str, tz)
        end = local_time_to_utc_datetime(d, end_str, tz)
        overlap = any(s < end and e > start for s, e in skeleton_ranges)
        if not overlap and start < end:
            result.append(ScheduleItem(
                start_time=start, end_time=end,
                activity=act, description=desc,
            ))

    return sorted(result, key=lambda x: x.start_time)


def get_current_activity(snap: LifeStateSnapshot, now: datetime) -> ActivityType:
    """返回 now 对应的当前活动，无匹配返回 OTHER。"""
    for item in snap.today_schedule:
        if item.start_time <= now < item.end_time:
            return item.activity
    return ActivityType.OTHER


def calc_next_transition(
    snap: LifeStateSnapshot, now: datetime
) -> tuple[datetime, ActivityType]:
    """
    返回 (下一个切换时间 UTC, 切换后活动)。
    如果没有更多切换点，返回 now + 1h, OTHER。
    """
    candidates: list[tuple[datetime, ActivityType]] = []
    current_act = get_current_activity(snap, now)

    for item in snap.today_schedule:
        if item.start_time > now:
            candidates.append((item.start_time, item.activity))
        if item.end_time > now and item.activity == current_act:
            candidates.append((item.end_time, ActivityType.OTHER))

    if not candidates:
        return now + timedelta(hours=1), ActivityType.OTHER

    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def get_missed_transitions(
    snap: LifeStateSnapshot, now: datetime
) -> list[tuple[ActivityType, datetime]]:
    """
    返回 last_transition_processed_at 到 now 之间所有未处理的切换点，按时间排序。
    每个切换点：item.start_time（进入该活动）或 item.end_time（离开该活动 → OTHER）
    去除相邻重复活动。
    """
    last = snap.last_transition_processed_at
    missed: list[tuple[ActivityType, datetime]] = []

    for item in snap.today_schedule:
        if last < item.start_time <= now:
            missed.append((item.activity, item.start_time))
        if last < item.end_time <= now:
            missed.append((ActivityType.OTHER, item.end_time))

    missed.sort(key=lambda x: x[1])

    # 去重相邻同活动
    result: list[tuple[ActivityType, datetime]] = []
    for act, t in missed:
        if not result or result[-1][0] != act:
            result.append((act, t))
    return result


class ScheduleSystem:
    def __init__(self, manager: Any, db: Any, budget: Any, ctx: Any, config: Any):
        self._manager = manager
        self._db = db
        self._budget = budget
        self._ctx = ctx
        self._config = config

    async def generate(self, date_str: str, is_recovery: bool = False) -> None:
        from utils.llm_helper import generate_json

        d = date.fromisoformat(date_str)
        tz = self._config.plugin.timezone
        skeleton = build_skeleton(d, self._config.schedule, tz)

        # 获取人格信息（失败时降级为空字符串）
        personality = ""
        try:
            personality = await self._ctx.person.get_value("self", "personality") or ""
        except Exception:
            pass

        skeleton_desc = "\n".join(
            f"{item.start_time.strftime('%H:%M')} - {item.end_time.strftime('%H:%M')}: {item.description}"
            for item in skeleton
        )

        prompt_tmpl = getattr(getattr(self._config, "prompts", None), "schedule_generation", "")
        if prompt_tmpl:
            prompt_text = (prompt_tmpl
                           .replace("{personality}", personality)
                           .replace("{date}", date_str)
                           .replace("{skeleton}", skeleton_desc))
        else:
            prompt_text = (
                f"You are scheduling a day for an AI character.\n"
                f"Personality: {personality or 'friendly and curious'}\n"
                f"Date: {date_str}\n"
                f"Fixed schedule (do NOT modify these time slots):\n{skeleton_desc}\n\n"
                f"Fill in the remaining free time with realistic activities. "
                f"Return JSON with this exact schema:\n"
                f'{{ "activities": [ {{'
                f'"start": "HH:MM", "end": "HH:MM", '
                f'"activity": "studying|working|exercising|leisure|other", '
                f'"description": "short description"}} ] }}'
            )

        schema = {
            "required": ["activities"],
            "properties": {"activities": {"type": "array"}},
        }

        result = await generate_json(
            self._ctx,
            prompt=[{"role": "user", "content": prompt_text}],
            schema=schema,
            budget_key="schedule",
            budget=self._budget,
            timeout=getattr(getattr(self._config, "llm", None), "timeout_seconds", 30),
            max_retries=getattr(getattr(self._config, "llm", None), "max_retries", 2),
        )

        if result is None:
            logger.warning("Schedule generation failed, using fallback for %s", date_str)
            items = build_fallback_schedule(d, self._config.schedule, tz)
        else:
            items = list(skeleton)
            skeleton_ranges = [(i.start_time, i.end_time) for i in skeleton]
            for act_data in result.get("activities", []):
                try:
                    start = local_time_to_utc_datetime(d, act_data["start"], tz)
                    end = local_time_to_utc_datetime(d, act_data["end"], tz)
                    act = ActivityType(act_data.get("activity", "other"))
                    desc = act_data.get("description", "")
                    overlap = any(s < end and e > start for s, e in skeleton_ranges)
                    if not overlap and start < end:
                        items.append(ScheduleItem(
                            start_time=start, end_time=end,
                            activity=act, description=desc,
                        ))
                except Exception as e:
                    logger.warning("Skipping invalid schedule item: %s", e)
            items.sort(key=lambda x: x.start_time)

        await self._manager.set_schedule(items, is_repair=is_recovery)
        await self._manager.set_schedule_generated_date(date_str)
        logger.info("Schedule generated for %s: %d items", date_str, len(items))
