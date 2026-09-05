"""MCP server exposing the vocab review queue to agents.

Deliberately stage-only: an agent can put candidate cards in front of the
human and read what happened, but approving, rejecting, exporting to Anki and
pushing review progress all stay in the web UI. That approval step is the
whole reason this app exists, so nothing here can bypass it.

Card creation for cards that should go straight to Anki already exists in
``anki_client.mcp_server``; this server is for the review-first path.
"""

import json
from datetime import UTC, datetime

from mcp.server.fastmcp import FastMCP

from anki_client.models import ChineseCard

from .config import get_app_settings
from .db import connect, init_schema
from .repo import get_cards, get_session, session_counts
from .services import quiz as quiz_service
from .services import vocab
from .services.quiz import QuizGenerationError

mcp = FastMCP("vocab-quiz")

init_schema()


def _review_url(session_id: int) -> str:
    return f"{get_app_settings().web_url}/?session={session_id}"


def _summary(conn, session_id: int) -> dict:
    session = get_session(conn, session_id)
    if not session:
        raise ValueError(f"no session with id {session_id}")
    counts = session_counts(conn, session_id)
    return {
        "session_id": session_id,
        "title": session["title"],
        "created_at": session["created_at"],
        **counts,
        "review_url": _review_url(session_id),
    }


def _card_rows(cards: list[ChineseCard], session_id: int) -> list[tuple]:
    return [
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
    ]


_INSERT_CARD = """
    INSERT INTO cards (session_id, traditional, pinyin, meaning, part_of_speech,
                       sentence_traditional, sentence_pinyin, sentence_meaning)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


@mcp.tool()
def create_vocab_session(text: str, title: str = "") -> dict:
    """Extract vocabulary from a passage of Chinese text and stage it for review.

    Cards are created as 'pending' — they do NOT go into Anki. Give the human
    the returned review_url so they can approve, edit or reject each card.

    Args:
        text: The Chinese passage to mine for vocabulary.
        title: Short label for the session, e.g. the article name.
    """
    text = text.strip()
    if not text:
        raise ValueError("text is empty")

    cards = vocab.extract(text, title)
    if not cards:
        raise ValueError("the model returned no vocabulary for this text")

    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (title, source_text) VALUES (?, ?)",
            (title.strip() or text[:40].replace("\n", " "), text),
        )
        session_id = cur.lastrowid
        conn.executemany(_INSERT_CARD, _card_rows(cards, session_id))
        conn.commit()
        return {
            **_summary(conn, session_id),
            "cards": get_cards(conn, session_id),
            "next_step": "Ask the human to review these at review_url. "
            "They must approve cards before anything reaches Anki.",
        }


@mcp.tool()
def stage_vocab_cards(cards: list[dict], title: str = "", source_text: str = "") -> dict:
    """Stage vocabulary cards you wrote yourself for human review.

    Use this when you have already selected the vocabulary (from a podcast,
    OCR'd image, transcript, or your own judgement) rather than having the
    text mined for you. Cards are created as 'pending' and do NOT go into Anki.

    Args:
        cards: Each needs 'traditional'; optionally pinyin, meaning,
            part_of_speech, sentence_traditional, sentence_pinyin,
            sentence_meaning. Traditional characters only.
        title: Short label for the session.
        source_text: The passage the cards came from, if you have it. Stored so
            quizzes can be generated against the original context.
    """
    if not cards:
        raise ValueError("no cards supplied")

    parsed = [
        ChineseCard(
            key="0",
            traditional=c["traditional"],
            pinyin=c.get("pinyin", ""),
            meaning=c.get("meaning", ""),
            part_of_speech=c.get("part_of_speech", ""),
            sentence_traditional=c.get("sentence_traditional", ""),
            sentence_pinyin=c.get("sentence_pinyin", ""),
            sentence_meaning=c.get("sentence_meaning", ""),
        )
        for c in cards
    ]

    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (title, source_text) VALUES (?, ?)",
            (title.strip() or f"{len(parsed)} staged cards", source_text),
        )
        session_id = cur.lastrowid
        conn.executemany(_INSERT_CARD, _card_rows(parsed, session_id))
        conn.commit()
        return {
            **_summary(conn, session_id),
            "cards": get_cards(conn, session_id),
            "next_step": "Ask the human to review these at review_url.",
        }


@mcp.tool()
def list_vocab_sessions(limit: int = 20) -> list[dict]:
    """List review sessions, newest first, with their approval counts."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.created_at,
                   COUNT(c.id) AS card_count,
                   COALESCE(SUM(c.status = 'approved'), 0) AS approved_count,
                   COALESCE(SUM(c.status = 'pending'), 0)  AS pending_count,
                   COALESCE(SUM(c.anki_note_id IS NOT NULL), 0) AS in_anki_count
            FROM sessions s LEFT JOIN cards c ON c.session_id = s.id
            GROUP BY s.id ORDER BY s.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [{**dict(r), "review_url": _review_url(r["id"])} for r in rows]


@mcp.tool()
def get_vocab_session(session_id: int) -> dict:
    """Read one session: its cards, each card's approval status, and whether
    it has reached Anki yet."""
    with connect() as conn:
        return {**_summary(conn, session_id), "cards": get_cards(conn, session_id)}


@mcp.tool()
def generate_quiz(session_id: int, n: int = 8) -> dict:
    """Write a multiple-choice quiz over a session's vocabulary.

    Uses approved cards when any exist, otherwise everything not rejected.
    Replaces any previous quiz for the session. Correct answers are returned
    here so you can discuss them; the web UI withholds them until the human
    answers.
    """
    with connect() as conn:
        session = get_session(conn, session_id)
        if not session:
            raise ValueError(f"no session with id {session_id}")

        cards = get_cards(conn, session_id, status="approved")
        if not cards:
            cards = [c for c in get_cards(conn, session_id) if c["status"] != "rejected"]
        if not cards:
            raise ValueError("no cards to quiz on")

        try:
            questions = quiz_service.generate(session["source_text"], cards, n)
        except QuizGenerationError as exc:
            raise ValueError(f"quiz generation failed: {exc}") from exc

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

    return {
        "session_id": session_id,
        "questions": questions,
        "quiz_url": _review_url(session_id),
    }


@mcp.tool()
def get_study_progress(session_id: int) -> dict:
    """How the human is doing on a session: cards due, quiz score so far, and
    how many in-app reviews are still waiting to be pushed to Anki."""
    now = datetime.now(UTC).isoformat()
    with connect() as conn:
        summary = _summary(conn, session_id)
        study = conn.execute(
            """
            SELECT COUNT(*) AS approved,
                   COALESCE(SUM(s.card_id IS NULL), 0) AS never_studied,
                   COALESCE(SUM(s.card_id IS NOT NULL AND s.due_at <= ?), 0) AS due_now
            FROM cards c LEFT JOIN card_srs s ON s.card_id = c.id
            WHERE c.session_id = ? AND c.status = 'approved'
            """,
            (now, session_id),
        ).fetchone()
        quiz = conn.execute(
            """
            SELECT COUNT(DISTINCT q.id) AS questions,
                   COUNT(DISTINCT a.question_id) AS answered,
                   COALESCE(SUM(a.correct), 0) AS correct
            FROM quiz_questions q LEFT JOIN quiz_attempts a ON a.question_id = q.id
            WHERE q.session_id = ?
            """,
            (session_id,),
        ).fetchone()
        unpushed = conn.execute(
            """
            SELECT COUNT(DISTINCT r.card_id) AS n FROM reviews r
            JOIN cards c ON c.id = r.card_id
            WHERE r.pushed_at IS NULL AND c.anki_note_id IS NOT NULL AND c.session_id = ?
            """,
            (session_id,),
        ).fetchone()

    return {
        **summary,
        "study": {**dict(study), "due_count": (study["due_now"] or 0) + (study["never_studied"] or 0)},
        "quiz": dict(quiz),
        "reviews_waiting_to_push": unpushed["n"] or 0,
    }


if __name__ == "__main__":
    mcp.run()
