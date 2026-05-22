# components/commands.py
# 纯业务逻辑函数，不含任何 SDK 装饰器
from __future__ import annotations
import logging
from utils.time_helper import to_local, now_utc

logger = logging.getLogger(__name__)


async def build_life_status_text(manager, config) -> str:
    snap = manager.snapshot()
    tz = config.plugin.timezone
    now = now_utc()
    lines = [
        f"Sleep: {snap.sleep_state.value}",
        f"Activity: {snap.current_activity.value}",
        f"Schedule date: {snap.schedule_generated_date}",
        f"Items: {len(snap.today_schedule)}",
    ]
    for item in snap.today_schedule:
        if item.start_time <= now < item.end_time:
            local_s = to_local(item.start_time, tz).strftime("%H:%M")
            local_e = to_local(item.end_time, tz).strftime("%H:%M")
            lines.append(f"Now: {local_s}-{local_e} {item.description}")
            break
    return "\n".join(lines)
