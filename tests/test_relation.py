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


def test_dirty_queue_requeue():
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
    ctx = MagicMock()
    budget = MagicMock()
    budget.get_flush_limit.return_value = 10
    config = MagicMock()
    config.min_update_interval_minutes = 30
    config.dirty_queue_max_size = 500
    config.dirty_queue_ttl_seconds = 7200
    sys = RelationSystem(db=db, ctx=ctx, budget=budget, config=config)
    await sys.mark_interaction("p1", "stream-1", {"message_id": "m1"})
    db.update_person_stream.assert_awaited_once()
    db.mark_dirty.assert_awaited_once_with("p1")


@pytest.mark.asyncio
async def test_flush_preserves_last_interaction():
    """Fix 6: impression refresh should preserve last_interaction from old impression."""
    import time as _time
    from datetime import datetime, timezone

    old_interaction_ts = _time.time() - 86400 * 5  # 5 days ago

    db = MagicMock()
    db.get_impression = AsyncMock(return_value={
        "person_id": "p1",
        "person_name": "Alice",
        "traits": ["kind"],
        "affinity": 0.5,
        "proactive_score": 0.3,
        "last_interaction": old_interaction_ts,
        "last_impression_update": _time.time() - 3600,
    })
    db.save_impression = AsyncMock()
    db.enqueue_write = AsyncMock(return_value=AsyncMock())

    ctx = MagicMock()
    ctx.message.get_recent = AsyncMock(return_value=[])

    budget = MagicMock()
    budget.get_flush_limit.return_value = 10
    budget.can_llm_call.return_value = True
    budget.record_llm = MagicMock()

    config = MagicMock()
    config.min_update_interval_minutes = 30
    config.dirty_queue_max_size = 500
    config.dirty_queue_ttl_seconds = 7200
    config.prompts.impression_update = ""

    sys = RelationSystem(db=db, ctx=ctx, budget=budget, config=config)
    sys._dirty_queue.mark("p1", "stream-1")

    import unittest.mock as um

    with um.patch("utils.llm_helper.generate_json", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {
            "traits": ["friendly"],
            "affinity": 0.6,
            "had_recent_interaction": False,
        }
        await sys.flush_dirty_impressions()

    saved_imp = db.save_impression.call_args[0][0]
    assert "last_interaction" in saved_imp
    assert saved_imp["last_interaction"] == old_interaction_ts
