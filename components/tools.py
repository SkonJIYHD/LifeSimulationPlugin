# components/tools.py
# 纯业务逻辑函数，不含任何 SDK 装饰器
from __future__ import annotations
import logging
from datetime import timedelta
from core.state import SleepState
from utils.hint_helper import build_status_hint, affinity_to_hint
from utils.time_helper import to_local, now_utc

logger = logging.getLogger(__name__)


async def get_life_state_data(manager) -> dict:
    snap = manager.snapshot()
    desc = ""
    now = now_utc()
    for item in snap.today_schedule:
        if item.start_time <= now < item.end_time:
            desc = item.description
            break
    return {
        "status_hint": build_status_hint(
            snap.current_activity.value, snap.sleep_state.value, desc
        ),
        "current_activity": snap.current_activity.value,
        "sleep_state": snap.sleep_state.value,
        "can_chat": snap.sleep_state != SleepState.SLEEPING,
    }


async def get_schedule_data(manager, config) -> dict:
    snap = manager.snapshot()
    tz = config.plugin.timezone
    now = now_utc()
    current_item = None
    upcoming = []
    for item in snap.today_schedule:
        local_start = to_local(item.start_time, tz).strftime("%H:%M")
        local_end = to_local(item.end_time, tz).strftime("%H:%M")
        time_str = f"{local_start}-{local_end}"
        if item.start_time <= now < item.end_time:
            current_item = {"time": time_str, "description": item.description}
        elif item.start_time > now:
            hours_ahead = getattr(config.tool, "upcoming_hours_ahead", 4)
            count = getattr(config.tool, "upcoming_count", 3)
            if (item.start_time - now) <= timedelta(hours=hours_ahead):
                if len(upcoming) < count:
                    upcoming.append({"time": time_str, "description": item.description})
    return {"current_item": current_item, "upcoming": upcoming}


async def get_impression_data(ctx, db, person_name: str) -> dict | None:
    try:
        person_id = await ctx.person.get_id_by_name(person_name)
    except Exception:
        return None
    if not person_id:
        return None
    imp = await db.get_impression(person_id)
    if imp is None:
        return None
    return {
        "traits": imp.get("traits", []),
        "affinity_hint": affinity_to_hint(imp.get("affinity", 0.5)),
    }
