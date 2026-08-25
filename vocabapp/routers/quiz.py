import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..repo import get_cards, get_session, with_conn
from ..schemas import AnswerIn, AnswerOut, QuestionOut, QuizCreate, QuizStats
from ..services import quiz as quiz_service
from ..services.quiz import QuizGenerationError

router = APIRouter(prefix="/api", tags=["quiz"])


@router.post("/sessions/{session_id}/quiz", response_model=list[QuestionOut])
def create_quiz(
    session_id: int, payload: QuizCreate, conn: sqlite3.Connection = Depends(with_conn)
):
    """Blocking LLM call — kept sync so Starlette runs it in a threadpool."""
    session = get_session(conn, session_id)
    if not session:
        raise HTTPException(404, "session not found")

    # Quiz the approved cards if any have been approved, else everything
    # still on the table — so you can quiz before finishing the review pass.
    cards = get_cards(conn, session_id, status="approved")
    if not cards:
        cards = [c for c in get_cards(conn, session_id) if c["status"] != "rejected"]
    if not cards:
        raise HTTPException(422, "no cards to quiz on")

    try:
        questions = quiz_service.generate(session["source_text"], cards, payload.n)
    except QuizGenerationError as exc:
        raise HTTPException(502, f"Quiz generation failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Quiz generation failed: {exc}") from exc

    by_word = {c["traditional"]: c["id"] for c in cards}
    conn.execute("DELETE FROM quiz_questions WHERE session_id = ?", (session_id,))
    conn.executemany(
        """
        INSERT INTO quiz_questions
            (session_id, card_id, prompt, choices, answer_index, explanation, position)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                session_id,
                by_word.get(q["word"]),
                q["prompt"],
                json.dumps(q["choices"], ensure_ascii=False),
                q["answer_index"],
                q["explanation"],
                i,
            )
            for i, q in enumerate(questions)
        ],
    )
    conn.commit()
    return _questions(conn, session_id)


@router.get("/sessions/{session_id}/quiz", response_model=list[QuestionOut])
def get_quiz(session_id: int, conn: sqlite3.Connection = Depends(with_conn)):
    if not get_session(conn, session_id):
        raise HTTPException(404, "session not found")
    return _questions(conn, session_id)


@router.get("/sessions/{session_id}/quiz/stats", response_model=QuizStats)
def quiz_stats(session_id: int, conn: sqlite3.Connection = Depends(with_conn)):
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT q.id) AS total,
               COUNT(DISTINCT a.question_id) AS answered,
               COALESCE(SUM(a.correct), 0) AS correct
        FROM quiz_questions q LEFT JOIN quiz_attempts a ON a.question_id = q.id
        WHERE q.session_id = ?
        """,
        (session_id,),
    ).fetchone()
    return QuizStats(**dict(row))


@router.post("/quiz/questions/{question_id}/answer", response_model=AnswerOut)
def answer_question(
    question_id: int, payload: AnswerIn, conn: sqlite3.Connection = Depends(with_conn)
):
    row = conn.execute(
        "SELECT answer_index, explanation, choices FROM quiz_questions WHERE id = ?",
        (question_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "question not found")
    if payload.chosen_index >= len(json.loads(row["choices"])):
        raise HTTPException(400, "chosen_index out of range")

    correct = payload.chosen_index == row["answer_index"]
    conn.execute(
        "INSERT INTO quiz_attempts (question_id, chosen_index, correct) VALUES (?, ?, ?)",
        (question_id, payload.chosen_index, int(correct)),
    )
    conn.commit()
    return AnswerOut(
        correct=correct, answer_index=row["answer_index"], explanation=row["explanation"]
    )


@router.delete("/sessions/{session_id}/quiz/attempts")
def reset_attempts(session_id: int, conn: sqlite3.Connection = Depends(with_conn)):
    conn.execute(
        """
        DELETE FROM quiz_attempts WHERE question_id IN
            (SELECT id FROM quiz_questions WHERE session_id = ?)
        """,
        (session_id,),
    )
    conn.commit()
    return {"reset": session_id}


def _questions(conn: sqlite3.Connection, session_id: int) -> list[QuestionOut]:
    rows = conn.execute(
        """
        SELECT q.id, q.prompt, q.choices, q.position,
               (SELECT COUNT(*) FROM quiz_attempts a WHERE a.question_id = q.id) AS attempts
        FROM quiz_questions q WHERE q.session_id = ? ORDER BY q.position, q.id
        """,
        (session_id,),
    ).fetchall()
    return [
        QuestionOut(
            id=r["id"],
            prompt=r["prompt"],
            choices=json.loads(r["choices"]),
            position=r["position"],
            answered=bool(r["attempts"]),
        )
        for r in rows
    ]
