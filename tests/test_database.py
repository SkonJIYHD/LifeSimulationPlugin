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
