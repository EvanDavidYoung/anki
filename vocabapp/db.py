"""SQLite persistence for the web app.

Deliberately separate from ``anki_client.store.MessageStore`` — that store models
the Slack/chatlog ingest pipeline, while this one models paste-a-text sessions,
card approval state, quizzes, and local study progress.
"""

import sqlite3
from pathlib import Path

from .config import get_app_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    source_text TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cards (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    traditional          TEXT NOT NULL,
    pinyin               TEXT NOT NULL DEFAULT '',
    meaning              TEXT NOT NULL DEFAULT '',
    part_of_speech       TEXT NOT NULL DEFAULT '',
    sentence_traditional TEXT NOT NULL DEFAULT '',
    sentence_pinyin      TEXT NOT NULL DEFAULT '',
    sentence_meaning     TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'pending',
    anki_note_id         INTEGER,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cards_session ON cards(session_id);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    card_id      INTEGER REFERENCES cards(id) ON DELETE SET NULL,
    prompt       TEXT NOT NULL,
    choices      TEXT NOT NULL,
    answer_index INTEGER NOT NULL,
    explanation  TEXT NOT NULL DEFAULT '',
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_questions_session ON quiz_questions(session_id);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    chosen_index INTEGER NOT NULL,
    correct      INTEGER NOT NULL,
    answered_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON quiz_attempts(question_id);

CREATE TABLE IF NOT EXISTS card_srs (
    card_id       INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    due_at        TEXT NOT NULL,
    interval_days REAL NOT NULL DEFAULT 0,
    ease_factor   REAL NOT NULL DEFAULT 2.5,
    reps          INTEGER NOT NULL DEFAULT 0,
    lapses        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    ease        INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL DEFAULT (datetime('now')),
    pushed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_card ON reviews(card_id);
"""

_db_path_override: Path | None = None


def set_db_path(path: Path | None) -> None:
    """Point the app at a different database file (used by tests)."""
    global _db_path_override
    _db_path_override = path


def db_path() -> Path:
    return _db_path_override or get_app_settings().db_path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema() -> None:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
