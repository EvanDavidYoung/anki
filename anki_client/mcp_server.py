from mcp.server.fastmcp import FastMCP

from .client import AnkiClient
from .config import get_settings
from .generator import ChineseCardGenerator
from .profile import LearnerProfile
from .staging import StagingService
from .stats import StatsClient

mcp = FastMCP("anki")

_anki = AnkiClient()
_stats = StatsClient(client=_anki)
_generator = ChineseCardGenerator(anki=_anki)
_staging = StagingService(client=_anki)
_profile = LearnerProfile(client=_anki)
_cfg = get_settings()


def _generate_and_add(item, deck: str) -> dict:
    """Generate cards for one content item, attach audio, and add them to a deck."""
    from .models import ChineseCard
    from .tts import generate_and_store, random_voice

    cards: list[ChineseCard] = _generator.generate(item)  # type: ignore[assignment]
    cards = _anki.filter_duplicates(cards, deck)
    if not cards:
        return {"added": 0, "duplicates": 0, "errors": 0, "note_ids": []}

    texts_voices = []
    for card in cards:
        voice = random_voice()
        texts_voices.append((card.traditional, voice))
        texts_voices.append((card.sentence_traditional, voice))
    audio_tags = generate_and_store(texts_voices, _anki)
    for i, card in enumerate(cards):
        card.word_audio = audio_tags[i * 2]
        card.sentence_audio = audio_tags[i * 2 + 1]

    return _anki.add_notes_batch(cards, deck).model_dump()


# ---------------------------------------------------------------------------
# Deck / format discovery  (call these before generating cards)
# ---------------------------------------------------------------------------


@mcp.tool()
def list_decks_with_note_types() -> list[dict]:
    """List every deck and the note type it uses. Call this before generating cards
    so the user can pick which deck's format to use."""
    decks = _anki.deck_names()
    return [
        {"deck": deck, "note_type": _anki.deck_note_type(deck) or "(empty)"}
        for deck in sorted(decks)
    ]


@mcp.tool()
def get_note_type_fields(note_type: str) -> list[str]:
    """Return the ordered field names for a given note type."""
    return _anki.note_type_fields(note_type)


@mcp.tool()
def create_deck(deck: str) -> dict:
    """Create a deck. No-op if it already exists. Use '::' for subdecks."""
    _anki.create_deck(deck)
    return {"created": deck}


# ---------------------------------------------------------------------------
# Card creation
# ---------------------------------------------------------------------------


@mcp.tool()
def add_card(
    traditional: str,
    pinyin: str,
    meaning: str,
    part_of_speech: str,
    sentence_traditional: str,
    sentence_pinyin: str,
    sentence_meaning: str,
    deck: str = "QA",
) -> dict:
    """Add a single Chinese flashcard to Anki. Defaults to the QA deck."""
    from .models import ChineseCard
    from .tts import generate_and_store, random_voice

    target_deck = deck
    key = str(_anki.next_key())
    voice = random_voice()
    word_audio, sentence_audio = generate_and_store(
        [(traditional, voice), (sentence_traditional, voice)], _anki
    )
    card = ChineseCard(
        key=key,
        traditional=traditional,
        pinyin=pinyin,
        meaning=meaning,
        part_of_speech=part_of_speech,
        sentence_traditional=sentence_traditional,
        sentence_pinyin=sentence_pinyin,
        sentence_meaning=sentence_meaning,
        word_audio=word_audio,
        sentence_audio=sentence_audio,
    )
    note_id = _anki.add_note(card, target_deck)
    return {"note_id": note_id, "added": note_id is not None}


@mcp.tool()
def add_cards(cards: list[dict], deck: str = "QA") -> dict:
    """Add multiple Chinese flashcards to Anki in a single batch. Defaults to the QA deck.
    Each card must have: traditional, pinyin, meaning, part_of_speech, sentence_traditional,
    sentence_pinyin, sentence_meaning. Optional: sentence_audio, word_audio, tags."""
    from .models import ChineseCard
    from .tts import generate_and_store, random_voice

    target_deck = deck
    next_key = _anki.next_key()

    voices = [random_voice() for _ in cards]
    texts_voices = []
    for c, voice in zip(cards, voices):
        texts_voices.append((c["traditional"], voice))
        texts_voices.append((c["sentence_traditional"], voice))
    audio_tags = generate_and_store(texts_voices, _anki)
    word_tags = audio_tags[0::2]
    sentence_tags = audio_tags[1::2]

    card_objects = [
        ChineseCard(
            key=str(next_key + i),
            traditional=c["traditional"],
            pinyin=c["pinyin"],
            meaning=c["meaning"],
            part_of_speech=c["part_of_speech"],
            sentence_traditional=c["sentence_traditional"],
            sentence_pinyin=c["sentence_pinyin"],
            sentence_meaning=c["sentence_meaning"],
            word_audio=word_tags[i],
            sentence_audio=sentence_tags[i],
            tags=c.get("tags", []),
        )
        for i, c in enumerate(cards)
    ]
    result = _anki.add_notes_batch(card_objects, target_deck)
    return result.model_dump()


@mcp.tool()
def generate_cards_from_text(text: str, deck: str = "QA") -> dict:
    """Generate Chinese flashcards from a text passage and add them to Anki.
    Defaults to the QA deck. Call list_decks_with_note_types first so the user
    can confirm which deck's format to use."""
    from .sources.base import ContentItem

    item = ContentItem(raw_text=text, title="mcp-input", suggested_deck=deck)
    return _generate_and_add(item, deck)


@mcp.tool()
def ingest_local_files(deck: str = "QA") -> dict:
    """Generate cards from every .md/.txt file in the configured input directory,
    add them to the deck (defaults to QA), and archive the files to
    input/processed/. Unlike ingest_chatlogs, these are added directly rather
    than staged for review."""
    from .sources.local_files import LocalFileSource

    items = LocalFileSource().fetch()
    return {
        "files": len(items),
        "results": [
            {"title": item.title, **_generate_and_add(item, deck)} for item in items
        ],
    }


# ---------------------------------------------------------------------------
# Chat-log ingestion (staging + review)
# ---------------------------------------------------------------------------


@mcp.tool()
def ingest_chatlogs(card_type: str = "auto", batch_size: int = 0) -> dict:
    """Ingest Slack-export chat logs end to end: parse files into the message
    store (and archive them to processed/), then generate vocab cards by batching
    text messages across files (batch_size messages per LLM request; 0 = the
    configured default). Cards are staged suspended, tagged status:pending, with
    no audio, skipping words you already know. Returns the sync summary and the
    staged candidates per batch for review before approving."""
    return _staging.ingest(card_type=card_type, batch_size=batch_size or None)


@mcp.tool()
def sync_messages() -> dict:
    """Parse chat-log files into the message store and archive them to
    processed/, without generating any cards. Idempotent (dedupes on re-parse)."""
    return _staging.sync_sources()


@mcp.tool()
def generate_pending_cards(card_type: str = "auto", batch_size: int = 0) -> list[dict]:
    """Generate cards for all new text messages already in the message store,
    batching batch_size messages per LLM request (0 = configured default).
    Returns the staged candidates per batch."""
    return _staging.generate_pending(card_type=card_type, batch_size=batch_size or None)


@mcp.tool()
def message_store_stats() -> list[dict]:
    """Counts of stored chat messages grouped by (kind, state) — e.g. how many
    text messages are still pending, how many image messages await the vision
    path."""
    return _staging._store.stats()


@mcp.tool()
def list_pending_messages(limit: int = 0) -> list[dict]:
    """List the actual chat messages still awaiting card generation, oldest
    first (0 = no limit). message_store_stats gives only counts; this shows the
    text itself."""
    messages = _staging._store.pending_text(limit or None)
    return [m.model_dump() for m in messages]


@mcp.tool()
def list_pending_cards() -> list[dict]:
    """List all cards currently staged for review (tag status:pending)."""
    return _staging.list_pending()


@mcp.tool()
def approve_cards(note_ids: list[int], target_deck: str = "") -> dict:
    """Approve staged cards: generate audio, move them to the target deck,
    unsuspend, and clear the pending tag. Defaults to the configured target deck."""
    return _staging.approve(note_ids, target_deck or None)


@mcp.tool()
def approve_batch(batch_id: str, target_deck: str = "") -> dict:
    """Approve every still-pending card from one generation batch by its
    batch_id (as returned by ingest_chatlogs / generate_pending_cards), without
    listing each note ID."""
    return _staging.approve_batch(batch_id, target_deck or None)


@mcp.tool()
def reject_cards(note_ids: list[int]) -> dict:
    """Reject staged cards: permanently delete them from the staging deck."""
    return _staging.reject(note_ids)


@mcp.tool()
def get_learner_profile() -> dict:
    """Return the learner's estimated HSK level, per-band coverage, and known/
    mature word counts, derived from the Anki study decks."""
    return _profile.estimate_level()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@mcp.tool()
def get_deck_stats(deck_names: list[str] = []) -> list[dict]:
    """Get new/learning/due counts for the specified decks. Defaults to the
    configured study decks when none are given."""
    return [s.model_dump() for s in _stats.get_deck_stats(deck_names or _cfg.study_decks)]


@mcp.tool()
def get_retention_rate(deck: str, days: int = 30) -> dict:
    """Get the percentage of reviews answered correctly in the last N days."""
    return {"deck": deck, "days": days, "retention_pct": _stats.get_retention_rate(deck, days)}


@mcp.tool()
def get_hard_cards(deck: str, min_lapses: int = 3, limit: int = 20) -> list[dict]:
    """Return cards with the highest lapse counts — your hardest cards."""
    return _stats.get_hard_cards(deck, min_lapses=min_lapses, limit=limit)


@mcp.tool()
def get_review_forecast(deck: str) -> dict:
    """Return counts of cards due today, this week, and new cards available."""
    return _stats.get_review_forecast(deck)


@mcp.tool()
def get_total_study_hours(deck: str) -> dict:
    """Total time spent reviewing every card in the deck, in hours."""
    return {"deck": deck, "hours": round(_stats.get_total_study_hours(deck), 2)}


@mcp.tool()
def get_new_cards_added(deck: str, days: int = 7) -> dict:
    """How many cards were added to the deck in the last N days."""
    return {"deck": deck, "days": days, "added": _stats.get_new_cards_added(deck, days)}


@mcp.tool()
def get_confused_pairs(
    deck: str,
    session_gap_minutes: int = 30,
    min_co_failures: int = 2,
    limit: int = 20,
) -> list[dict]:
    """Find pairs of cards repeatedly failed in the same study session — strong
    candidates for words you are mixing up with each other."""
    return _stats.get_confused_pairs(
        deck,
        session_gap_minutes=session_gap_minutes,
        min_co_failures=min_co_failures,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@mcp.tool()
def search_cards(query: str) -> list[dict]:
    """Search notes using Anki search syntax (e.g. 'deck:Chinese tag:hard')."""
    note_ids = _anki.find_notes(query)
    if not note_ids:
        return []
    return _anki.get_notes_info(note_ids)


@mcp.tool()
def update_note_fields(note_id: int, fields: dict) -> dict:
    """Update one or more fields on a note by ID. If you change Traditional or
    SentenceTraditional, call regenerate_audio afterwards — the existing audio
    still plays the old text."""
    _anki.update_note_fields(note_id, fields)
    return {"updated": True, "note_id": note_id}


@mcp.tool()
def regenerate_audio(note_ids: list[int]) -> dict:
    """Re-synthesize WordAudio and SentenceAudio from the notes' current text.
    Use after editing Traditional or SentenceTraditional, or to fill in cards
    reported by find_cards_missing_audio."""
    return _staging.regenerate_audio(note_ids)


@mcp.tool()
def find_cards_missing_audio(deck: str) -> list[dict]:
    """List notes in the deck whose WordAudio or SentenceAudio field is blank.
    Feed the note IDs to regenerate_audio to fix them."""
    return _anki.notes_missing_audio(deck)


@mcp.tool()
def move_notes(note_ids: list[int], deck: str) -> dict:
    """Move all cards belonging to the given notes into another deck."""
    card_ids = _anki._notes_to_cards(note_ids)
    _anki.change_deck(card_ids, deck)
    return {"moved": len(note_ids), "cards": len(card_ids), "deck": deck}


@mcp.tool()
def delete_notes(note_ids: list[int]) -> dict:
    """Permanently delete notes and all their cards. This cannot be undone from
    here — confirm the note IDs with search_cards first."""
    _anki.delete_notes(note_ids)
    return {"deleted": len(note_ids)}


@mcp.tool()
def add_tags(note_ids: list[int], tags: list[str]) -> dict:
    """Add tags to a list of notes."""
    _anki.add_tags(note_ids, tags)
    return {"updated": len(note_ids)}


@mcp.tool()
def remove_tags(note_ids: list[int], tags: list[str]) -> dict:
    """Remove tags from a list of notes."""
    _anki.remove_tags(note_ids, tags)
    return {"updated": len(note_ids)}


@mcp.tool()
def suspend(note_ids: list[int]) -> dict:
    """Suspend all cards belonging to the given notes."""
    _anki.suspend(note_ids)
    return {"suspended": len(note_ids)}


@mcp.tool()
def unsuspend(note_ids: list[int]) -> dict:
    """Unsuspend all cards belonging to the given notes."""
    _anki.unsuspend(note_ids)
    return {"unsuspended": len(note_ids)}


if __name__ == "__main__":
    mcp.run()
