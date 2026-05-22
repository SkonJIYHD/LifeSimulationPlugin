from datetime import datetime, timezone, time, date
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def to_local(dt: datetime, tz_name: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz_name))


def local_time_to_utc_datetime(d: date, time_str: str, tz_name: str) -> datetime:
    h, m = map(int, time_str.split(":"))
    local_dt = datetime(d.year, d.month, d.day, h, m, 0, tzinfo=ZoneInfo(tz_name))
    return local_dt.astimezone(timezone.utc)


def local_date_str(tz_name: str) -> str:
    return datetime.now(tz=ZoneInfo(tz_name)).date().isoformat()


def is_in_quiet_hours(now: datetime, start_str: str, end_str: str, tz_name: str) -> bool:
    local_t = to_local(now, tz_name).time().replace(second=0, microsecond=0)
    h, m = map(int, start_str.split(":"))
    start = time(h, m)
    h, m = map(int, end_str.split(":"))
    end = time(h, m)
    if start <= end:
        return start <= local_t < end
    return local_t >= start or local_t < end
