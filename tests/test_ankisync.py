"""Covers the push-back path, where AnkiConnect can partially refuse."""

import pytest

from vocabapp.services import ankisync


class FakeAnki:
    """Minimal AnkiConnect double: note 1 has a due card, note 2 doesn't."""

    def __init__(self, due_cards=(11,), note_cards=None):
        self.due_cards = list(due_cards)
        self.note_cards = note_cards or {1: [11], 2: [22]}
        self.answered = []

    def find_cards(self, query):
        if "is:due" in query:
            return list(self.due_cards)
        nid = int(query.split("nid:")[1].split()[0])
        return self.note_cards.get(nid, [])

    def answer_cards(self, answers):
        self.answered = answers
        return [a["cardId"] in self.due_cards for a in answers]


PENDING = [
    {"card_id": 1, "traditional": "夜市", "anki_note_id": 1, "ease": 3},
    {"card_id": 2, "traditional": "攝販", "anki_note_id": 2, "ease": 1},
]


@pytest.fixture
def fake(monkeypatch):
    anki = FakeAnki()
    monkeypatch.setattr(ankisync, "_client", lambda: anki)
    return anki


def test_cards_that_are_not_due_are_reported_rather_than_assumed_pushed(fake):
    results = ankisync.push_reviews(PENDING)

    assert [r["pushed"] for r in results] == [True, False]
    assert results[1]["reason"] == "not due in Anki"
    # The undue card is never sent, so Anki can't silently mis-schedule it.
    assert fake.answered == [{"cardId": 11, "ease": 3}]


def test_ease_is_carried_through_per_card(monkeypatch):
    anki = FakeAnki(due_cards=(11, 22))
    monkeypatch.setattr(ankisync, "_client", lambda: anki)

    results = ankisync.push_reviews(PENDING)

    assert all(r["pushed"] for r in results)
    assert anki.answered == [{"cardId": 11, "ease": 3}, {"cardId": 22, "ease": 1}]


def test_a_note_with_several_cards_only_counts_as_pushed_if_all_succeed(monkeypatch):
    # Note 1 makes two cards; only one of them is due.
    anki = FakeAnki(due_cards=(11, 12), note_cards={1: [11, 12]})
    monkeypatch.setattr(ankisync, "_client", lambda: anki)
    anki.due_cards = [11, 12]

    results = ankisync.push_reviews(PENDING[:1])
    assert results[0]["pushed"] is True
    assert anki.answered == [{"cardId": 11, "ease": 3}, {"cardId": 12, "ease": 3}]


def test_empty_input_short_circuits(fake):
    assert ankisync.push_reviews([]) == []
    assert fake.answered == []
