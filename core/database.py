from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Any, Callable

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS life_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS person_impression (
    person_id TEXT PRIMARY KEY,
    person_name TEXT NOT NULL,
    traits TEXT NOT NULL DEFAULT '[]',
    affinity REAL NOT NULL DEFAULT 0.5,
    proactive_score REAL NOT NULL DEFAULT 0.0,
    proactive_cooldown_until REAL,
    last_interaction REAL,
    last_impression_update REAL,
    dirty INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS person_stream (
    person_id TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    last_seen REAL NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (person_id, stream_id)
);
CREATE TABLE IF NOT EXISTS proactive_nonce (
    nonce TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_transition (
    transition_id TEXT PRIMARY KEY,
    processed_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_counter (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    window_start TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS proactive_guard_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self._path = path
        self._write_conn: aiosqlite.Connection | None = None
        self._read_conn: aiosqlite.Connection | None = None
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._write_conn = await aiosqlite.connect(self._path)
        self._read_conn = await aiosqlite.connect(self._path)
        for conn in (self._write_conn, self._read_conn):
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
        await self._write_conn.executescript(_SCHEMA)
        await self._write_conn.commit()
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        try:
            while True:
                op, fut = await self._write_queue.get()
                try:
                    await self._write_conn.execute("BEGIN")
                    await op(self._write_conn)
                    await self._write_conn.commit()
                    if not fut.done():
                        fut.set_result(True)
                except asyncio.CancelledError:
                    try:
                        await self._write_conn.rollback()
                    except Exception:
                        pass
                    if not fut.done():
                        fut.cancel()
                    raise
                except Exception as e:
                    logger.error("DB write error: %s", e, exc_info=True)
                    try:
                        await self._write_conn.rollback()
                    except Exception:
                        logger.error("DB rollback failed")
                    if not fut.done():
                        fut.set_exception(e)
                finally:
                    self._write_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        await self._write_queue.join()
        if self._writer_task:
            self._writer_task.cancel()
            await asyncio.gather(self._writer_task, return_exceptions=True)
        if self._write_conn:
            try:
                await self._write_conn.execute("PRAGMA wal_checkpoint(FULL);")
            except Exception:
                pass
            await self._write_conn.close()
        if self._read_conn:
            await self._read_conn.close()

    async def enqueue_write(self, op: Callable) -> asyncio.Future:
        fut = asyncio.get_event_loop().create_future()
        await self._write_queue.put((op, fut))
        return fut

    # ── State ──────────────────────────────────────────────────────────────

    async def save_state(self, data: dict) -> None:
        s, now = json.dumps(data), time.time()

        async def op(c):
            await c.execute(
                "INSERT OR REPLACE INTO life_state (key, value, updated_at) VALUES (?, ?, ?)",
                ("main", s, now),
            )

        await (await self.enqueue_write(op))

    async def load_state(self) -> dict | None:
        async with self._read_conn.execute(
            "SELECT value FROM life_state WHERE key = ?", ("main",)
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    # ── Impression ─────────────────────────────────────────────────────────

    async def save_impression(self, imp: dict) -> None:
        now = time.time()
        traits = json.dumps(imp.get("traits", []))

        async def op(c):
            await c.execute(
                "INSERT OR REPLACE INTO person_impression "
                "(person_id, person_name, traits, affinity, proactive_score, "
                "proactive_cooldown_until, last_interaction, last_impression_update, dirty) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    imp["person_id"],
                    imp["person_name"],
                    traits,
                    imp.get("affinity", 0.5),
                    imp.get("proactive_score", 0.0),
                    imp.get("proactive_cooldown_until"),
                    imp.get("last_interaction", now),
                    imp.get("last_impression_update", now),
                    0,
                ),
            )

        await (await self.enqueue_write(op))

    async def get_impression(self, person_id: str) -> dict | None:
        async with self._read_conn.execute(
            "SELECT person_id, person_name, traits, affinity, proactive_score, "
            "proactive_cooldown_until, last_interaction, last_impression_update, dirty "
            "FROM person_impression WHERE person_id = ?",
            (person_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        keys = [
            "person_id",
            "person_name",
            "traits",
            "affinity",
            "proactive_score",
            "proactive_cooldown_until",
            "last_interaction",
            "last_impression_update",
            "dirty",
        ]
        d = dict(zip(keys, row))
        d["traits"] = json.loads(d["traits"])
        return d

    async def mark_dirty(self, person_id: str) -> None:
        async def op(c):
            await c.execute(
                "INSERT INTO person_impression (person_id, person_name, traits, dirty) "
                "VALUES (?, '', '[]', 1) "
                "ON CONFLICT(person_id) DO UPDATE SET dirty = 1",
                (person_id,),
            )

        await (await self.enqueue_write(op))

    async def get_dirty_persons(self) -> list[dict]:
        async with self._read_conn.execute(
            "SELECT person_id FROM person_impression WHERE dirty = 1"
        ) as cur:
            rows = await cur.fetchall()
        return [{"person_id": r[0]} for r in rows]

    async def get_persons_above_score(self, threshold: float) -> list[dict]:
        async with self._read_conn.execute(
            "SELECT person_id, person_name, proactive_score FROM person_impression "
            "WHERE proactive_score >= ? AND "
            "(proactive_cooldown_until IS NULL OR proactive_cooldown_until < ?)",
            (threshold, time.time()),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {"person_id": r[0], "person_name": r[1], "proactive_score": r[2]}
            for r in rows
        ]

    # ── PersonStream ───────────────────────────────────────────────────────

    async def update_person_stream(
        self, person_id: str, stream_id: str, ts: float
    ) -> None:
        async def op(c):
            await c.execute(
                "INSERT INTO person_stream (person_id, stream_id, last_seen, message_count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(person_id, stream_id) DO UPDATE SET "
                "last_seen = excluded.last_seen, message_count = message_count + 1",
                (person_id, stream_id, ts),
            )

        await (await self.enqueue_write(op))

    async def get_best_stream_for_person(self, person_id: str) -> dict | None:
        async with self._read_conn.execute(
            "SELECT stream_id, last_seen FROM person_stream "
            "WHERE person_id = ? ORDER BY last_seen DESC LIMIT 1",
            (person_id,),
        ) as cur:
            row = await cur.fetchone()
        return {"stream_id": row[0], "last_seen": row[1]} if row else None

    # ── Nonce ──────────────────────────────────────────────────────────────

    async def register_nonce(self, nonce: str, stream_id: str, ttl: int) -> None:
        now = time.time()

        async def op(c):
            await c.execute(
                "INSERT OR IGNORE INTO proactive_nonce "
                "(nonce, stream_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (nonce, stream_id, now, now + ttl),
            )

        await (await self.enqueue_write(op))

    async def nonce_exists(self, nonce: str) -> bool:
        async with self._read_conn.execute(
            "SELECT 1 FROM proactive_nonce WHERE nonce = ? AND expires_at > ?",
            (nonce, time.time()),
        ) as cur:
            return await cur.fetchone() is not None

    async def delete_nonce(self, nonce: str) -> None:
        async def op(c):
            await c.execute(
                "DELETE FROM proactive_nonce WHERE nonce = ?", (nonce,)
            )

        await (await self.enqueue_write(op))

    # ── ProcessedTransition ────────────────────────────────────────────────

    async def save_processed_transition(self, transition_id: str, ttl: int = 86400) -> None:
        now = time.time()

        async def op(c):
            await c.execute(
                "INSERT OR REPLACE INTO processed_transition "
                "(transition_id, processed_at, expires_at) VALUES (?, ?, ?)",
                (transition_id, now, now + ttl),
            )

        await (await self.enqueue_write(op))

    async def load_processed_transitions_unexpired(self) -> dict[str, float]:
        async with self._read_conn.execute(
            "SELECT transition_id, expires_at FROM processed_transition WHERE expires_at > ?",
            (time.time(),),
        ) as cur:
            rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

    # ── ProactiveGuard ─────────────────────────────────────────────────────

    async def save_proactive_guard_state(self, data: dict) -> None:
        now = time.time()

        async def op(c):
            await c.execute(
                "INSERT OR REPLACE INTO proactive_guard_state (key, value, updated_at) "
                "VALUES (?, ?, ?)",
                ("main", json.dumps(data), now),
            )

        await (await self.enqueue_write(op))

    async def load_proactive_guard_state(self) -> dict | None:
        async with self._read_conn.execute(
            "SELECT value FROM proactive_guard_state WHERE key = ?", ("main",)
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    # ── Cleanup & Maintenance ──────────────────────────────────────────────

    async def cleanup_expired(self) -> None:
        now = time.time()

        async def op(c):
            await c.execute(
                "DELETE FROM proactive_nonce WHERE expires_at < ?", (now,)
            )
            await c.execute(
                "DELETE FROM processed_transition WHERE expires_at < ?", (now,)
            )

        await (await self.enqueue_write(op))

    async def maybe_checkpoint(self) -> None:
        async def op(c):
            await c.execute("PRAGMA wal_checkpoint(PASSIVE);")

        await (await self.enqueue_write(op))
