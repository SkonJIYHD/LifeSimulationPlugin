# Life Simulation Plugin v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完全重写 Life Simulation 插件，基于 maibot-plugin-sdk 2.0，实现日程、睡眠、频率控制、关系网、主动行为五大系统。

**Architecture:** 多模块分层架构：utils（工具层）→ core（状态/数据库/调度）→ systems（业务系统）→ components（SDK 组件）→ plugin.py（入口集成）。所有系统通过 LifeStateManager 共享状态，systems 之间禁止互相 import，所有副作用由 orchestrator 统一 dispatch。

**Tech Stack:** Python 3.11+, maibot-plugin-sdk 2.0, aiosqlite 0.20+, pytest, pytest-asyncio

---

## 文件结构总览

```
life-simulation/
├── _manifest.json
├── plugin.py
├── config.toml
├── requirements.txt
├── core/
│   ├── __init__.py
│   ├── state.py          # LifeStateManager, LifeStateSnapshot, LifeState, enums, dataclasses
│   ├── database.py       # Database（读写分离双连接，single writer queue，WAL）
│   ├── orchestrator.py   # Orchestrator, BackgroundTaskRegistry, StreamRegistry
│   └── budget.py         # ResourceBudget（LLM/dirty flush 预算，daily 持久化）
├── systems/
│   ├── __init__.py
│   ├── schedule.py       # ScheduleSystem（AI 生成日程，calc_next_transition，get_missed_transitions）
│   ├── sleep.py          # derive_sleep_state（纯函数）
│   ├── relation.py       # RelationSystem（DirtyQueue，flush_dirty_impressions，proactive_score）
│   └── proactive.py      # ProactiveSystem（ProactiveGuard，trigger，check_score_trigger）
├── components/
│   ├── __init__.py
│   ├── hooks.py          # HookHandler（chat.receive.before_process + after_process）
│   ├── tools.py          # Tool（get_life_state, get_today_schedule, get_person_impression）
│   ├── commands.py       # Command（/life_status）
│   └── apis.py           # API（life_sim.get_*，显式 DTO）
└── utils/
    ├── __init__.py
    ├── llm_helper.py     # generate_json（timeout/retry/schema validate/budget check）
    ├── time_helper.py    # now_utc, to_local, local_time_to_utc_datetime, local_date_str, is_in_quiet_hours
    └── hint_helper.py    # _build_status_hint, _affinity_to_hint（tools.py 和 apis.py 共用）

tests/
├── conftest.py
├── test_time_helper.py
├── test_sleep.py
├── test_state.py
├── test_database.py
├── test_schedule.py
├── test_relation.py
├── test_proactive.py
├── test_budget.py
└── test_hooks.py
```

---

## Phase A：基础层

### Task A1: 项目脚手架

**Files:**
- Create: `requirements.txt`, `_manifest.json`, `config.toml`
- Create: `core/__init__.py`, `systems/__init__.py`, `components/__init__.py`, `utils/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p core systems components utils tests
touch core/__init__.py systems/__init__.py components/__init__.py utils/__init__.py
```

- [ ] **Step 2: 写 requirements.txt**

```
maibot-plugin-sdk>=2.0.0
aiosqlite>=0.20.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 3: 写 _manifest.json**

```json
{
  "manifest_version": 2,
  "id": "com.lifesim.life-simulation",
  "version": "2.0.0",
  "name": "Life Simulation",
  "description": "Maibot life simulation plugin",
  "capabilities": ["send_message"],
  "host_application": {"min_version": "1.0.0", "max_version": "1.99.99"},
  "sdk": {"min_version": "2.0.0", "max_version": "2.99.99"}
}
```

- [ ] **Step 4: 写 tests/conftest.py**

```python
import pytest
import asyncio
from datetime import datetime, timezone

@pytest.fixture
def utc_now():
    return datetime.now(tz=timezone.utc)
```

- [ ] **Step 5: 安装依赖并验证**

```bash
pip install aiosqlite pytest pytest-asyncio
python -c "import aiosqlite; print('ok')"
```

Expected: ok

- [ ] **Step 6: Commit**

```bash
git add requirements.txt _manifest.json config.toml core/__init__.py systems/__init__.py components/__init__.py utils/__init__.py tests/conftest.py
git commit -m "feat: project scaffold"
```

---

### Task A2: 时间工具（utils/time_helper.py）

**Files:**
- Create: `utils/time_helper.py`
- Test: `tests/test_time_helper.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_time_helper.py
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
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_time_helper.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 utils/time_helper.py**

```python
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
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_time_helper.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add utils/time_helper.py tests/test_time_helper.py
git commit -m "feat: time_helper with timezone support"
```

---

### Task A3: hint 工具（utils/hint_helper.py）

**Files:**
- Create: `utils/hint_helper.py`

- [ ] **Step 1: 实现 utils/hint_helper.py**

```python
_HINTS: dict[tuple[str, str], str] = {
    ("sleeping", "sleepy"):   "Preparing to sleep, feeling drowsy",
    ("sleeping", "sleeping"): "Currently sleeping, do not disturb",
    ("sleeping", "waking"):   "Just woke up, still a bit groggy",
    ("eating",   "awake"):    "Having a meal",
    ("studying", "awake"):    "Studying, pretty focused",
    ("exercising", "awake"):  "Exercising",
    ("working",  "awake"):    "Busy with work",
    ("leisure",  "awake"):    "Relaxing",
    ("other",    "awake"):    "Doing something",
}


def build_status_hint(activity: str, sleep_state: str, description: str = "") -> str:
    base = _HINTS.get((activity, sleep_state), "Status unknown")
    if description and activity not in ("sleeping",):
        return f"{base} ({description})"
    return base


_AFFINITY_LEVELS = [
    (0.8, "Very close, chat often"),
    (0.6, "Good impression, talk quite a bit"),
    (0.4, "Some interaction"),
    (0.2, "Occasional contact"),
    (0.0, "Barely know each other"),
]


def affinity_to_hint(affinity: float) -> str:
    for threshold, hint in _AFFINITY_LEVELS:
        if affinity >= threshold:
            return hint
    return _AFFINITY_LEVELS[-1][1]
```

- [ ] **Step 2: Commit**

```bash
git add utils/hint_helper.py
git commit -m "feat: hint_helper for status and affinity display"
```

---

### Task A4: 状态管理（core/state.py）

**Files:**
- Create: `core/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_state.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from core.state import (
    LifeStateManager, LifeStateSnapshot,
    ActivityType, SleepState, ScheduleItem, RecentEvent
)


@pytest.fixture
def config():
    c = MagicMock()
    c.max_recent_events = 20
    c.sleep.sleepy_duration_minutes = 30
    c.sleep.waking_duration_minutes = 15
    return c


@pytest.fixture
def manager(config):
    return LifeStateManager(config)


def test_snapshot_is_frozen(manager):
    snap = manager.snapshot()
    assert isinstance(snap, LifeStateSnapshot)
    with pytest.raises((AttributeError, TypeError)):
        snap.sleep_state = SleepState.SLEEPING


def test_snapshot_schedule_is_tuple(manager):
    assert isinstance(manager.snapshot().today_schedule, tuple)


def test_snapshot_events_is_tuple(manager):
    assert isinstance(manager.snapshot().recent_events, tuple)


@pytest.mark.asyncio
async def test_transition_returns_true(manager):
    ok = await manager.transition_activity(ActivityType.EATING, "t1")
    assert ok is True
    assert manager.snapshot().current_activity == ActivityType.EATING


@pytest.mark.asyncio
async def test_transition_idempotent(manager):
    await manager.transition_activity(ActivityType.EATING, "t1")
    ok = await manager.transition_activity(ActivityType.SLEEPING, "t1")
    assert ok is False
    assert manager.snapshot().current_activity == ActivityType.EATING


@pytest.mark.asyncio
async def test_transition_stores_prev(manager):
    await manager.transition_activity(ActivityType.EATING, "t1")
    await manager.transition_activity(ActivityType.LEISURE, "t2")
    snap = manager.snapshot()
    assert snap.prev_activity == ActivityType.EATING
    assert snap.current_activity == ActivityType.LEISURE


@pytest.mark.asyncio
async def test_set_schedule(manager):
    from datetime import date
    from utils.time_helper import local_time_to_utc_datetime
    d = date.today()
    start = local_time_to_utc_datetime(d, "08:00", "Asia/Shanghai")
    end = local_time_to_utc_datetime(d, "09:00", "Asia/Shanghai")
    item = ScheduleItem(start_time=start, end_time=end,
                        activity=ActivityType.EATING, description="breakfast")
    await manager.set_schedule([item])
    assert len(manager.snapshot().today_schedule) == 1


@pytest.mark.asyncio
async def test_append_event_prunes_expired(manager):
    old = RecentEvent("t", "old", datetime(2020, 1, 1, tzinfo=timezone.utc), ttl_seconds=1)
    new = RecentEvent("t", "new", datetime.now(tz=timezone.utc), ttl_seconds=3600)
    await manager.append_event(old)
    await manager.append_event(new)
    descs = [e.description for e in manager.snapshot().recent_events]
    assert "old" not in descs and "new" in descs
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_state.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 core/state.py**

```python
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SleepState(Enum):
    AWAKE = "awake"
    SLEEPY = "sleepy"
    SLEEPING = "sleeping"
    WAKING = "waking"


class ActivityType(Enum):
    SLEEPING = "sleeping"
    EATING = "eating"
    STUDYING = "studying"
    EXERCISING = "exercising"
    LEISURE = "leisure"
    WORKING = "working"
    OTHER = "other"


@dataclass(frozen=True)
class ScheduleItem:
    start_time: datetime
    end_time: datetime
    activity: ActivityType
    description: str
    is_skeleton: bool = False


@dataclass(frozen=True)
class RecentEvent:
    event_type: str
    description: str
    timestamp: datetime
    ttl_seconds: int = 3600


@dataclass(frozen=True)
class LifeStateSnapshot:
    sleep_state: SleepState
    current_activity: ActivityType
    prev_activity: ActivityType
    activity_since: datetime
    last_transition_processed_at: datetime
    schedule_generated_date: str
    schedule_is_repair: bool
    today_schedule: tuple
    recent_events: tuple


@dataclass
class LifeState:
    current_activity: ActivityType = ActivityType.OTHER
    prev_activity: ActivityType = ActivityType.OTHER
    activity_since: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc))
    last_transition_processed_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc))
    sleep_state: SleepState = SleepState.AWAKE
    today_schedule: list = field(default_factory=list)
    schedule_generated_date: str = ""
    schedule_is_repair: bool = False
    recent_events: list = field(default_factory=list)


class LifeStateManager:
    def __init__(self, config: Any):
        self._config = config
        self._lock = asyncio.Lock()
        self._state = LifeState()
        self._processed_transitions: dict[str, float] = {}

    def snapshot(self) -> LifeStateSnapshot:
        s = self._state
        return LifeStateSnapshot(
            sleep_state=s.sleep_state,
            current_activity=s.current_activity,
            prev_activity=s.prev_activity,
            activity_since=s.activity_since,
            last_transition_processed_at=s.last_transition_processed_at,
            schedule_generated_date=s.schedule_generated_date,
            schedule_is_repair=s.schedule_is_repair,
            today_schedule=tuple(s.today_schedule),
            recent_events=tuple(s.recent_events),
        )

    async def transition_activity(
        self, new_activity: ActivityType, transition_id: str
    ) -> bool:
        from systems.sleep import derive_sleep_state
        async with self._lock:
            now_ts = time.time()
            self._processed_transitions = {
                k: v for k, v in self._processed_transitions.items() if v > now_ts
            }
            if transition_id in self._processed_transitions:
                return False
            self._processed_transitions[transition_id] = now_ts + 86400
            now = datetime.now(tz=timezone.utc)
            prev = self._state.current_activity
            self._state.prev_activity = prev
            self._state.current_activity = new_activity
            self._state.activity_since = now
            self._state.last_transition_processed_at = now
            self._state.sleep_state = derive_sleep_state(
                activity=new_activity,
                activity_since=now,
                prev_activity=prev,
                now=now,
                config=self._config.sleep,
            )
            return True

    async def set_schedule(self, items: list, is_repair: bool = False) -> None:
        async with self._lock:
            self._state.today_schedule = list(items)
            self._state.schedule_is_repair = is_repair

    async def set_schedule_generated_date(self, date_str: str) -> None:
        async with self._lock:
            self._state.schedule_generated_date = date_str

    async def append_event(self, event: RecentEvent) -> None:
        async with self._lock:
            now = datetime.now(tz=timezone.utc)
            self._state.recent_events = [
                e for e in self._state.recent_events
                if (now - e.timestamp).total_seconds() < e.ttl_seconds
            ]
            self._state.recent_events.append(event)
            max_e = self._config.max_recent_events
            if len(self._state.recent_events) > max_e:
                self._state.recent_events = self._state.recent_events[-max_e:]

    async def restore(self, data: dict) -> None:
        async with self._lock:
            s = self._state
            s.current_activity = ActivityType(data.get("current_activity", "other"))
            s.prev_activity = ActivityType(data.get("prev_activity", "other"))
            s.sleep_state = SleepState(data.get("sleep_state", "awake"))
            s.schedule_generated_date = data.get("schedule_generated_date", "")

    async def restore_processed_transitions(
        self, transitions: dict[str, float]
    ) -> None:
        async with self._lock:
            self._processed_transitions.update(transitions)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_state.py -v
```

Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add core/state.py tests/test_state.py
git commit -m "feat: LifeStateManager with idempotent transitions and frozen snapshot"
```

---

### Task A5: 睡眠状态派生（systems/sleep.py）

**Files:**
- Create: `systems/sleep.py`
- Test: `tests/test_sleep.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sleep.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from core.state import ActivityType, SleepState
from systems.sleep import derive_sleep_state


@pytest.fixture
def cfg():
    c = MagicMock()
    c.sleepy_duration_minutes = 30
    c.waking_duration_minutes = 15
    return c


def test_eating_returns_awake(cfg):
    now = datetime.now(tz=timezone.utc)
    assert derive_sleep_state(ActivityType.EATING, now, ActivityType.LEISURE, now, cfg) == SleepState.AWAKE


def test_after_sleep_within_waking(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=5)
    result = derive_sleep_state(ActivityType.OTHER, since, ActivityType.SLEEPING, now, cfg)
    assert result == SleepState.WAKING


def test_after_sleep_past_waking(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=20)
    result = derive_sleep_state(ActivityType.OTHER, since, ActivityType.SLEEPING, now, cfg)
    assert result == SleepState.AWAKE


def test_sleeping_short_returns_sleepy(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=10)
    result = derive_sleep_state(ActivityType.SLEEPING, since, ActivityType.LEISURE, now, cfg)
    assert result == SleepState.SLEEPY


def test_sleeping_long_returns_sleeping(cfg):
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=45)
    result = derive_sleep_state(ActivityType.SLEEPING, since, ActivityType.LEISURE, now, cfg)
    assert result == SleepState.SLEEPING
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_sleep.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 systems/sleep.py**

```python
from datetime import datetime
from typing import Any
from core.state import ActivityType, SleepState


def derive_sleep_state(
    activity: ActivityType,
    activity_since: datetime,
    prev_activity: ActivityType,
    now: datetime,
    config: Any,
) -> SleepState:
    if activity != ActivityType.SLEEPING:
        if prev_activity == ActivityType.SLEEPING:
            elapsed = (now - activity_since).total_seconds() / 60
            if elapsed < config.waking_duration_minutes:
                return SleepState.WAKING
        return SleepState.AWAKE
    elapsed = (now - activity_since).total_seconds() / 60
    if elapsed < config.sleepy_duration_minutes:
        return SleepState.SLEEPY
    return SleepState.SLEEPING
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_sleep.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add systems/sleep.py tests/test_sleep.py
git commit -m "feat: derive_sleep_state pure function"
```

---

### Task A6: 数据库（core/database.py）

**Files:**
- Create: `core/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_database.py
import pytest, asyncio, time
from core.database import Database


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.start()
    yield d
    await d.stop()


@pytest.mark.asyncio
async def test_state_roundtrip(db):
    await db.save_state({"current_activity": "eating"})
    r = await db.load_state()
    assert r["current_activity"] == "eating"


@pytest.mark.asyncio
async def test_impression_roundtrip(db):
    imp = {"person_id": "p1", "person_name": "Alice", "traits": ["kind"],
           "affinity": 0.7, "proactive_score": 0.5, "proactive_cooldown_until": None,
           "last_interaction": None, "last_impression_update": None, "dirty": 0}
    await db.save_impression(imp)
    r = await db.get_impression("p1")
    assert r["person_name"] == "Alice"
    assert abs(r["affinity"] - 0.7) < 0.001


@pytest.mark.asyncio
async def test_nonce_lifecycle(db):
    await db.register_nonce("n1", "s1", ttl=3600)
    assert await db.nonce_exists("n1") is True
    await db.delete_nonce("n1")
    assert await db.nonce_exists("n1") is False


@pytest.mark.asyncio
async def test_person_stream(db):
    await db.update_person_stream("p1", "stream-1", time.time())
    r = await db.get_best_stream_for_person("p1")
    assert r["stream_id"] == "stream-1"


@pytest.mark.asyncio
async def test_writer_serializes(db):
    order = []
    async def op1(c): await asyncio.sleep(0.01); order.append(1)
    async def op2(c): order.append(2)
    f1 = await db.enqueue_write(op1)
    f2 = await db.enqueue_write(op2)
    await asyncio.gather(f1, f2)
    assert order == [1, 2]
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_database.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 core/database.py**

见 spec 4.2 节，关键实现要点：

1. `start()`: 读写双连接，均执行 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`，执行 `_SCHEMA` 建表，启动 `_writer_loop` task
2. `_writer_loop()`: `op, fut = await queue.get()` → `await conn.execute("BEGIN")` → `await op(conn)` → `await conn.commit()` → `fut.set_result(True)`；CancelledError 时 `await conn.rollback()` 后 raise；Exception 时 rollback + `fut.set_exception(e)`；finally: `queue.task_done()`
3. `stop()`: `await queue.join()` → cancel writer → `PRAGMA wal_checkpoint(FULL)` → close conns
4. `enqueue_write(op)`: 创建 Future，put `(op, fut)` 到队列，return fut
5. 所有读用 `self._read_conn`，写通过 `enqueue_write`

完整代码（含 _SCHEMA 和所有方法）约 250 行，按上述设计实现，方法列表：
`save_state`, `load_state`, `save_impression`, `get_impression`, `mark_dirty`, `get_dirty_persons`, `get_persons_above_score`, `update_person_stream`, `get_best_stream_for_person`, `register_nonce`, `nonce_exists`, `delete_nonce`, `load_processed_transitions_unexpired`, `save_proactive_guard_state`, `load_proactive_guard_state`, `cleanup_expired`, `maybe_checkpoint`

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_database.py -v
```

Expected: 5 passed

- [ ] **Step 5: 运行全部 Phase A 测试**

```bash
pytest tests/test_time_helper.py tests/test_sleep.py tests/test_state.py tests/test_database.py -v
```

Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add core/database.py tests/test_database.py
git commit -m "feat: Database WAL dual-connection single-writer-queue"
```

---

## Phase B：调度层

### Task B1: LLM 辅助（utils/llm_helper.py）

**Files:**
- Create: `utils/llm_helper.py`
- Create: `core/budget.py`

- [ ] **Step 1: 实现 core/budget.py**

```python
from __future__ import annotations
import time
from collections import defaultdict
from typing import Any


class ResourceBudget:
    """
    per-hour LLM 调用预算（滑动窗口，内存）。
    proactive daily 预算由 ProactiveGuard 管理，Budget 不重复维护。
    dirty_flush 每 heartbeat 上限通过 get_flush_limit() 获取。
    """

    def __init__(self, config: Any):
        self._config = config
        # call_type -> list of unix timestamps
        self._hourly: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str) -> None:
        cutoff = time.time() - 3600
        self._hourly[key] = [t for t in self._hourly[key] if t > cutoff]

    def can_llm_call(self, call_type: str) -> bool:
        self._cleanup(call_type)
        limits = {
            "schedule": self._config.llm_schedule_per_day,
            "impression": self._config.llm_impression_per_hour,
            "proactive_intent": self._config.llm_proactive_intent_per_hour,
        }
        limit = limits.get(call_type, 100)
        return len(self._hourly[call_type]) < limit

    def record_llm(self, call_type: str) -> None:
        self._hourly[call_type].append(time.time())

    def get_flush_limit(self) -> int:
        return self._config.dirty_flush_per_heartbeat

    async def restore_from_db(self) -> None:
        pass  # per-hour sliding window: 重启丢失可接受

    async def flush_daily_counters(self) -> None:
        pass  # per-hour budget 不需要持久化
```

- [ ] **Step 2: 实现 utils/llm_helper.py**

```python
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}", re.DOTALL)


def _parse_json(text: str) -> dict | None:
    # 1. 尝试直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # 2. 提取 ```json ... ``` 块
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 3. 提取第一个 {...}
    m = _JSON_OBJ_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _validate(data: dict, schema: dict) -> bool:
    required = schema.get("required", [])
    props = schema.get("properties", {})
    for key in required:
        if key not in data:
            return False
        expected_type = props.get(key, {}).get("type")
        if expected_type == "array" and not isinstance(data[key], list):
            return False
        if expected_type == "string" and not isinstance(data[key], str):
            return False
    return True


async def generate_json(
    ctx: Any,
    prompt: list[dict],
    schema: dict,
    budget_key: str,
    budget: Any,
    timeout: float = 30.0,
    max_retries: int = 2,
    max_repair_attempts: int = 2,
) -> dict | None:
    if not budget.can_llm_call(budget_key):
        logger.warning("LLM budget exceeded for %s", budget_key)
        return None

    repair_attempts = 0
    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.wait_for(
                ctx.llm.generate(prompt=prompt),
                timeout=timeout,
            )
            if not result.get("success"):
                logger.warning("LLM returned success=False attempt %d", attempt + 1)
                continue
            data = _parse_json(result.get("response", ""))
            if data is None:
                logger.warning("JSON parse failed attempt %d", attempt + 1)
                continue
            if _validate(data, schema):
                budget.record_llm(budget_key)
                return data
            # schema 校验失败，尝试修复
            if repair_attempts < max_repair_attempts:
                repair_attempts += 1
                repair_prompt = prompt + [
                    {"role": "assistant", "content": result["response"]},
                    {"role": "user", "content":
                     f"The response is missing required fields: "
                     f"{[k for k in schema.get('required', []) if k not in data]}. "
                     f"Please provide a valid JSON response with all required fields."},
                ]
                prompt = repair_prompt
                continue
            logger.warning("Schema validation failed after %d repair attempts", repair_attempts)
            return None
        except asyncio.TimeoutError:
            logger.warning("LLM timeout attempt %d/%d for %s", attempt + 1, max_retries + 1, budget_key)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("LLM error: %s", e, exc_info=True)
        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)
    return None
```

- [ ] **Step 3: Commit**

```bash
git add core/budget.py utils/llm_helper.py
git commit -m "feat: ResourceBudget and llm_helper with retry/schema validate"
```

---

### Task B2: 日程系统（systems/schedule.py）

**Files:**
- Create: `systems/schedule.py`
- Test: `tests/test_schedule.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_schedule.py
import pytest
from datetime import datetime, timezone, timedelta, date
from unittest.mock import MagicMock, AsyncMock
from core.state import ActivityType, ScheduleItem, LifeStateSnapshot, SleepState
from utils.time_helper import local_time_to_utc_datetime
from systems.schedule import (
    calc_next_transition, get_current_activity,
    get_missed_transitions, build_skeleton
)


def make_item(start_h: int, end_h: int, activity: ActivityType,
              desc: str = "", d: date = None) -> ScheduleItem:
    d = d or date.today()
    start = local_time_to_utc_datetime(d, f"{start_h:02d}:00", "Asia/Shanghai")
    end = local_time_to_utc_datetime(d, f"{end_h:02d}:00", "Asia/Shanghai")
    return ScheduleItem(start_time=start, end_time=end, activity=activity, description=desc)


def make_snap(items: list, last_processed: datetime = None) -> LifeStateSnapshot:
    now = datetime.now(tz=timezone.utc)
    return LifeStateSnapshot(
        sleep_state=SleepState.AWAKE,
        current_activity=ActivityType.OTHER,
        prev_activity=ActivityType.OTHER,
        activity_since=now,
        last_transition_processed_at=last_processed or now,
        schedule_generated_date=date.today().isoformat(),
        schedule_is_repair=False,
        today_schedule=tuple(items),
        recent_events=tuple(),
    )


def test_get_current_activity_finds_item():
    # 08:00~09:00 CST = some UTC range
    item = make_item(8, 9, ActivityType.EATING, "breakfast")
    snap = make_snap([item])
    # 08:30 CST
    t = local_time_to_utc_datetime(date.today(), "08:30", "Asia/Shanghai")
    result = get_current_activity(snap, t)
    assert result == ActivityType.EATING


def test_get_current_activity_returns_other_when_no_match():
    item = make_item(8, 9, ActivityType.EATING)
    snap = make_snap([item])
    t = local_time_to_utc_datetime(date.today(), "10:00", "Asia/Shanghai")
    result = get_current_activity(snap, t)
    assert result == ActivityType.OTHER


def test_calc_next_transition_returns_future():
    item = make_item(8, 9, ActivityType.EATING)
    snap = make_snap([item])
    t = local_time_to_utc_datetime(date.today(), "08:30", "Asia/Shanghai")
    next_time, next_act = calc_next_transition(snap, t)
    assert next_time > t
    assert next_act != ActivityType.EATING


def test_get_missed_transitions_empty_when_no_gap():
    item = make_item(8, 9, ActivityType.EATING)
    now = local_time_to_utc_datetime(date.today(), "08:30", "Asia/Shanghai")
    last = now - timedelta(minutes=1)
    snap = make_snap([item], last_processed=last)
    missed = get_missed_transitions(snap, now)
    assert len(missed) == 0


def test_get_missed_transitions_finds_skipped():
    # last_processed at 07:50, now at 09:10 -> missed the 08:00 and 09:00 transitions
    item1 = make_item(8, 9, ActivityType.EATING)
    item2 = make_item(9, 10, ActivityType.STUDYING)
    last = local_time_to_utc_datetime(date.today(), "07:50", "Asia/Shanghai")
    now = local_time_to_utc_datetime(date.today(), "09:10", "Asia/Shanghai")
    snap = make_snap([item1, item2], last_processed=last)
    missed = get_missed_transitions(snap, now)
    assert len(missed) >= 1


def test_build_skeleton_returns_items():
    cfg = MagicMock()
    cfg.sleep_start = "23:00"
    cfg.sleep_end = "07:00"
    cfg.breakfast_start = "07:30"
    cfg.breakfast_end = "08:00"
    cfg.lunch_start = "12:00"
    cfg.lunch_end = "12:30"
    cfg.dinner_start = "18:00"
    cfg.dinner_end = "18:30"
    items = build_skeleton(date.today(), cfg, "Asia/Shanghai")
    activities = [i.activity for i in items]
    assert ActivityType.SLEEPING in activities
    assert ActivityType.EATING in activities
    assert all(i.is_skeleton for i in items)
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_schedule.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 systems/schedule.py**

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Any, TYPE_CHECKING

from core.state import ActivityType, ScheduleItem
from utils.time_helper import local_time_to_utc_datetime, now_utc

if TYPE_CHECKING:
    from core.state import LifeStateSnapshot

logger = logging.getLogger(__name__)

_FALLBACK_SLOTS = [
    ("07:00", "09:00", ActivityType.STUDYING, "Morning study"),
    ("09:00", "12:00", ActivityType.WORKING, "Morning work"),
    ("13:00", "18:00", ActivityType.WORKING, "Afternoon work"),
    ("19:00", "22:00", ActivityType.LEISURE, "Evening leisure"),
]


def build_skeleton(d: date, cfg: Any, tz: str) -> list[ScheduleItem]:
    items = []
    def add(start_str: str, end_str: str, act: ActivityType, desc: str) -> None:
        start = local_time_to_utc_datetime(d, start_str, tz)
        end = local_time_to_utc_datetime(d, end_str, tz)
        if end <= start:
            end = end + timedelta(days=1)
        items.append(ScheduleItem(start_time=start, end_time=end,
                                  activity=act, description=desc, is_skeleton=True))

    add(cfg.sleep_end, cfg.sleep_end, ActivityType.SLEEPING, "Sleep")
    # Sleep spans midnight: split into two segments
    sleep_start = local_time_to_utc_datetime(d, cfg.sleep_start, tz)
    sleep_end_next = local_time_to_utc_datetime(d, cfg.sleep_end, tz) + timedelta(days=1)
    midnight = datetime(d.year, d.month, d.day + 1, 0, 0, 0, tzinfo=timezone.utc)
    if sleep_start.date() == d:
        items.append(ScheduleItem(sleep_start, midnight,
                                  ActivityType.SLEEPING, "Sleep (evening)", is_skeleton=True))
        sleep_end = local_time_to_utc_datetime(d + timedelta(days=1), cfg.sleep_end, tz)
        items.append(ScheduleItem(midnight, sleep_end,
                                  ActivityType.SLEEPING, "Sleep (morning)", is_skeleton=True))
    add(cfg.breakfast_start, cfg.breakfast_end, ActivityType.EATING, "Breakfast")
    add(cfg.lunch_start, cfg.lunch_end, ActivityType.EATING, "Lunch")
    add(cfg.dinner_start, cfg.dinner_end, ActivityType.EATING, "Dinner")
    # Remove the dummy first item
    items = [i for i in items if i.start_time != i.end_time]
    return sorted(items, key=lambda x: x.start_time)


def build_fallback_schedule(d: date, cfg: Any, tz: str) -> list[ScheduleItem]:
    items = build_skeleton(d, cfg, tz)
    skeleton_ranges = [(i.start_time, i.end_time) for i in items]
    day_start = local_time_to_utc_datetime(d, cfg.sleep_end, tz)
    day_end = local_time_to_utc_datetime(d, cfg.sleep_start, tz)
    for start_str, end_str, act, desc in _FALLBACK_SLOTS:
        start = local_time_to_utc_datetime(d, start_str, tz)
        end = local_time_to_utc_datetime(d, end_str, tz)
        if start < day_start or end > day_end:
            continue
        overlap = any(s < end and e > start for s, e in skeleton_ranges)
        if not overlap:
            items.append(ScheduleItem(start, end, act, desc))
    return sorted(items, key=lambda x: x.start_time)


def get_current_activity(snap: LifeStateSnapshot, now: datetime) -> ActivityType:
    for item in snap.today_schedule:
        if item.start_time <= now < item.end_time:
            return item.activity
    return ActivityType.OTHER


def calc_next_transition(
    snap: LifeStateSnapshot, now: datetime
) -> tuple[datetime, ActivityType]:
    current = get_current_activity(snap, now)
    candidates = []
    for item in snap.today_schedule:
        if item.start_time > now:
            candidates.append((item.start_time, item.activity))
        if item.end_time > now and item.activity == current:
            candidates.append((item.end_time, ActivityType.OTHER))
    if not candidates:
        # No more transitions today: sleep until tomorrow same time + 1 min
        return now + timedelta(hours=1), ActivityType.OTHER
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def get_missed_transitions(
    snap: LifeStateSnapshot, now: datetime
) -> list[tuple[ActivityType, datetime]]:
    last = snap.last_transition_processed_at
    missed = []
    for item in snap.today_schedule:
        # Item start is a transition point
        if last < item.start_time <= now:
            missed.append((item.activity, item.start_time))
        # Item end is a transition point (back to OTHER)
        if last < item.end_time <= now:
            missed.append((ActivityType.OTHER, item.end_time))
    missed.sort(key=lambda x: x[1])
    # Deduplicate adjacent same-activity transitions
    result = []
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
        from utils.time_helper import local_date_str
        from utils.llm_helper import generate_json
        d = date.fromisoformat(date_str)
        tz = self._config.plugin.timezone
        skeleton = build_skeleton(d, self._config.schedule, tz)

        personality = ""
        try:
            personality = await self._ctx.person.get_value("self", "personality") or ""
        except Exception:
            pass

        prompt_tmpl = self._config.prompts.schedule_generation
        skeleton_desc = "\n".join(
            f"{i.start_time.isoformat()} - {i.end_time.isoformat()}: {i.description}"
            for i in skeleton
        )
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
                f"Fixed schedule (do not modify): {skeleton_desc}\n"
                f"Fill in the remaining free time with realistic activities. "
                f"Return JSON: {{\"activities\": ["
                f"{{\"start\": \"HH:MM\", \"end\": \"HH:MM\", "
                f"\"activity\": \"studying|working|exercising|leisure|other\", "
                f"\"description\": \"short desc\"}}]}}"
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
            timeout=self._config.llm.timeout_seconds,
            max_retries=self._config.llm.max_retries,
        )

        if result is None:
            logger.warning("Schedule generation failed, using fallback")
            items = build_fallback_schedule(d, self._config.schedule, tz)
        else:
            items = list(skeleton)
            for act_data in result.get("activities", []):
                try:
                    start = local_time_to_utc_datetime(d, act_data["start"], tz)
                    end = local_time_to_utc_datetime(d, act_data["end"], tz)
                    act = ActivityType(act_data.get("activity", "other"))
                    desc = act_data.get("description", "")
                    overlap = any(i.start_time < end and i.end_time > start for i in skeleton)
                    if not overlap and start < end:
                        items.append(ScheduleItem(start, end, act, desc))
                except Exception as e:
                    logger.warning("Skip invalid schedule item: %s", e)
            items.sort(key=lambda x: x.start_time)

        await self._manager.set_schedule(items, is_repair=is_recovery)
        await self._manager.set_schedule_generated_date(date_str)
        logger.info("Schedule generated for %s: %d items", date_str, len(items))
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_schedule.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add systems/schedule.py tests/test_schedule.py
git commit -m "feat: schedule system with skeleton, fallback, calc_next_transition"
```

---

### Task B3: 资源预算（core/budget.py 补全）

资源预算已在 Task B1 中完整实现，此 Task 验证与 ScheduleSystem 的集成。

- [ ] **Step 1: 验证 budget + schedule 集成**

```bash
pytest tests/test_schedule.py tests/ -v -k "not database and not state and not sleep and not time"
```

Expected: no new failures

- [ ] **Step 2: Commit（如有修改）**

```bash
git add -A && git commit -m "feat: budget integration verification"
```

---

### Task B4: 调度编排（core/orchestrator.py）

**Files:**
- Create: `core/orchestrator.py`

- [ ] **Step 1: 实现 core/orchestrator.py**

```python
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.state import ActivityType, RecentEvent
from systems import schedule as schedule_mod
from utils.time_helper import now_utc, local_date_str, is_in_quiet_hours

logger = logging.getLogger(__name__)


class StreamRegistry:
    def __init__(self):
        self._streams: set[str] = set()

    def register(self, stream_id: str) -> None:
        self._streams.add(stream_id)

    def get_all(self) -> list[str]:
        return list(self._streams)


class BackgroundTaskRegistry:
    def __init__(self):
        self._tasks: set[asyncio.Task] = set()

    def create_task(self, coro, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        task.add_done_callback(self._on_done)
        self._tasks.add(task)
        return task

    def _on_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Task '%s' raised: %s", task.get_name(), exc, exc_info=exc)

    async def cancel_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


class Orchestrator:
    def __init__(
        self,
        manager: Any,
        db: Any,
        budget: Any,
        schedule_sys: Any,
        relation_sys: Any,
        proactive_sys: Any,
        ctx: Any,
        config: Any,
        stream_registry: StreamRegistry,
    ):
        self._manager = manager
        self._db = db
        self._budget = budget
        self._schedule = schedule_sys
        self._relation = relation_sys
        self._proactive = proactive_sys
        self._ctx = ctx
        self._config = config
        self._stream_registry = stream_registry
        self._registry = BackgroundTaskRegistry()

    async def start(self) -> None:
        await self._db.start()
        await self._recovery_check()
        self._registry.create_task(self._run(), name="orchestrator.main")
        self._registry.create_task(self._heartbeat(), name="orchestrator.heartbeat")

    async def stop(self) -> None:
        await self._registry.cancel_all()
        await self._db.stop()

    async def _run(self) -> None:
        while True:
            try:
                snap = self._manager.snapshot()
                now = now_utc()
                next_time, _ = schedule_mod.calc_next_transition(snap, now)
                sleep_secs = max((next_time - now).total_seconds(), 0)
                await asyncio.sleep(sleep_secs)

                actual_now = now_utc()
                snap = self._manager.snapshot()

                missed = schedule_mod.get_missed_transitions(snap, actual_now)
                for missed_act, missed_time in missed:
                    tid = f"transition:{missed_time.isoformat()}:{missed_act.value}"
                    await self._on_transition(missed_act, tid, is_missed=True)

                actual_act = schedule_mod.get_current_activity(
                    self._manager.snapshot(), actual_now
                )
                tid = f"transition:{actual_now.isoformat()}:{actual_act.value}"
                await self._on_transition(actual_act, tid)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Orchestrator _run error: %s", e, exc_info=True)
                await asyncio.sleep(10)

    async def _on_transition(
        self, new_activity: ActivityType, transition_id: str, is_missed: bool = False
    ) -> None:
        old_snap = self._manager.snapshot()
        ok = await self._manager.transition_activity(new_activity, transition_id)
        if not ok:
            return

        try:
            await self._apply_frequency(new_activity)
        except Exception as e:
            logger.error("apply_frequency failed: %s", e)

        try:
            if not is_missed and not old_snap.schedule_is_repair:
                await self._proactive.on_transition(
                    old_snap.current_activity, new_activity, transition_id
                )
        except Exception as e:
            logger.error("proactive.on_transition failed: %s", e)

        await self._db.enqueue_write(self._persist_state)

        await self._manager.append_event(RecentEvent(
            event_type="schedule_transition",
            description=f"{old_snap.current_activity.value} -> {new_activity.value}",
            timestamp=now_utc(),
        ))

    async def _persist_state(self, conn: Any) -> None:
        import json, time as _time
        snap = self._manager.snapshot()
        data = {
            "current_activity": snap.current_activity.value,
            "prev_activity": snap.prev_activity.value,
            "sleep_state": snap.sleep_state.value,
            "schedule_generated_date": snap.schedule_generated_date,
        }
        await conn.execute(
            "INSERT OR REPLACE INTO life_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("main", json.dumps(data), _time.time()),
        )

    async def _apply_frequency(self, activity: ActivityType) -> None:
        factor = self._config.frequency.get(activity.value, 0.0)
        for stream_id in self._stream_registry.get_all():
            try:
                await self._ctx.frequency.set_adjust(stream_id, factor)
            except Exception as e:
                logger.warning("set_adjust failed for %s: %s", stream_id, e)

    async def _heartbeat(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._config.heartbeat.interval_seconds)
                self._registry.create_task(
                    self._relation.flush_dirty_impressions(),
                    name="heartbeat.flush_impressions"
                )
                self._registry.create_task(
                    self._proactive.check_score_trigger(),
                    name="heartbeat.score_trigger"
                )
                self._registry.create_task(
                    self._db.maybe_checkpoint(),
                    name="heartbeat.checkpoint"
                )
                self._registry.create_task(
                    self._db.cleanup_expired(),
                    name="heartbeat.cleanup"
                )
                self._registry.create_task(
                    self._budget.flush_daily_counters(),
                    name="heartbeat.budget_flush"
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Orchestrator _heartbeat error: %s", e, exc_info=True)
                await asyncio.sleep(30)

    async def _recovery_check(self) -> None:
        persisted = await self._db.load_state()
        if persisted:
            await self._manager.restore(persisted)

        unexpired = await self._db.load_processed_transitions_unexpired()
        await self._manager.restore_processed_transitions(unexpired)

        guard_state = await self._db.load_proactive_guard_state()
        if guard_state:
            self._proactive.restore_guard(guard_state)

        await self._budget.restore_from_db()

        tz = self._config.plugin.timezone
        local_today = local_date_str(tz)
        if self._manager.snapshot().schedule_generated_date != local_today:
            await self._schedule.generate(local_today, is_recovery=True)

        snap = self._manager.snapshot()
        missed = schedule_mod.get_missed_transitions(snap, now_utc())
        for act, t in missed:
            tid = f"transition:{t.isoformat()}:{act.value}"
            await self._on_transition(act, tid, is_missed=True)

    def reload_config(self, config: Any) -> None:
        self._config = config
        logger.info("Orchestrator config reloaded")
```

- [ ] **Step 2: Commit**

```bash
git add core/orchestrator.py
git commit -m "feat: Orchestrator with event-driven scheduling, recovery, heartbeat"
```

---

## Phase C：关系网（systems/relation.py）

### Task C1: 关系网系统

**Files:**
- Create: `systems/relation.py`
- Test: `tests/test_relation.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_relation.py
import pytest
import time
from unittest.mock import MagicMock, AsyncMock
from systems.relation import DirtyQueue, RelationSystem


def test_dirty_queue_dedup():
    q = DirtyQueue(max_size=10, ttl_seconds=3600)
    q.mark("p1", "s1")
    q.mark("p1", "s1")  # duplicate
    assert len(q._queue) == 1


def test_dirty_queue_pop_batch():
    q = DirtyQueue(max_size=10, ttl_seconds=3600)
    q.mark("p1", "s1")
    q.mark("p2", "s1")
    batch = q.pop_batch(limit=1)
    assert len(batch) == 1
    assert len(q._queue) == 1


def test_dirty_queue_ttl_prune():
    q = DirtyQueue(max_size=10, ttl_seconds=1)
    q._queue[("p_old", "s1")] = time.time() - 2  # already expired
    q.mark("p_new", "s1")
    batch = q.pop_batch(limit=10)
    pids = [b[0] for b in batch]
    assert "p_old" not in pids
    assert "p_new" in pids


def test_dirty_queue_requeue_on_cooldown():
    q = DirtyQueue(max_size=10, ttl_seconds=3600)
    q.mark("p1", "s1")
    q.pop_batch(limit=10)
    assert len(q._queue) == 0
    q.mark("p1", "s1")  # requeue
    assert len(q._queue) == 1


@pytest.mark.asyncio
async def test_mark_interaction_updates_db():
    db = MagicMock()
    db.update_person_stream = AsyncMock()
    db.mark_dirty = AsyncMock()
    db.get_impression = AsyncMock(return_value=None)
    ctx = MagicMock()
    budget = MagicMock()
    config = MagicMock()
    config.min_update_interval_minutes = 30
    sys = RelationSystem(db=db, ctx=ctx, budget=budget, config=config)
    await sys.mark_interaction("p1", "stream-1", {"message_id": "m1"})
    db.update_person_stream.assert_awaited_once()
    db.mark_dirty.assert_awaited_once_with("p1")
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_relation.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 systems/relation.py**

```python
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class DirtyQueue:
    def __init__(self, max_size: int = 500, ttl_seconds: int = 7200):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._queue: dict[tuple[str, str], float] = {}

    def mark(self, person_id: str, stream_id: str) -> None:
        key = (person_id, stream_id)
        if key in self._queue:
            return
        if len(self._queue) >= self.max_size:
            oldest = min(self._queue, key=self._queue.get)
            del self._queue[oldest]
        self._queue[key] = time.time()

    def pop_batch(self, limit: int) -> list[tuple[str, str]]:
        now = time.time()
        expired = [k for k, t in self._queue.items() if now - t > self.ttl_seconds]
        for k in expired:
            del self._queue[k]
        sorted_keys = sorted(self._queue, key=self._queue.get)[:limit]
        for k in sorted_keys:
            del self._queue[k]
        return sorted_keys


class RelationSystem:
    def __init__(self, db: Any, ctx: Any, budget: Any, config: Any):
        self._db = db
        self._ctx = ctx
        self._budget = budget
        self._config = config
        self._dirty_queue = DirtyQueue(
            max_size=config.dirty_queue_max_size,
            ttl_seconds=config.dirty_queue_ttl_seconds,
        )

    async def mark_interaction(
        self, person_id: str, stream_id: str, message: dict
    ) -> None:
        try:
            await self._db.update_person_stream(person_id, stream_id, time.time())
            await self._db.mark_dirty(person_id)
            self._dirty_queue.mark(person_id, stream_id)
        except Exception as e:
            logger.error("mark_interaction error: %s", e, exc_info=True)

    async def flush_dirty_impressions(self) -> None:
        limit = self._budget.get_flush_limit()
        pairs = self._dirty_queue.pop_batch(limit=limit)
        now = datetime.now(tz=timezone.utc)

        for person_id, stream_id in pairs:
            try:
                imp = await self._db.get_impression(person_id)
                if imp and imp.get("last_impression_update"):
                    last_update = imp["last_impression_update"]
                    elapsed_min = (now.timestamp() - last_update) / 60
                    if elapsed_min < self._config.min_update_interval_minutes:
                        self._dirty_queue.mark(person_id, stream_id)  # requeue
                        continue

                if not self._budget.can_llm_call("impression"):
                    self._dirty_queue.mark(person_id, stream_id)  # requeue
                    break

                recent_msgs = await self._ctx.message.get_recent(
                    chat_id=stream_id, limit=20
                )

                prompt_tmpl = self._config.prompts.impression_update if hasattr(self._config, 'prompts') else ""
                person_name = imp["person_name"] if imp else person_id
                old_imp_str = str(imp) if imp else "No previous impression"
                if prompt_tmpl:
                    prompt_text = (prompt_tmpl
                                   .replace("{person_name}", person_name)
                                   .replace("{recent_messages}", str(recent_msgs))
                                   .replace("{old_impression}", old_imp_str))
                else:
                    prompt_text = (
                        f"Based on these recent messages from {person_name}: {recent_msgs}\n"
                        f"Previous impression: {old_imp_str}\n"
                        f"Update the impression. Return JSON: "
                        f'{{\"traits\": [\"trait1\", \"trait2\"], '
                        f'\"affinity\": 0.5, '
                        f'\"had_recent_interaction\": true}}'
                    )

                from utils.llm_helper import generate_json
                schema = {
                    "required": ["traits", "affinity"],
                    "properties": {
                        "traits": {"type": "array"},
                        "affinity": {"type": "number"},
                    },
                }
                result = await generate_json(
                    self._ctx,
                    prompt=[{"role": "user", "content": prompt_text}],
                    schema=schema,
                    budget_key="impression",
                    budget=self._budget,
                )
                if result is None:
                    continue

                new_score = self._update_proactive_score(imp, result)
                new_imp = {
                    "person_id": person_id,
                    "person_name": person_name,
                    "traits": result.get("traits", []),
                    "affinity": float(result.get("affinity", 0.5)),
                    "proactive_score": new_score,
                    "last_impression_update": now.timestamp(),
                }
                await self._db.save_impression(new_imp)

            except Exception as e:
                logger.error("flush impression for %s failed: %s", person_id, e, exc_info=True)

    def _update_proactive_score(self, old_imp: dict | None, new_data: dict) -> float:
        score = old_imp["proactive_score"] if old_imp else 0.0
        if new_data.get("had_recent_interaction"):
            score = min(1.0, score + 0.15)
        if new_data.get("user_replied_to_proactive"):
            score = min(1.0, score + 0.2)
        if float(new_data.get("affinity", 0.5)) > 0.7:
            score = min(1.0, score + 0.05)
        if old_imp and old_imp.get("last_interaction"):
            import time as _time
            days_silent = (_time.time() - old_imp["last_interaction"]) / 86400
            decay = min(days_silent * 0.05, 0.3)
            score = max(0.0, score - decay)
        return round(score, 4)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_relation.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add systems/relation.py tests/test_relation.py
git commit -m "feat: RelationSystem with DirtyQueue and impression flush"
```

---

## Phase D：主动行为（systems/proactive.py）

### Task D1: 主动行为系统

**Files:**
- Create: `systems/proactive.py`
- Test: `tests/test_proactive.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_proactive.py
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from core.state import SleepState, ActivityType
from systems.proactive import ProactiveGuard, ProactiveSystem


@pytest.fixture
def config():
    c = MagicMock()
    c.proactive.enabled = True
    c.proactive.global_cooldown_minutes = 30
    c.proactive.per_group_cooldown_minutes = 60
    c.proactive.daily_limit = 5
    c.proactive.max_consecutive = 2
    c.proactive.consecutive_reset_after_minutes = 120
    c.proactive.score_threshold = 0.7
    c.proactive.debounce_seconds = 5
    c.proactive.schedule_transition_probability = 1.0  # always trigger in tests
    c.proactive.waking_probability_factor = 0.3
    c.proactive.quiet_hours_start = "23:00"
    c.proactive.quiet_hours_end = "07:00"
    c.plugin.timezone = "Asia/Shanghai"
    return c


@pytest.fixture
def guard():
    return ProactiveGuard(
        global_cooldown_until=datetime(2000, 1, 1, tzinfo=timezone.utc),
        per_group_cooldown={},
        daily_count=0,
        daily_date="2000-01-01",
        daily_limit=5,
        last_trigger_time=None,
        consecutive_count=0,
        consecutive_reset_after_minutes=120,
    )


def test_guard_passes_when_fresh(guard):
    from systems.proactive import _check_guard_conditions
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    ok = _check_guard_conditions(guard, "stream-1", snap, MagicMock())
    assert ok is True


def test_guard_fails_when_sleeping(guard):
    from systems.proactive import _check_guard_conditions
    snap = MagicMock()
    snap.sleep_state = SleepState.SLEEPING
    ok = _check_guard_conditions(guard, "stream-1", snap, MagicMock())
    assert ok is False


def test_guard_fails_when_daily_limit_reached(guard):
    from systems.proactive import _check_guard_conditions
    guard.daily_count = 5
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    ok = _check_guard_conditions(guard, "stream-1", snap, MagicMock())
    assert ok is False


def test_guard_fails_when_global_cooldown(guard):
    from systems.proactive import _check_guard_conditions
    guard.global_cooldown_until = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    ok = _check_guard_conditions(guard, "stream-1", snap, MagicMock())
    assert ok is False


@pytest.mark.asyncio
async def test_trigger_calls_maisaka(config):
    db = MagicMock()
    db.nonce_exists = AsyncMock(return_value=False)
    db.register_nonce = AsyncMock()
    db.delete_nonce = AsyncMock()
    db.save_proactive_guard_state = AsyncMock()
    db.enqueue_write = AsyncMock(return_value=AsyncMock())
    ctx = MagicMock()
    ctx.maisaka.proactive.trigger = AsyncMock()
    ctx.llm.generate = AsyncMock(return_value={
        "success": True,
        "response": "OK let me chat"
    })
    manager = MagicMock()
    snap = MagicMock()
    snap.sleep_state = SleepState.AWAKE
    snap.schedule_is_repair = False
    manager.snapshot.return_value = snap
    budget = MagicMock()
    budget.can_llm_call.return_value = True
    budget.record_llm = MagicMock()

    sys = ProactiveSystem(db=db, ctx=ctx, manager=manager, budget=budget, config=config)
    await sys.trigger("stream-1", "Just finished lunch", "transition", "tid-001")
    ctx.maisaka.proactive.trigger.assert_awaited_once()
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_proactive.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 systems/proactive.py**

```python
from __future__ import annotations
import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from core.state import ActivityType, SleepState
from utils.time_helper import now_utc, is_in_quiet_hours, local_date_str

logger = logging.getLogger(__name__)


@dataclass
class ProactiveGuard:
    global_cooldown_until: datetime
    per_group_cooldown: dict[str, datetime]
    daily_count: int
    daily_date: str
    daily_limit: int
    last_trigger_time: datetime | None
    consecutive_count: int
    consecutive_reset_after_minutes: int
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _nonce_registry: dict[str, float] = field(default_factory=dict)


def _check_guard_conditions(
    guard: ProactiveGuard, stream_id: str, snap: Any, config: Any
) -> bool:
    now = now_utc()
    if snap.sleep_state == SleepState.SLEEPING:
        return False
    tz = config.plugin.timezone if hasattr(config, 'plugin') else "Asia/Shanghai"
    if is_in_quiet_hours(now, config.proactive.quiet_hours_start,
                         config.proactive.quiet_hours_end, tz):
        return False
    if now < guard.global_cooldown_until:
        return False
    group_cd = guard.per_group_cooldown.get(stream_id)
    if group_cd and now < group_cd:
        return False
    # Check daily_count (reset if new day)
    today = local_date_str(tz)
    if guard.daily_date != today:
        guard.daily_count = 0
        guard.daily_date = today
    if guard.daily_count >= guard.daily_limit:
        return False
    if guard.consecutive_count >= config.proactive.max_consecutive:
        # Check if enough time has passed to reset
        if guard.last_trigger_time:
            elapsed = (now - guard.last_trigger_time).total_seconds() / 60
            if elapsed < guard.consecutive_reset_after_minutes:
                return False
        guard.consecutive_count = 0
    return True


class ProactiveSystem:
    def __init__(self, db: Any, ctx: Any, manager: Any, budget: Any, config: Any):
        self._db = db
        self._ctx = ctx
        self._manager = manager
        self._budget = budget
        self._config = config
        self._guard = ProactiveGuard(
            global_cooldown_until=datetime(2000, 1, 1, tzinfo=timezone.utc),
            per_group_cooldown={},
            daily_count=0,
            daily_date="",
            daily_limit=config.proactive.daily_limit,
            last_trigger_time=None,
            consecutive_count=0,
            consecutive_reset_after_minutes=config.proactive.consecutive_reset_after_minutes,
        )

    def _make_nonce(self, stream_id: str, transition_id: str | None, source: str) -> str:
        key = f"{stream_id}:{transition_id or ''}:{source}:{local_date_str('UTC')}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    async def trigger(
        self,
        stream_id: str,
        intent: str,
        source: str,
        transition_id: str | None = None,
    ) -> None:
        if not self._config.proactive.enabled:
            return

        async with self._guard._lock:
            snap = self._manager.snapshot()
            if not _check_guard_conditions(self._guard, stream_id, snap, self._config):
                return

            nonce = self._make_nonce(stream_id, transition_id, source)
            now_ts = time.time()
            # Cleanup expired nonces
            self._guard._nonce_registry = {
                k: v for k, v in self._guard._nonce_registry.items() if v > now_ts
            }
            if nonce in self._guard._nonce_registry:
                return
            if await self._db.nonce_exists(nonce):
                return

            # Debounce check
            debounce = self._config.proactive.debounce_seconds
            if transition_id:
                key = f"debounce:{transition_id}"
                if key in self._guard._nonce_registry:
                    return
                self._guard._nonce_registry[key] = now_ts + debounce

            self._guard._nonce_registry[nonce] = now_ts + 3600
            await self._db.register_nonce(nonce, stream_id, ttl=3600)
        # Lock released

        # Build intent (LLM, no lock held)
        final_intent = await self._build_intent(intent, snap)
        if final_intent is None:
            await self._db.delete_nonce(nonce)
            self._guard._nonce_registry.pop(nonce, None)
            return

        # Trigger
        try:
            await self._ctx.maisaka.proactive.trigger(
                stream_id=stream_id,
                intent=final_intent,
                reason=source,
                metadata={"nonce": nonce, "source": "life_simulation"},
            )
        except Exception as e:
            logger.error("maisaka.proactive.trigger failed: %s", e)
            await self._db.delete_nonce(nonce)
            self._guard._nonce_registry.pop(nonce, None)
            return

        async with self._guard._lock:
            self._update_guard(stream_id)
        await self._db.save_proactive_guard_state(self._guard_to_dict())

    async def _build_intent(self, base_intent: str, snap: Any) -> str | None:
        prompt_tmpl = getattr(getattr(self._config, 'prompts', None), 'proactive_intent', "")
        if not prompt_tmpl:
            return base_intent  # use base intent directly if no LLM template

        if not self._budget.can_llm_call("proactive_intent"):
            return base_intent

        prompt_text = (prompt_tmpl
                       .replace("{state}", snap.sleep_state.value)
                       .replace("{activity}", snap.current_activity.value)
                       .replace("{description}", base_intent))

        from utils.llm_helper import generate_json
        result = await generate_json(
            self._ctx,
            prompt=[{"role": "user", "content": prompt_text}],
            schema={"required": ["intent"], "properties": {"intent": {"type": "string"}}},
            budget_key="proactive_intent",
            budget=self._budget,
        )
        return result["intent"] if result else None

    def _update_guard(self, stream_id: str) -> None:
        now = now_utc()
        self._guard.global_cooldown_until = now + timedelta(
            minutes=self._config.proactive.global_cooldown_minutes
        )
        self._guard.per_group_cooldown[stream_id] = now + timedelta(
            minutes=self._config.proactive.per_group_cooldown_minutes
        )
        # Cleanup expired per_group entries
        self._guard.per_group_cooldown = {
            k: v for k, v in self._guard.per_group_cooldown.items() if v > now
        }
        tz = self._config.plugin.timezone if hasattr(self._config, 'plugin') else "Asia/Shanghai"
        today = local_date_str(tz)
        if self._guard.daily_date != today:
            self._guard.daily_count = 0
            self._guard.daily_date = today
        self._guard.daily_count += 1
        self._guard.last_trigger_time = now
        self._guard.consecutive_count += 1

    def _guard_to_dict(self) -> dict:
        import json
        return {
            "global_cooldown_until": self._guard.global_cooldown_until.isoformat(),
            "daily_count": self._guard.daily_count,
            "daily_date": self._guard.daily_date,
            "consecutive_count": self._guard.consecutive_count,
            "last_trigger_time": (
                self._guard.last_trigger_time.isoformat()
                if self._guard.last_trigger_time else None
            ),
        }

    def restore_guard(self, data: dict) -> None:
        if data.get("global_cooldown_until"):
            self._guard.global_cooldown_until = datetime.fromisoformat(
                data["global_cooldown_until"]
            )
        tz = self._config.plugin.timezone if hasattr(self._config, 'plugin') else "Asia/Shanghai"
        today = local_date_str(tz)
        if data.get("daily_date") == today:
            self._guard.daily_count = data.get("daily_count", 0)
        self._guard.consecutive_count = data.get("consecutive_count", 0)
        if data.get("last_trigger_time"):
            self._guard.last_trigger_time = datetime.fromisoformat(data["last_trigger_time"])

    async def on_transition(
        self, old_activity: ActivityType, new_activity: ActivityType, transition_id: str
    ) -> None:
        if not self._config.proactive.enabled:
            return
        snap = self._manager.snapshot()
        if snap.schedule_is_repair:
            return
        prob = self._config.proactive.schedule_transition_probability
        if snap.sleep_state == SleepState.WAKING:
            prob *= self._config.proactive.waking_probability_factor
        if random.random() > prob:
            return
        intent = f"Just transitioned from {old_activity.value} to {new_activity.value}"
        # Find a stream to send to
        streams = []
        try:
            group_streams = await self._ctx.chat.get_group_streams()
            streams = [s.get("stream_id") for s in group_streams if s.get("stream_id")]
        except Exception:
            pass
        if not streams:
            return
        stream_id = streams[0]
        await self.trigger(stream_id, intent, "transition", transition_id)

    async def check_score_trigger(self) -> None:
        if not self._config.proactive.enabled:
            return
        try:
            persons = await self._db.get_persons_above_score(
                self._config.proactive.score_threshold
            )
            for person in persons:
                best = await self._db.get_best_stream_for_person(person["person_id"])
                if best is None:
                    continue
                intent = f"Feeling like chatting with {person['person_name']}"
                await self.trigger(
                    stream_id=best["stream_id"],
                    intent=intent,
                    source="heartbeat_score",
                )
        except Exception as e:
            logger.error("check_score_trigger error: %s", e, exc_info=True)
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_proactive.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add systems/proactive.py tests/test_proactive.py
git commit -m "feat: ProactiveSystem with guard, nonce, debounce, score trigger"
```

---

## Phase E：组件层与集成

### Task E1: Hook 组件（components/hooks.py）

**Files:**
- Create: `components/hooks.py`
- Test: `tests/test_hooks.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_hooks.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from core.state import SleepState, ActivityType, LifeStateSnapshot
from datetime import datetime, timezone


def make_snap(sleep_state=SleepState.AWAKE):
    return LifeStateSnapshot(
        sleep_state=sleep_state,
        current_activity=ActivityType.OTHER,
        prev_activity=ActivityType.OTHER,
        activity_since=datetime.now(tz=timezone.utc),
        last_transition_processed_at=datetime.now(tz=timezone.utc),
        schedule_generated_date="2026-05-22",
        schedule_is_repair=False,
        today_schedule=tuple(),
        recent_events=tuple(),
    )


@pytest.mark.asyncio
async def test_sleep_gate_aborts_when_sleeping():
    from components.hooks import LifeSimHooks
    plugin = MagicMock()
    plugin._manager.snapshot.return_value = make_snap(SleepState.SLEEPING)
    plugin._stream_registry = MagicMock()
    plugin._relation = MagicMock()
    plugin._registry = MagicMock()

    hooks = LifeSimHooks(plugin)
    result = await hooks.handle_sleep_gate(message={"stream_id": "s1", "message_id": "m1"})
    assert result == {"action": "abort"}


@pytest.mark.asyncio
async def test_sleep_gate_continues_when_awake():
    from components.hooks import LifeSimHooks
    plugin = MagicMock()
    plugin._manager.snapshot.return_value = make_snap(SleepState.AWAKE)
    plugin._stream_registry = MagicMock()
    plugin._relation = MagicMock()
    plugin._registry = MagicMock()

    hooks = LifeSimHooks(plugin)
    msg = {"stream_id": "s1", "message_id": "m1"}
    result = await hooks.handle_sleep_gate(message=msg)
    assert result["action"] == "continue"
    plugin._stream_registry.register.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_observe_interaction_creates_task():
    from components.hooks import LifeSimHooks
    plugin = MagicMock()
    plugin._registry.create_task = MagicMock()

    hooks = LifeSimHooks(plugin)
    msg = {"stream_id": "s1", "person_id": "p1", "message_id": "m1"}
    await hooks.observe_interaction(message=msg)
    plugin._registry.create_task.assert_called_once()
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_hooks.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 components/hooks.py**

```python
from __future__ import annotations
import asyncio
import logging
from typing import Any

from maibot_sdk import HookHandler
from maibot_sdk.types import HookMode, HookOrder, ErrorPolicy

from core.state import SleepState

logger = logging.getLogger(__name__)


class LifeSimHooks:
    """
    Hook handlers. Injected with plugin instance to access _manager, _registry, etc.
    Decorators are declarative; method bodies run when called by Host.
    """

    def __init__(self, plugin: Any):
        self._plugin = plugin

    @HookHandler(
        "chat.receive.before_process",
        name="life_sim_sleep_gate",
        description="Intercept messages while sleeping",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def handle_sleep_gate(self, **kwargs) -> dict:
        message = kwargs.get("message", {})
        snap = self._plugin._manager.snapshot()

        if snap.sleep_state == SleepState.SLEEPING:
            return {"action": "abort"}

        stream_id = message.get("stream_id")
        if stream_id:
            self._plugin._stream_registry.register(stream_id)

        kwargs["message"] = message
        return {"action": "continue", "modified_kwargs": kwargs}

    @HookHandler(
        "chat.receive.after_process",
        name="life_sim_interaction_observer",
        description="Observe messages to update relation network",
        mode=HookMode.OBSERVE,
        order=HookOrder.NORMAL,
    )
    async def observe_interaction(self, **kwargs) -> None:
        message = kwargs.get("message", {})
        person_id = (message.get("person_id") or
                     message.get("user_info", {}).get("person_id"))
        stream_id = message.get("stream_id")
        if person_id and stream_id:
            self._plugin._registry.create_task(
                self._plugin._relation.mark_interaction(person_id, stream_id, message),
                name=f"mark_interaction:{message.get('message_id', 'unknown')}",
            )
```

- [ ] **Step 4: 运行确认通过**

```bash
pytest tests/test_hooks.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add components/hooks.py tests/test_hooks.py
git commit -m "feat: HookHandler for sleep gate and interaction observer"
```

---

### Task E2: Tool 组件（components/tools.py）

**Files:**
- Create: `components/tools.py`

- [ ] **Step 1: 实现 components/tools.py**

```python
from __future__ import annotations
import logging
from datetime import timedelta
from typing import Any

from maibot_sdk import Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from core.state import SleepState
from utils.hint_helper import build_status_hint, affinity_to_hint
from utils.time_helper import to_local, now_utc

logger = logging.getLogger(__name__)


class LifeSimTools:
    def __init__(self, plugin: Any):
        self._plugin = plugin

    @Tool(
        "get_life_state",
        brief_description="Get current life simulation status",
        detailed_description="Returns current activity, sleep state, and a natural language hint.",
        parameters=[],
    )
    async def get_life_state(self, **kwargs) -> dict:
        snap = self._plugin._manager.snapshot()
        desc = ""
        if snap.today_schedule:
            for item in snap.today_schedule:
                now = now_utc()
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

    @Tool(
        "get_today_schedule",
        brief_description="Get today's schedule",
        detailed_description="Returns current and upcoming activities (up to 3, within 4 hours).",
        parameters=[],
    )
    async def get_today_schedule(self, **kwargs) -> dict:
        snap = self._plugin._manager.snapshot()
        tz = self._plugin._config.plugin.timezone
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
                hours_ahead = self._plugin._config.tool.upcoming_hours_ahead
                count = self._plugin._config.tool.upcoming_count
                if (item.start_time - now) <= timedelta(hours=hours_ahead):
                    if len(upcoming) < count:
                        upcoming.append({"time": time_str, "description": item.description})

        return {"current_item": current_item, "upcoming": upcoming}

    @Tool(
        "get_person_impression",
        brief_description="Get impression of a person",
        detailed_description="Parameter: person_name (string). Returns traits and affinity hint.",
        parameters=[
            ToolParameterInfo(
                name="person_name",
                param_type=ToolParamType.STRING,
                description="The display name of the person",
                required=True,
            ),
        ],
    )
    async def get_person_impression(self, person_name: str, **kwargs) -> dict | None:
        try:
            person_id = await self._plugin._ctx.person.get_id_by_name(person_name)
        except Exception:
            return None
        if not person_id:
            return None
        imp = await self._plugin._db.get_impression(person_id)
        if imp is None:
            return None
        return {
            "traits": imp.get("traits", []),
            "affinity_hint": affinity_to_hint(imp.get("affinity", 0.5)),
        }
```

- [ ] **Step 2: Commit**

```bash
git add components/tools.py
git commit -m "feat: Tool components for life state, schedule, impression"
```

---

### Task E3: API 组件（components/apis.py）和 Command（components/commands.py）

**Files:**
- Create: `components/apis.py`
- Create: `components/commands.py`

- [ ] **Step 1: 实现 components/apis.py**

```python
from __future__ import annotations
import dataclasses
import logging
from typing import Any

from maibot_sdk import API

from utils.hint_helper import affinity_to_hint
from utils.time_helper import to_local, now_utc

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


class LifeSimAPIs:
    def __init__(self, plugin: Any):
        self._plugin = plugin

    @API("life_sim.get_current_state")
    async def get_current_state(self, schema_version: str = "v1", **kwargs) -> dict:
        snap = self._plugin._manager.snapshot()
        builder = _DTO_BUILDERS.get(schema_version)
        if builder is None:
            return {"error": f"Unknown schema_version: {schema_version}"}
        return dataclasses.asdict(builder(snap))

    @API("life_sim.get_schedule")
    async def get_schedule(self, **kwargs) -> list[dict]:
        snap = self._plugin._manager.snapshot()
        tz = self._plugin._config.plugin.timezone
        return [
            {
                "start": to_local(item.start_time, tz).strftime("%H:%M"),
                "end": to_local(item.end_time, tz).strftime("%H:%M"),
                "activity": item.activity.value,
                "description": item.description,
            }
            for item in snap.today_schedule
        ]

    @API("life_sim.get_impression")
    async def get_impression(self, person_id: str, **kwargs) -> dict | None:
        imp = await self._plugin._db.get_impression(person_id)
        if imp is None:
            return None
        return {
            "traits": imp.get("traits", []),
            "affinity_hint": affinity_to_hint(imp.get("affinity", 0.5)),
        }

    @API("life_sim.get_frequency_factor")
    async def get_frequency_factor(self, **kwargs) -> float:
        snap = self._plugin._manager.snapshot()
        freq = self._plugin._config.frequency
        return freq.get(snap.current_activity.value, 0.0)

    @API("life_sim.get_sleep_state")
    async def get_sleep_state(self, **kwargs) -> str:
        return self._plugin._manager.snapshot().sleep_state.value
```

- [ ] **Step 2: 实现 components/commands.py**

```python
from __future__ import annotations
import logging
from typing import Any

from maibot_sdk import Command

from utils.time_helper import to_local, now_utc

logger = logging.getLogger(__name__)


class LifeSimCommands:
    def __init__(self, plugin: Any):
        self._plugin = plugin

    @Command("life_status", pattern=r"^/life_status")
    async def handle_life_status(self, **kwargs) -> tuple:
        stream_id = kwargs.get("stream_id", "")
        snap = self._plugin._manager.snapshot()
        tz = self._plugin._config.plugin.timezone
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

        text = "\n".join(lines)
        await self._plugin._ctx.send.text(text, stream_id)
        return True, text, 1
```

- [ ] **Step 3: Commit**

```bash
git add components/apis.py components/commands.py
git commit -m "feat: API components (DTO versioned) and /life_status command"
```

---

### Task E4: 插件入口（plugin.py）

**Files:**
- Create: `plugin.py`

- [ ] **Step 1: 实现 plugin.py**

```python
from __future__ import annotations
import logging
from typing import Any

from maibot_sdk import MaiBotPlugin

from core.state import LifeStateManager
from core.database import Database
from core.budget import ResourceBudget
from core.orchestrator import Orchestrator, BackgroundTaskRegistry, StreamRegistry
from systems.schedule import ScheduleSystem
from systems.relation import RelationSystem
from systems.proactive import ProactiveSystem
from components.hooks import LifeSimHooks
from components.tools import LifeSimTools
from components.apis import LifeSimAPIs
from components.commands import LifeSimCommands

logger = logging.getLogger(__name__)


class LifeSimulationPlugin(MaiBotPlugin):
    async def on_load(self) -> None:
        config = await self._load_config()

        self._config = config
        self._db = Database(f"data/life_simulation.db")
        self._manager = LifeStateManager(config)
        self._budget = ResourceBudget(config.budget)
        self._stream_registry = StreamRegistry()
        self._registry = BackgroundTaskRegistry()

        self._schedule_sys = ScheduleSystem(
            manager=self._manager, db=self._db,
            budget=self._budget, ctx=self.ctx, config=config,
        )
        self._relation = RelationSystem(
            db=self._db, ctx=self.ctx,
            budget=self._budget, config=config.relation,
        )
        self._proactive = ProactiveSystem(
            db=self._db, ctx=self.ctx,
            manager=self._manager, budget=self._budget, config=config,
        )

        self._orchestrator = Orchestrator(
            manager=self._manager,
            db=self._db,
            budget=self._budget,
            schedule_sys=self._schedule_sys,
            relation_sys=self._relation,
            proactive_sys=self._proactive,
            ctx=self.ctx,
            config=config,
            stream_registry=self._stream_registry,
        )

        # Component instances (decorators are declarative, bodies run on call)
        self._hooks = LifeSimHooks(self)
        self._tools = LifeSimTools(self)
        self._apis = LifeSimAPIs(self)
        self._commands = LifeSimCommands(self)

        await self._orchestrator.start()
        self.ctx.logger.info("Life Simulation Plugin loaded")

    async def on_unload(self) -> None:
        if hasattr(self, "_orchestrator"):
            await self._orchestrator.stop()
        self.ctx.logger.info("Life Simulation Plugin unloaded")

    async def on_config_update(
        self, scope: str, config_data: dict, version: str
    ) -> None:
        if scope == "self":
            config = self._parse_config(config_data)
            self._config = config
            self._orchestrator.reload_config(config)
            self.ctx.logger.info("Config updated, version=%s", version)

    async def _load_config(self) -> Any:
        raw = await self.ctx.config.get_all()
        return self._parse_config(raw)

    def _parse_config(self, raw: dict) -> Any:
        from types import SimpleNamespace

        def ns(d: dict) -> Any:
            obj = SimpleNamespace()
            for k, v in d.items():
                if isinstance(v, dict):
                    setattr(obj, k, ns(v))
                else:
                    setattr(obj, k, v)
            return obj

        defaults = {
            "plugin": {"enabled": True, "timezone": "Asia/Shanghai"},
            "schedule": {
                "sleep_start": "23:00", "sleep_end": "07:00",
                "breakfast_start": "07:30", "breakfast_end": "08:00",
                "lunch_start": "12:00", "lunch_end": "12:30",
                "dinner_start": "18:00", "dinner_end": "18:30",
            },
            "sleep": {"sleepy_duration_minutes": 30, "waking_duration_minutes": 15},
            "frequency": {
                "sleeping": -1.0, "exercising": -0.6,
                "studying": -0.4, "working": -0.4,
                "eating": -0.2, "leisure": 0.0, "other": 0.0,
            },
            "relation": {
                "min_update_interval_minutes": 30,
                "dirty_queue_max_size": 500,
                "dirty_queue_ttl_seconds": 7200,
            },
            "proactive": {
                "enabled": True,
                "schedule_transition_probability": 0.4,
                "waking_probability_factor": 0.3,
                "global_cooldown_minutes": 30,
                "per_group_cooldown_minutes": 60,
                "quiet_hours_start": "23:00",
                "quiet_hours_end": "07:00",
                "daily_limit": 5,
                "max_consecutive": 2,
                "consecutive_reset_after_minutes": 120,
                "score_threshold": 0.7,
                "debounce_seconds": 5,
            },
            "llm": {"timeout_seconds": 30, "max_retries": 2, "max_repair_attempts": 2},
            "budget": {
                "llm_schedule_per_day": 3,
                "llm_impression_per_hour": 50,
                "llm_proactive_intent_per_hour": 20,
                "dirty_flush_per_heartbeat": 10,
            },
            "db": {"checkpoint_interval_minutes": 60, "max_size_mb": 50},
            "heartbeat": {"interval_seconds": 600},
            "tool": {"upcoming_count": 3, "upcoming_hours_ahead": 4},
            "prompts": {"schedule_generation": "", "impression_update": "", "proactive_intent": ""},
        }

        # Deep merge raw over defaults
        def deep_merge(base: dict, override: dict) -> dict:
            result = dict(base)
            for k, v in override.items():
                if isinstance(v, dict) and isinstance(result.get(k), dict):
                    result[k] = deep_merge(result[k], v)
                else:
                    result[k] = v
            return result

        merged = deep_merge(defaults, raw or {})
        config = ns(merged)
        config.max_recent_events = 20
        return config


def create_plugin() -> LifeSimulationPlugin:
    return LifeSimulationPlugin()
```

- [ ] **Step 2: Commit**

```bash
git add plugin.py
git commit -m "feat: plugin.py entry point with full lifecycle management"
```

---

### Task E5: 全量测试与验证

- [ ] **Step 1: 运行全部单元测试**

```bash
pytest tests/ -v --tb=short
```

Expected: all passed (目标: 30+ tests)

- [ ] **Step 2: 检查 import 是否有循环依赖**

```bash
python -c "import plugin; print('import ok')"
```

Expected: import ok

- [ ] **Step 3: 验证 DB schema 正确创建**

```bash
python -c "
import asyncio
from core.database import Database
async def check():
    db = Database('/tmp/test_check.db')
    await db.start()
    await db.stop()
    print('DB ok')
asyncio.run(check())
"
```

Expected: DB ok

- [ ] **Step 4: 最终 commit**

```bash
git add -A
git commit -m "feat: v2.0 complete rewrite - all systems implemented"
```

---

## 自审清单（Self-Review）

### Spec 覆盖检查

| Spec 章节 | 计划任务 | 状态 |
|-----------|---------|------|
| 4.1 LifeStateManager | A4 | 覆盖 |
| 4.2 Database WAL 双连接 | A6 | 覆盖 |
| 4.3 Orchestrator 事件驱动 | B4 | 覆盖 |
| 4.4 ScheduleSystem + fallback | B2 | 覆盖 |
| 4.5 derive_sleep_state 纯函数 | A5 | 覆盖 |
| 4.6 StreamRegistry + 批量 set_adjust | B4（_apply_frequency） | 覆盖 |
| 4.7 RelationSystem + DirtyQueue | C1 | 覆盖 |
| 4.8 ProactiveSystem + guard + nonce | D1 | 覆盖 |
| 4.9 HookHandler 正确 SDK 名称 | E1 | 覆盖 |
| 4.10 Tool 摘要态 hint | E2 | 覆盖 |
| 4.11 API DTO versioned | E3 | 覆盖 |
| 4.12 ResourceBudget | B1 | 覆盖 |
| 4.13 llm_helper timeout/retry/schema | B1 | 覆盖 |
| 4.14 time_helper UTC | A2 | 覆盖 |
| hint_helper 共用 | A3 | 覆盖 |
| plugin.py 生命周期 | E4 | 覆盖 |
| person_stream 表 | A6 | 覆盖 |
| processed_transition 表 | A6 | 覆盖 |
| proactive_guard_state 表 | A6 + D1 | 覆盖 |
| budget_counter 表 | A6 | 覆盖（简化版） |

### 类型一致性确认

- `LifeStateSnapshot.today_schedule: tuple` ← A4 定义，B2/E2/E3 使用 ✓
- `LifeStateSnapshot.recent_events: tuple[RecentEvent, ...]` ← A4 定义，RecentEvent frozen ✓
- `derive_sleep_state(activity, activity_since, prev_activity, now, config)` ← A5 定义，A4 调用 ✓
- `calc_next_transition(snap, now) -> tuple[datetime, ActivityType]` ← B2 定义，B4 调用 ✓
- `get_missed_transitions(snap, now) -> list[tuple[ActivityType, datetime]]` ← B2 定义，B4 调用 ✓
- `Database.enqueue_write(op) -> asyncio.Future` ← A6 定义，B4 调用 ✓
- `RelationSystem.mark_interaction(person_id, stream_id, message)` ← C1 定义，E1 调用 ✓
- `ProactiveSystem.restore_guard(data: dict)` ← D1 定义，B4 调用 ✓

