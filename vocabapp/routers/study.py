import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from ..repo import CARD_COLUMNS, get_card, get_session, unpushed_review_count, with_conn
from ..schemas import CardOut, StudyAnswer, StudyCard, StudyState
from ..services import srs

router = APIRouter(prefix="/api", tags=["study"])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/sessions/{session_id}/study/next", response_model=StudyCard | None)
def next_card(session_id: int, conn: sqlite3.Connection = Depends(with_conn)):
    """Next approved card that is due, or None when the queue is empty."""
    if not get_session(conn, session_id):
        raise HTTPException(404, "session not found")

    now = _now_iso()
    row = conn.execute(
        f"""
        SELECT {', '.join('c.' + c.strip() for c in CARD_COLUMNS.split(','))},
               s.reps, s.interval_days
        FROM cards c LEFT JOIN card_srs s ON s.card_id = c.id
        WHERE c.session_id = ? AND c.status = 'approved'
          AND (s.due_at IS NULL OR s.due_at <= ?)
        ORDER BY (s.due_at IS NULL), s.due_at, c.id
        LIMIT 1
        """,
        (session_id, now),
    ).fetchone()
    if not row:
        return None

    data = dict(row)
    reps = data.pop("reps") or 0
    interval = data.pop("interval_days") or 0.0
    counts = _counts(conn, session_id)
    return StudyCard(
        card=CardOut(**data),
        due_count=counts["due_count"],
        new_count=counts["new_count"],
        reps=reps,
        interval_days=interval,
    )


@router.get("/sessions/{session_id}/study/state", response_model=StudyState)
def study_state(session_id: int, conn: sqlite3.Connection = Depends(with_conn)):
    if not get_session(conn, session_id):
        raise HTTPException(404, "session not found")
    counts = _counts(conn, session_id)
    return StudyState(
        **counts, unpushed_reviews=unpushed_review_count(conn, session_id)
    )


@router.post("/study/answer", response_model=StudyState)
def answer(payload: StudyAnswer, conn: sqlite3.Connection = Depends(with_conn)):
    card = get_card(conn, payload.card_id)
    if not card:
        raise HTTPException(404, "card not found")

    now = datetime.now(UTC)
    row = conn.execute(
        "SELECT * FROM card_srs WHERE card_id = ?", (payload.card_id,)
    ).fetchone()
    state = (
        srs.SrsState(
            due_at=datetime.fromisoformat(row["due_at"]),
            interval_days=row["interval_days"],
            ease_factor=row["ease_factor"],
            reps=row["reps"],
            lapses=row["lapses"],
        )
        if row
        else srs.new_state(now)
    )
    nxt = srs.review(state, payload.ease, now)

    conn.execute(
        """
        INSERT INTO card_srs (card_id, due_at, interval_days, ease_factor, reps, lapses)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(card_id) DO UPDATE SET
            due_at = excluded.due_at, interval_days = excluded.interval_days,
            ease_factor = excluded.ease_factor, reps = excluded.reps,
            lapses = excluded.lapses
        """,
        (
            payload.card_id,
            nxt.due_at.isoformat(),
            nxt.interval_days,
            nxt.ease_factor,
            nxt.reps,
            nxt.lapses,
        ),
    )
    conn.execute(
        "INSERT INTO reviews (card_id, ease, reviewed_at) VALUES (?, ?, ?)",
        (payload.card_id, payload.ease, now.isoformat()),
    )
    conn.commit()

    counts = _counts(conn, card["session_id"])
    return StudyState(
        **counts, unpushed_reviews=unpushed_review_count(conn, card["session_id"])
    )


def _counts(conn: sqlite3.Connection, session_id: int) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(s.card_id IS NULL), 0) AS new_count,
               COALESCE(SUM(s.card_id IS NOT NULL AND s.due_at <= ?), 0) AS due_now
        FROM cards c LEFT JOIN card_srs s ON s.card_id = c.id
        WHERE c.session_id = ? AND c.status = 'approved'
        """,
        (_now_iso(), session_id),
    ).fetchone()
    new_count = row["new_count"] or 0
    return {
        "total": row["total"] or 0,
        "new_count": new_count,
        "due_count": (row["due_now"] or 0) + new_count,
    }
