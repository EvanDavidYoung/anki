"""Shared SQL helpers. Routers hold HTTP concerns, this holds the queries."""

import sqlite3

from .db import connect

CARD_COLUMNS = (
    "id, session_id, traditional, pinyin, meaning, part_of_speech, "
    "sentence_traditional, sentence_pinyin, sentence_meaning, status, anki_note_id"
)

EDITABLE_FIELDS = (
    "traditional",
    "pinyin",
    "meaning",
    "part_of_speech",
    "sentence_traditional",
    "sentence_pinyin",
    "sentence_meaning",
)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def session_counts(conn: sqlite3.Connection, session_id: int) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS card_count,
               SUM(status = 'approved') AS approved_count,
               SUM(status = 'pending')  AS pending_count
        FROM cards WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    return {
        "card_count": row["card_count"] or 0,
        "approved_count": row["approved_count"] or 0,
        "pending_count": row["pending_count"] or 0,
    }


def get_cards(conn: sqlite3.Connection, session_id: int, status: str = "") -> list[dict]:
    sql = f"SELECT {CARD_COLUMNS} FROM cards WHERE session_id = ?"
    params: list = [session_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id"
    return rows_to_dicts(conn.execute(sql, params).fetchall())


def get_card(conn: sqlite3.Connection, card_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {CARD_COLUMNS} FROM cards WHERE id = ?", (card_id,)
    ).fetchone()
    return dict(row) if row else None


def unpushed_reviews(conn: sqlite3.Connection, session_id: int | None = None) -> list[dict]:
    """Latest unpushed review per card, for cards that made it into Anki.

    Anki cannot replay review history, so only the most recent grade per card
    is worth sending.
    """
    sql = """
        SELECT r.card_id, c.traditional, c.anki_note_id, r.ease,
               MAX(r.id) AS review_id
        FROM reviews r
        JOIN cards c ON c.id = r.card_id
        WHERE r.pushed_at IS NULL AND c.anki_note_id IS NOT NULL
    """
    params: list = []
    if session_id is not None:
        sql += " AND c.session_id = ?"
        params.append(session_id)
    sql += " GROUP BY r.card_id ORDER BY r.card_id"
    return rows_to_dicts(conn.execute(sql, params).fetchall())


def unpushed_review_count(conn: sqlite3.Connection, session_id: int | None = None) -> int:
    return len(unpushed_reviews(conn, session_id))


def with_conn():
    """FastAPI dependency yielding a connection that commits on success."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
