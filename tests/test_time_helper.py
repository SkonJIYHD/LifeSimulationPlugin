from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from utils.time_helper import (
    now_utc, to_local, local_time_to_utc_datetime,
    local_date_str, is_in_quiet_hours
)

def test_now_utc_is_aware():
    assert now_utc().tzinfo == timezone.utc

def test_to_local():
    utc = datetime(2026, 5, 22, 15, 0, 0, tzinfo=timezone.utc)
    assert to_local(utc, "Asia/Shanghai").hour == 23

def test_local_time_to_utc():
    d = date(2026, 5, 22)
    r = local_time_to_utc_datetime(d, "23:00", "Asia/Shanghai")
    assert r.tzinfo == timezone.utc and r.hour == 15

def test_local_date_str():
    r = local_date_str("Asia/Shanghai")
    assert len(r) == 10 and r[4] == "-"

def test_quiet_hours_inside():
    # 18:00 UTC = 02:00 next day CST, in quiet 23:00-07:00
    utc = datetime(2026, 5, 22, 18, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(utc, "23:00", "07:00", "Asia/Shanghai") is True

def test_quiet_hours_outside():
    # 06:00 UTC = 14:00 CST, not in quiet 23:00-07:00
    utc = datetime(2026, 5, 22, 6, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(utc, "23:00", "07:00", "Asia/Shanghai") is False
