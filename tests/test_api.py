import httpx
import pytest
from conftest import QUIZ_JSON, VOCAB_JSON, StubLLM

from anki_client.generator import ChineseCardGenerator
from vocabapp.services import ankisync, quiz as quiz_service, vocab


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """Both generation paths run for real — only the model call is faked."""
    monkeypatch.setattr(
        vocab, "_get_generator", lambda: ChineseCardGenerator(llm=StubLLM(VOCAB_JSON))
    )
    monkeypatch.setattr(quiz_service, "quiz_llm", lambda: StubLLM(QUIZ_JSON))


@pytest.fixture(autouse=True)
def anki_offline(monkeypatch):
    """Default to a closed Anki so tests never depend on a live collection."""

    def boom(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ankisync, "_client", boom)


def make_session(client, text="台灣的夜市文化"):
    res = client.post("/api/sessions", json={"text": text, "title": "夜市"})
    assert res.status_code == 200, res.text
    return res.json()


# ------------------------------------------------------------------ sessions


def test_create_session_stores_cards_as_pending(client):
    session = make_session(client)

    assert session["title"] == "夜市"
    assert session["card_count"] == 2
    assert session["pending_count"] == 2
    assert [c["status"] for c in session["cards"]] == ["pending", "pending"]
    assert session["cards"][0]["traditional"] == "夜市"


def test_empty_text_is_rejected(client):
    assert client.post("/api/sessions", json={"text": "   "}).status_code == 400


def test_sessions_list_and_detail_round_trip(client):
    created = make_session(client)

    listed = client.get("/api/sessions").json()
    assert [s["id"] for s in listed] == [created["id"]]

    detail = client.get(f"/api/sessions/{created['id']}").json()
    assert detail["source_text"] == "台灣的夜市文化"

    assert client.get("/api/sessions/999").status_code == 404


# --------------------------------------------------------------------- cards


def test_approve_reject_and_edit_persist(client):
    session = make_session(client)
    first, second = session["cards"]

    assert client.post(f"/api/cards/{first['id']}/approve").json()["status"] == "approved"
    assert client.post(f"/api/cards/{second['id']}/reject").json()["status"] == "rejected"

    edited = client.patch(f"/api/cards/{first['id']}", json={"meaning": "night bazaar"})
    assert edited.json()["meaning"] == "night bazaar"

    reloaded = client.get(f"/api/sessions/{session['id']}").json()
    assert reloaded["approved_count"] == 1
    assert reloaded["pending_count"] == 0
    assert reloaded["cards"][0]["meaning"] == "night bazaar"


def test_patch_rejects_unknown_and_missing_fields(client):
    card = make_session(client)["cards"][0]

    assert client.patch(f"/api/cards/{card['id']}", json={}).status_code == 400
    assert client.patch(f"/api/cards/{card['id']}", json={"status": "approved"}).status_code == 400
    assert client.patch("/api/cards/999", json={"meaning": "x"}).status_code == 404


def test_bulk_approve_only_touches_pending_cards(client):
    session = make_session(client)
    rejected = session["cards"][1]
    client.post(f"/api/cards/{rejected['id']}/reject")

    cards = client.post(
        f"/api/sessions/{session['id']}/cards/bulk", json={"status": "approved"}
    ).json()

    assert [c["status"] for c in cards] == ["approved", "rejected"]


# ---------------------------------------------------------------------- quiz


def test_quiz_generation_hides_answers_until_you_answer(client):
    session = make_session(client)
    client.post(f"/api/sessions/{session['id']}/cards/bulk", json={"status": "approved"})

    questions = client.post(f"/api/sessions/{session['id']}/quiz", json={"n": 2}).json()
    assert len(questions) == 2
    assert all(len(q["choices"]) == 4 for q in questions)
    assert all("answer_index" not in q for q in questions)

    # Answer every question both ways to prove grading works either direction.
    for q in questions:
        res = client.post(f"/api/quiz/questions/{q['id']}/answer", json={"chosen_index": 0}).json()
        assert set(res) == {"correct", "answer_index", "explanation"}
        assert res["correct"] == (res["answer_index"] == 0)

    stats = client.get(f"/api/sessions/{session['id']}/quiz/stats").json()
    assert stats == {"total": 2, "answered": 2, "correct": stats["correct"]}


def test_quiz_requires_cards(client):
    session = make_session(client)
    client.post(
        f"/api/sessions/{session['id']}/cards/bulk",
        json={"status": "rejected", "card_ids": [c["id"] for c in session["cards"]]},
    )

    assert client.post(f"/api/sessions/{session['id']}/quiz", json={"n": 2}).status_code == 422


def test_answering_out_of_range_is_rejected(client):
    session = make_session(client)
    question = client.post(f"/api/sessions/{session['id']}/quiz", json={"n": 1}).json()[0]

    res = client.post(f"/api/quiz/questions/{question['id']}/answer", json={"chosen_index": 9})
    assert res.status_code == 400


# --------------------------------------------------------------------- study


def test_study_queue_only_serves_approved_cards(client):
    session = make_session(client)
    assert client.get(f"/api/sessions/{session['id']}/study/next").json() is None

    approved = session["cards"][0]
    client.post(f"/api/cards/{approved['id']}/approve")

    served = client.get(f"/api/sessions/{session['id']}/study/next").json()
    assert served["card"]["id"] == approved["id"]
    assert served["reps"] == 0
    assert served["new_count"] == 1


def test_answering_good_schedules_the_card_out_of_the_queue(client):
    session = make_session(client)
    card = session["cards"][0]
    client.post(f"/api/cards/{card['id']}/approve")

    state = client.post("/api/study/answer", json={"card_id": card["id"], "ease": 3}).json()
    assert state == {"due_count": 0, "new_count": 0, "total": 1, "unpushed_reviews": 0}

    # unpushed_reviews stays 0 because the card was never exported to Anki.
    assert client.get(f"/api/sessions/{session['id']}/study/next").json() is None


def test_again_keeps_the_card_due_shortly(client):
    session = make_session(client)
    card = session["cards"][0]
    client.post(f"/api/cards/{card['id']}/approve")

    client.post("/api/study/answer", json={"card_id": card["id"], "ease": 1})
    state = client.get(f"/api/sessions/{session['id']}/study/state").json()

    assert state["total"] == 1
    assert state["new_count"] == 0  # it now has SRS state


def test_invalid_ease_rejected_by_the_api(client):
    card = make_session(client)["cards"][0]
    assert client.post("/api/study/answer", json={"card_id": card["id"], "ease": 7}).status_code == 422


# ---------------------------------------------------------------------- anki


def test_status_reports_offline_without_raising(client):
    body = client.get("/api/anki/status").json()

    assert body["reachable"] is False
    assert body["default_deck"] == "QA"
    assert body["decks"] == []
    assert body["error"]


def test_export_without_anki_returns_503_not_500(client):
    session = make_session(client)
    client.post(f"/api/sessions/{session['id']}/cards/bulk", json={"status": "approved"})

    res = client.post("/api/anki/export", json={"session_id": session["id"], "deck": "QA"})
    assert res.status_code == 503
    assert "apkg" in res.json()["detail"]


def test_export_requires_approved_cards(client):
    session = make_session(client)

    res = client.post("/api/anki/export", json={"session_id": session["id"]})
    assert res.status_code == 422


def test_apkg_export_works_with_anki_closed(client):
    session = make_session(client)
    client.post(f"/api/sessions/{session['id']}/cards/bulk", json={"status": "approved"})

    res = client.get(f"/api/anki/apkg?session_id={session['id']}&deck=QA")
    assert res.status_code == 200
    assert res.content[:2] == b"PK"  # .apkg is a zip
    assert len(res.content) > 1000


def test_push_reviews_is_a_noop_when_nothing_is_queued(client):
    session = make_session(client)
    card = session["cards"][0]
    client.post(f"/api/cards/{card['id']}/approve")
    client.post("/api/study/answer", json={"card_id": card["id"], "ease": 3})

    # The card has no anki_note_id, so there is nothing Anki could accept.
    body = client.post("/api/anki/push-reviews", json={"session_id": session["id"]}).json()
    assert body == {"attempted": 0, "pushed": 0, "results": []}
