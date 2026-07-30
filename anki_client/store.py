"""SQLite-backed store of parsed chat messages.

Sits upstream of Anki: source files are parsed into typed :class:`Message`
rows here (deduped by ``content_hash``) before being batched into
card-generation requests. Provenance lives on the row (``source_file``), so the
source ``.md`` can be retired right after parsing, and batching may freely span
files. Card review/approval still happens in Anki; this store only tracks
whether a message has yet produced card(s).

State machine:  ``new`` → ``staged`` (cards in the Anki Staging deck) → ``done``.
``image-only`` rows stay ``new`` until the future vision path consumes them.
"""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from .config import get_settings
from .sources.base import ImageRef, Message

STATE_NEW = "new"
STATE_STAGED = "staged"
STATE_DONE = "done"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file    TEXT NOT NULL,
    kind           TEXT NOT NULL,
    author         TEXT NOT NULL DEFAULT '',
    ts             TEXT NOT NULL DEFAULT '',
    text           TEXT NOT NULL DEFAULT '',
    image_refs     TEXT NOT NULL DEFAULT '[]',
    priority_terms TEXT NOT NULL DEFAULT '[]',
    content_hash   TEXT NOT NULL UNIQUE,
    state          TEXT NOT NULL DEFAULT 'new',
    batch_id       TEXT,
    note_ids       TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_state_kind ON messages (state, kind);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages (source_file);
"""


class StoredMessage(Message):
    """A :class:`Message` with its persisted row id and lifecycle state."""

    id: int
    state: str = STATE_NEW
    batch_id: str | None = None
    note_ids: list[int] = []


class MessageStore:
    def __init__(self, db_path: Path | None = None):
        self._path = db_path or get_settings().message_db
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def add_messages(self, messages: list[Message]) -> list[int]:
        """Insert messages, skipping any whose content_hash already exists.

        Returns the row ids of the newly inserted messages (idempotent on
        re-parse of the same source file)."""
        new_ids: list[int] = []
        with self._connect() as conn:
            for msg in messages:
                content_hash = msg.content_hash or msg.compute_hash()
                cur = conn.execute(
                    """INSERT OR IGNORE INTO messages
                       (source_file, kind, author, ts, text, image_refs,
                        priority_terms, content_hash, state)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        msg.source_file,
                        msg.kind,
                        msg.author,
                        msg.ts,
                        msg.text,
                        json.dumps([r.model_dump() for r in msg.image_refs]),
                        json.dumps(msg.priority_terms, ensure_ascii=False),
                        content_hash,
                        STATE_NEW,
                    ),
                )
                if cur.rowcount:
                    new_ids.append(cur.lastrowid)
        return new_ids

    def mark_staged(self, message_ids: list[int], batch_id: str, note_ids: list[int]) -> None:
        if not message_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE messages SET state=?, batch_id=?, note_ids=? WHERE id=?",
                [
                    (STATE_STAGED, batch_id, json.dumps(note_ids), mid)
                    for mid in message_ids
                ],
            )

    def mark_done(self, message_ids: list[int]) -> None:
        self.set_state(message_ids, STATE_DONE)

    def set_state(self, message_ids: list[int], state: str) -> None:
        if not message_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE messages SET state=? WHERE id=?",
                [(state, mid) for mid in message_ids],
            )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def pending_text(self, limit: int | None = None) -> list[StoredMessage]:
        """New, text-bearing messages awaiting card generation, oldest first."""
        sql = (
            "SELECT * FROM messages WHERE state=? AND kind IN ('text','text+image') "
            "ORDER BY source_file, ts, id"
        )
        params: tuple = (STATE_NEW,)
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_message(r) for r in rows]

    def iter_text_batches(self, size: int) -> Iterator[list[StoredMessage]]:
        """Chunk pending text messages into batches of ``size``."""
        pending = self.pending_text()
        for i in range(0, len(pending), size):
            yield pending[i : i + size]

    def stats(self) -> list[dict]:
        """Counts grouped by (kind, state) for visibility / the future web app."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, state, COUNT(*) AS n FROM messages GROUP BY kind, state "
                "ORDER BY kind, state"
            ).fetchall()
        return [{"kind": r["kind"], "state": r["state"], "count": r["n"]} for r in rows]


def _row_to_message(row: sqlite3.Row) -> StoredMessage:
    return StoredMessage(
        id=row["id"],
        source_file=row["source_file"],
        kind=row["kind"],
        author=row["author"],
        ts=row["ts"],
        text=row["text"],
        image_refs=[ImageRef(**d) for d in json.loads(row["image_refs"])],
        priority_terms=json.loads(row["priority_terms"]),
        content_hash=row["content_hash"],
        state=row["state"],
        batch_id=row["batch_id"],
        note_ids=json.loads(row["note_ids"]),
    )
