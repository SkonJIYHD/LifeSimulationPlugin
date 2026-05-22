# components/apis.py
# DTO 定义和纯逻辑函数，不含任何 SDK 装饰器
from __future__ import annotations
import dataclasses
import logging
from utils.hint_helper import affinity_to_hint
from utils.time_helper import to_local

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class LifeStateDTO_v1:
    schema_version: str = "v1"
    sleep_state: str = ""
    current_activity: str = ""
    schedule_generated_date: str = ""


_DTO_BUILDERS = {
    "v1": lambda snap: LifeStateDTO_v1(
        sleep_state=snap.sleep_state.value,
        current_activity=snap.current_activity.value,
        schedule_generated_date=snap.schedule_generated_date,
    ),
}


def build_state_dto(snap, schema_version: str = "v1") -> dict:
    builder = _DTO_BUILDERS.get(schema_version)
    if builder is None:
        return {"error": f"Unknown schema_version: {schema_version}"}
    return dataclasses.asdict(builder(snap))


def build_schedule_list(snap, tz: str) -> list[dict]:
    return [
        {
            "start": to_local(item.start_time, tz).strftime("%H:%M"),
            "end": to_local(item.end_time, tz).strftime("%H:%M"),
            "activity": item.activity.value,
            "description": item.description,
        }
        for item in snap.today_schedule
    ]


async def get_impression_for_api(db, person_id: str) -> dict | None:
    imp = await db.get_impression(person_id)
    if imp is None:
        return None
    return {
        "traits": imp.get("traits", []),
        "affinity_hint": affinity_to_hint(imp.get("affinity", 0.5)),
    }
