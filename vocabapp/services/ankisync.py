"""Everything that talks to Anki: live push, .apkg export, review push-back."""


import genanki
import httpx

from anki_client.client import NOTE_TYPE, AnkiClient, AnkiConnectError
from anki_client.models import AddResult, ChineseCard
from anki_client.tts import random_voice

from ..config import get_app_settings

FIELD_NAMES = [
    "Key",
    "Traditional",
    "Pinyin",
    "Meaning",
    "PartOfSpeech",
    "SentenceTraditional",
    "SentencePinyin",
    "SentenceMeaning",
    "SentenceAudio",
    "WordAudio",
]

# Stable IDs so re-exporting the same deck doesn't create new note types /
# decks on every import. genanki requires these to be fixed constants.
APKG_MODEL_ID = 1_607_392_319
APKG_DECK_ID = 2_059_400_110

_FALLBACK_FRONT = "<div class=hanzi>{{Traditional}}</div>{{WordAudio}}"
_FALLBACK_BACK = (
    "{{FrontSide}}<hr id=answer>"
    "<div class=pinyin>{{Pinyin}}</div>"
    "<div class=meaning>{{Meaning}} <span class=pos>{{PartOfSpeech}}</span></div>"
    "<div class=sentence>{{SentenceTraditional}}</div>"
    "<div class=sentence-pinyin>{{SentencePinyin}}</div>"
    "<div class=sentence-meaning>{{SentenceMeaning}}</div>"
    "{{SentenceAudio}}"
)
_FALLBACK_CSS = """\
.card { font-family: "Noto Sans TC", "PingFang TC", sans-serif; text-align: center;
        font-size: 20px; color: #111; background: #fff; }
.hanzi { font-size: 56px; margin-bottom: 12px; }
.pinyin { color: #2563eb; font-size: 24px; }
.meaning { margin: 10px 0; }
.pos { color: #888; font-size: 15px; }
.sentence { font-size: 26px; margin-top: 18px; }
.sentence-pinyin { color: #2563eb; font-size: 17px; }
.sentence-meaning { color: #555; font-size: 17px; }
"""


def _client() -> AnkiClient:
    return AnkiClient(url=get_app_settings().anki_url)


# ---------------------------------------------------------------- status


def status() -> dict:
    """Never raises — a closed Anki is a normal state for this app."""
    cfg = get_app_settings()
    try:
        decks = sorted(_client().deck_names())
    except (httpx.HTTPError, AnkiConnectError, OSError) as exc:
        return {
            "reachable": False,
            "decks": [],
            "default_deck": cfg.default_deck,
            "error": str(exc),
        }
    return {"reachable": True, "decks": decks, "default_deck": cfg.default_deck, "error": ""}


# ------------------------------------------------------------ live export


def _row_to_card(row: dict, key: str) -> ChineseCard:
    return ChineseCard(
        key=key,
        traditional=row["traditional"],
        pinyin=row["pinyin"],
        meaning=row["meaning"],
        part_of_speech=row["part_of_speech"],
        sentence_traditional=row["sentence_traditional"],
        sentence_pinyin=row["sentence_pinyin"],
        sentence_meaning=row["sentence_meaning"],
        tags=["source:webapp"],
    )


def export_cards(rows: list[dict], deck: str, with_audio: bool = False) -> dict:
    """Push approved cards to Anki. Returns AddResult fields + the row->note map.

    Called from a sync endpoint (threadpool) because AnkiClient, the TTS helper
    and the LLM client are all blocking.
    """
    anki = _client()
    anki.create_deck(deck)

    next_key = anki.next_key()
    cards = [_row_to_card(row, str(next_key + i)) for i, row in enumerate(rows)]

    # Keep row ids aligned with cards through de-duplication.
    kept = anki.filter_duplicates(cards, deck)
    kept_traditionals = {c.traditional for c in kept}
    paired = [(row, card) for row, card in zip(rows, cards) if card.traditional in kept_traditionals]
    duplicates = len(cards) - len(paired)
    if not paired:
        return {"added": 0, "duplicates": duplicates, "errors": 0, "note_ids": [], "row_notes": {}}

    kept_cards = [card for _, card in paired]
    if with_audio:
        _attach_audio(kept_cards, anki)

    result: AddResult = anki.add_notes_batch(kept_cards, deck)
    row_notes = {
        row["id"]: note_id
        for (row, _), note_id in zip(paired, result.note_ids)
        if note_id
    }
    return {
        "added": result.added,
        "duplicates": result.duplicates + duplicates,
        "errors": result.errors,
        "note_ids": [n for n in result.note_ids if n],
        "row_notes": row_notes,
    }


def _attach_audio(cards: list[ChineseCard], anki: AnkiClient) -> None:
    # Imported lazily: generate_and_store calls asyncio.run internally, so it
    # must never be imported into an async context by accident.
    from anki_client.tts import generate_and_store

    texts_voices: list[tuple[str, str]] = []
    for card in cards:
        voice = random_voice()  # one voice per card, both clips
        texts_voices.append((card.traditional, voice))
        texts_voices.append((card.sentence_traditional, voice))
    tags = generate_and_store(texts_voices, anki)
    for i, card in enumerate(cards):
        card.word_audio = tags[2 * i]
        card.sentence_audio = tags[2 * i + 1]


# ------------------------------------------------------------ apkg export


def _apkg_model() -> genanki.Model:
    """Mirror the live note type's templates/CSS when Anki is reachable.

    The model *id* still can't match the collection's, so importing this .apkg
    into a collection that already has "Chinese Learning Model" produces a
    second, suffixed note type. Live AnkiConnect export is the lossless path.
    """
    front, back, css = _FALLBACK_FRONT, _FALLBACK_BACK, _FALLBACK_CSS
    try:
        anki = _client()
        templates = anki.note_type_templates(NOTE_TYPE)
        if templates:
            first = next(iter(templates.values()))
            front = first.get("Front") or front
            back = first.get("Back") or back
        css = anki.note_type_styling(NOTE_TYPE).get("css") or css
    except (httpx.HTTPError, AnkiConnectError, OSError, StopIteration):
        pass  # Anki closed — fall back to our own templates.

    return genanki.Model(
        APKG_MODEL_ID,
        NOTE_TYPE,
        fields=[{"name": name} for name in FIELD_NAMES],
        templates=[{"name": "Recognition", "qfmt": front, "afmt": back}],
        css=css,
    )


def build_apkg(rows: list[dict], deck: str, out_path: str) -> int:
    """Write a .apkg of the given card rows. Returns the note count."""
    model = _apkg_model()
    package_deck = genanki.Deck(APKG_DECK_ID, deck)
    for i, row in enumerate(rows):
        card = _row_to_card(row, str(i + 1))
        package_deck.add_note(
            genanki.Note(
                model=model,
                fields=[
                    card.key,
                    card.traditional,
                    card.pinyin,
                    card.meaning,
                    card.part_of_speech,
                    card.sentence_traditional,
                    card.sentence_pinyin,
                    card.sentence_meaning,
                    card.sentence_audio,
                    card.word_audio,
                ],
                tags=["source:webapp"],
                guid=genanki.guid_for(card.traditional, deck),
            )
        )
    genanki.Package(package_deck).write_to_file(out_path)
    return len(rows)


# ----------------------------------------------------------- review push


def push_reviews(pending: list[dict]) -> list[dict]:
    """Answer Anki cards for the given reviews.

    ``pending`` rows need ``card_id``, ``traditional``, ``anki_note_id``, ``ease``.
    AnkiConnect only accepts an answer for a card that is currently due, so the
    per-card outcome is reported rather than assumed.
    """
    if not pending:
        return []

    anki = _client()
    note_ids = [row["anki_note_id"] for row in pending]
    query = " OR ".join(f"nid:{nid}" for nid in note_ids)
    due_now = set(anki.find_cards(f"({query}) (is:due OR is:new OR is:learn)"))

    answers: list[dict] = []
    plan: list[dict] = []
    for row in pending:
        card_ids = anki.find_cards(f"nid:{row['anki_note_id']}")
        answerable = [cid for cid in card_ids if cid in due_now]
        if not answerable:
            plan.append({**row, "pushed": False, "reason": "not due in Anki"})
            continue
        for cid in answerable:
            answers.append({"cardId": cid, "ease": row["ease"]})
        plan.append({**row, "pushed": None, "reason": "", "_count": len(answerable)})

    if answers:
        outcomes = anki.answer_cards(answers)
    else:
        outcomes = []

    results: list[dict] = []
    cursor = 0
    for entry in plan:
        if entry["pushed"] is False:
            results.append(entry)
            continue
        count = entry.pop("_count")
        chunk = outcomes[cursor : cursor + count]
        cursor += count
        ok = bool(chunk) and all(chunk)
        results.append(
            {**entry, "pushed": ok, "reason": "" if ok else "Anki rejected the answer"}
        )
    return results
