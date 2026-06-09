# tests/test_database.py
import pytest
import asyncio
import time
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


@pytest.mark.asyncio
async def test_enqueue_write_awaits_commit(db):
    """Fix 1: enqueue_write future should resolve only after commit."""
    committed = []

    async def op(c):
        await c.execute(
            "INSERT INTO life_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("test_key", '"test_val"', time.time()),
        )
        committed.append(True)

    fut = await db.enqueue_write(op)
    result = await fut
    assert result is True
    assert len(committed) == 1


@pytest.mark.asyncio
async def test_save_and_load_processed_transition(db):
    """Fix 2: processed_transition should persist and load correctly."""
    await db.save_processed_transition("transition:2026-01-01T08:00:00:eating", ttl=86400)
    await db.save_processed_transition("transition:2026-01-01T09:00:00:working", ttl=86400)

    loaded = await db.load_processed_transitions_unexpired()
    assert "transition:2026-01-01T08:00:00:eating" in loaded
    assert "transition:2026-01-01T09:00:00:working" in loaded


@pytest.mark.asyncio
async def test_expired_transitions_not_loaded(db):
    """Fix 2: expired transitions should not be returned."""
    await db.save_processed_transition("expired_one", ttl=0)
    # ttl=0 means expires_at = now, so it should be expired
    loaded = await db.load_processed_transitions_unexpired()
    assert "expired_one" not in loaded


@pytest.mark.asyncio
async def test_mark_dirty_new_user_creates_row(db):
    """Fix 7: mark_dirty should create a row for new users (upsert)."""
    await db.mark_dirty("new_user_123")
    dirty = await db.get_dirty_persons()
    ids = [d["person_id"] for d in dirty]
    assert "new_user_123" in ids


@pytest.mark.asyncio
async def test_mark_dirty_existing_user(db):
    """Fix 7: mark_dirty should set dirty=1 for existing users."""
    imp = {"person_id": "p2", "person_name": "Bob", "traits": [],
           "affinity": 0.5, "proactive_score": 0.0, "proactive_cooldown_until": None,
           "last_interaction": None, "last_impression_update": None, "dirty": 0}
    await db.save_impression(imp)
    await db.mark_dirty("p2")
    dirty = await db.get_dirty_persons()
    ids = [d["person_id"] for d in dirty]
    assert "p2" in ids
