import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..repo import EDITABLE_FIELDS, get_card, get_cards, get_session, with_conn
from ..schemas import BulkStatus, CardOut, CardUpdate

router = APIRouter(prefix="/api", tags=["cards"])

VALID_STATUSES = {"pending", "approved", "rejected"}


@router.patch("/cards/{card_id}", response_model=CardOut)
def update_card(
    card_id: int, payload: CardUpdate, conn: sqlite3.Connection = Depends(with_conn)
):
    changes = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if k in EDITABLE_FIELDS and v is not None
    }
    if not changes:
        raise HTTPException(400, "no editable fields supplied")
    if not get_card(conn, card_id):
        raise HTTPException(404, "card not found")

    assignments = ", ".join(f"{k} = ?" for k in changes)
    conn.execute(
        f"UPDATE cards SET {assignments} WHERE id = ?", [*changes.values(), card_id]
    )
    conn.commit()
    return CardOut(**get_card(conn, card_id))


@router.post("/cards/{card_id}/{action}", response_model=CardOut)
def set_card_status(
    card_id: int, action: str, conn: sqlite3.Connection = Depends(with_conn)
):
    status = {"approve": "approved", "reject": "rejected", "reset": "pending"}.get(action)
    if not status:
        raise HTTPException(404, f"unknown action {action!r}")
    if not get_card(conn, card_id):
        raise HTTPException(404, "card not found")
    conn.execute("UPDATE cards SET status = ? WHERE id = ?", (status, card_id))
    conn.commit()
    return CardOut(**get_card(conn, card_id))


@router.post("/sessions/{session_id}/cards/bulk", response_model=list[CardOut])
def bulk_status(
    session_id: int, payload: BulkStatus, conn: sqlite3.Connection = Depends(with_conn)
):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(VALID_STATUSES)}")
    if not get_session(conn, session_id):
        raise HTTPException(404, "session not found")

    if payload.card_ids:
        placeholders = ",".join("?" * len(payload.card_ids))
        conn.execute(
            f"UPDATE cards SET status = ? WHERE session_id = ? AND id IN ({placeholders})",
            [payload.status, session_id, *payload.card_ids],
        )
    else:
        # No explicit ids means "everything still undecided".
        conn.execute(
            "UPDATE cards SET status = ? WHERE session_id = ? AND status = 'pending'",
            (payload.status, session_id),
        )
    conn.commit()
    return [CardOut(**c) for c in get_cards(conn, session_id)]
