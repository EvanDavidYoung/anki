"""The MCP surface is stage-only; these tests lock that in."""

import pytest


@pytest.fixture
def mcp_db(tmp_path, monkeypatch):
    """Point the MCP server at a throwaway DB and stub card extraction."""
    from conftest import VOCAB_JSON, StubLLM

    from anki_client.generator import ChineseCardGenerator
    from vocabapp import db
    from vocabapp.services import vocab

    db.set_db_path(tmp_path / "mcp.db")
    monkeypatch.setattr(
        vocab, "_get_generator", lambda: ChineseCardGenerator(llm=StubLLM(VOCAB_JSON))
    )
    db.init_schema()
    try:
        yield
    finally:
        db.set_db_path(None)


def test_the_server_exposes_no_tool_that_can_reach_anki(mcp_db):
    """An agent must not be able to approve, reject or export on its own."""
    from vocabapp import mcp_server

    names = {
        name
        for name in dir(mcp_server)
        if not name.startswith("_") and callable(getattr(mcp_server, name))
    }
    banned = {"approve", "reject", "export", "push", "answer", "delete"}
    offenders = {n for n in names if any(b in n.lower() for b in banned)}

    assert offenders == set(), f"stage-only server exposes {offenders}"


def test_created_cards_are_pending_and_absent_from_anki(mcp_db):
    from vocabapp.mcp_server import create_vocab_session

    result = create_vocab_session("台灣的夜市文化", "夜市")

    assert result["pending_count"] == 2
    assert result["approved_count"] == 0
    assert all(c["status"] == "pending" for c in result["cards"])
    assert all(c["anki_note_id"] is None for c in result["cards"])
    assert result["review_url"].endswith(f"?session={result['session_id']}")


def test_agent_supplied_cards_are_staged_not_exported(mcp_db):
    from vocabapp.mcp_server import get_vocab_session, stage_vocab_cards

    staged = stage_vocab_cards(
        cards=[
            {"traditional": "少子化", "pinyin": "shǎo zǐ huà", "meaning": "declining birthrate"},
            {"traditional": "衝擊"},
        ],
        title="Podcast ep. 42",
    )

    assert staged["card_count"] == 2
    assert staged["pending_count"] == 2

    reread = get_vocab_session(staged["session_id"])
    assert [c["traditional"] for c in reread["cards"]] == ["少子化", "衝擊"]
    # Sparse cards are allowed through so the human can fill them in.
    assert reread["cards"][1]["meaning"] == ""


def test_empty_input_is_rejected(mcp_db):
    from vocabapp.mcp_server import create_vocab_session, stage_vocab_cards

    with pytest.raises(ValueError, match="text is empty"):
        create_vocab_session("   ")
    with pytest.raises(ValueError, match="no cards supplied"):
        stage_vocab_cards(cards=[])


def test_unknown_session_raises_rather_than_returning_junk(mcp_db):
    from vocabapp.mcp_server import get_study_progress, get_vocab_session

    with pytest.raises(ValueError, match="no session with id"):
        get_vocab_session(999)
    with pytest.raises(ValueError, match="no session with id"):
        get_study_progress(999)


def test_progress_reflects_what_the_human_did(mcp_db):
    from vocabapp.db import connect
    from vocabapp.mcp_server import create_vocab_session, get_study_progress

    session = create_vocab_session("台灣的夜市文化", "夜市")
    card_id = session["cards"][0]["id"]

    # Stand in for the human approving one card in the web UI.
    with connect() as conn:
        conn.execute("UPDATE cards SET status = 'approved' WHERE id = ?", (card_id,))
        conn.commit()

    progress = get_study_progress(session["session_id"])
    assert progress["approved_count"] == 1
    assert progress["pending_count"] == 1
    assert progress["study"]["due_count"] == 1  # approved but never studied
    assert progress["reviews_waiting_to_push"] == 0
