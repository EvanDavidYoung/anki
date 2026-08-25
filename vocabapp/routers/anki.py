import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from anki_client.client import AnkiConnectError

from ..config import get_app_settings
from ..repo import get_cards, get_session, unpushed_reviews, with_conn
from ..schemas import (
    AnkiStatus,
    ExportRequest,
    ExportResult,
    PushedReview,
    PushReviewsRequest,
    PushReviewsResult,
)
from ..services import ankisync

router = APIRouter(prefix="/api/anki", tags=["anki"])

ANKI_DOWN = "Anki isn't reachable. Open Anki with the AnkiConnect add-on, or use .apkg export."


@router.get("/status", response_model=AnkiStatus)
def anki_status():
    return AnkiStatus(**ankisync.status())


@router.post("/export", response_model=ExportResult)
def export(payload: ExportRequest, conn: sqlite3.Connection = Depends(with_conn)):
    """Blocking (AnkiConnect + optional TTS) — sync so it runs in a threadpool."""
    rows = _approved_rows(conn, payload.session_id, only_unexported=True)
    deck = payload.deck.strip() or get_app_settings().default_deck

    try:
        result = ankisync.export_cards(rows, deck, with_audio=payload.with_audio)
    except (httpx.HTTPError, OSError) as exc:
        raise HTTPException(503, f"{ANKI_DOWN} ({exc})") from exc
    except AnkiConnectError as exc:
        raise HTTPException(502, f"AnkiConnect rejected the export: {exc}") from exc

    for card_id, note_id in result["row_notes"].items():
        conn.execute("UPDATE cards SET anki_note_id = ? WHERE id = ?", (note_id, card_id))
    conn.commit()
    return ExportResult(
        added=result["added"],
        duplicates=result["duplicates"],
        errors=result["errors"],
        note_ids=result["note_ids"],
        deck=deck,
    )


@router.get("/apkg")
def export_apkg(
    session_id: int, deck: str = "", conn: sqlite3.Connection = Depends(with_conn)
):
    """Always available, Anki running or not."""
    session = get_session(conn, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    rows = _approved_rows(conn, session_id)
    deck = deck.strip() or get_app_settings().default_deck

    tmp = Path(tempfile.mkdtemp()) / f"{_slug(session['title'])}.apkg"
    ankisync.build_apkg(rows, deck, str(tmp))
    return FileResponse(
        tmp,
        media_type="application/octet-stream",
        filename=tmp.name,
        background=BackgroundTask(lambda: tmp.unlink(missing_ok=True)),
    )


@router.post("/push-reviews", response_model=PushReviewsResult)
def push_reviews(
    payload: PushReviewsRequest, conn: sqlite3.Connection = Depends(with_conn)
):
    pending = unpushed_reviews(conn, payload.session_id)
    if not pending:
        return PushReviewsResult(attempted=0, pushed=0, results=[])

    try:
        results = ankisync.push_reviews(pending)
    except (httpx.HTTPError, OSError) as exc:
        raise HTTPException(503, f"{ANKI_DOWN} ({exc})") from exc
    except AnkiConnectError as exc:
        raise HTTPException(502, f"AnkiConnect rejected the reviews: {exc}") from exc

    now = datetime.now(UTC).isoformat()
    # Only mark reviews pushed when Anki actually accepted them; the rest stay
    # unpushed so a later attempt (once they're due) can retry.
    for row, result in zip(pending, results):
        if result["pushed"]:
            conn.execute(
                "UPDATE reviews SET pushed_at = ? WHERE card_id = ? AND pushed_at IS NULL",
                (now, row["card_id"]),
            )
    conn.commit()

    return PushReviewsResult(
        attempted=len(results),
        pushed=sum(1 for r in results if r["pushed"]),
        results=[
            PushedReview(
                card_id=r["card_id"],
                traditional=r["traditional"],
                ease=r["ease"],
                pushed=bool(r["pushed"]),
                reason=r.get("reason", ""),
            )
            for r in results
        ],
    )


def _approved_rows(
    conn: sqlite3.Connection, session_id: int, only_unexported: bool = False
) -> list[dict]:
    if not get_session(conn, session_id):
        raise HTTPException(404, "session not found")
    rows = get_cards(conn, session_id, status="approved")
    if only_unexported:
        rows = [r for r in rows if not r["anki_note_id"]]
    if not rows:
        raise HTTPException(422, "no approved cards left to export in this session")
    return rows


def _slug(title: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in title).strip("-")
    return safe[:40] or "vocab"
