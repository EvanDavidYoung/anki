import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..repo import get_cards, get_session, session_counts, with_conn
from ..schemas import SessionCreate, SessionDetail, SessionOut
from ..services import vocab

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionDetail)
def create_session(payload: SessionCreate, conn: sqlite3.Connection = Depends(with_conn)):
    """Sync (not async) on purpose: the LLM client is blocking, so Starlette
    runs this in a threadpool instead of stalling the event loop."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "text is empty")

    try:
        cards = vocab.extract(text, payload.title)
    except Exception as exc:  # LLM/network/parse — surface it, don't 500 blindly
        raise HTTPException(502, f"Vocab generation failed: {exc}") from exc
    if not cards:
        raise HTTPException(422, "The model returned no vocabulary for this text.")

    title = payload.title.strip() or text[:40].replace("\n", " ")
    cur = conn.execute(
        "INSERT INTO sessions (title, source_text) VALUES (?, ?)", (title, text)
    )
    session_id = cur.lastrowid
    conn.executemany(
        """
        INSERT INTO cards (session_id, traditional, pinyin, meaning, part_of_speech,
                           sentence_traditional, sentence_pinyin, sentence_meaning)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                session_id,
                c.traditional,
                c.pinyin,
                c.meaning,
                c.part_of_speech,
                c.sentence_traditional,
                c.sentence_pinyin,
                c.sentence_meaning,
            )
            for c in cards
        ],
    )
    conn.commit()
    return _detail(conn, session_id)


@router.get("", response_model=list[SessionOut])
def list_sessions(conn: sqlite3.Connection = Depends(with_conn)):
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.created_at,
               COUNT(c.id) AS card_count,
               COALESCE(SUM(c.status = 'approved'), 0) AS approved_count,
               COALESCE(SUM(c.status = 'pending'), 0)  AS pending_count
        FROM sessions s LEFT JOIN cards c ON c.session_id = s.id
        GROUP BY s.id ORDER BY s.id DESC
        """
    ).fetchall()
    return [SessionOut(**dict(r)) for r in rows]


@router.get("/{session_id}", response_model=SessionDetail)
def get_session_detail(session_id: int, conn: sqlite3.Connection = Depends(with_conn)):
    return _detail(conn, session_id)


@router.delete("/{session_id}")
def delete_session(session_id: int, conn: sqlite3.Connection = Depends(with_conn)):
    if not get_session(conn, session_id):
        raise HTTPException(404, "session not found")
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return {"deleted": session_id}


def _detail(conn: sqlite3.Connection, session_id: int) -> SessionDetail:
    session = get_session(conn, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    return SessionDetail(
        **session, **session_counts(conn, session_id), cards=get_cards(conn, session_id)
    )
