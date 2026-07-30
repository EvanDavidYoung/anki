import base64
import httpx

from .models import AddResult, ChineseCard

ANKI_URL = "http://localhost:8765"
NOTE_TYPE = "Chinese Learning Model"


class AnkiConnectError(Exception):
    pass


class AnkiClient:
    def __init__(self, url: str = ANKI_URL):
        self._url = url

    def _request(self, action: str, **params) -> object:
        payload = {"action": action, "version": 6, "params": params}
        resp = httpx.post(self._url, json=payload, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            raise AnkiConnectError(f"{action}: {body['error']}")
        return body["result"]

    # ------------------------------------------------------------------
    # Deck / note discovery
    # ------------------------------------------------------------------

    def deck_names(self) -> list[str]:
        return self._request("deckNames")

    def create_deck(self, deck: str) -> None:
        """Create a deck (no-op if it already exists)."""
        self._request("createDeck", deck=deck)

    def deck_note_type(self, deck: str) -> str | None:
        """Return the note type used by the first note found in a deck, or None if empty."""
        note_ids = self.find_notes(f'deck:"{deck}"')
        if not note_ids:
            return None
        notes = self.get_notes_info(note_ids[:1])
        return notes[0].get("modelName") if notes else None

    def note_type_fields(self, note_type: str) -> list[str]:
        """Return the ordered field names for a note type."""
        return self._request("modelFieldNames", modelName=note_type)

    def find_notes(self, query: str) -> list[int]:
        return self._request("findNotes", query=query)

    def get_notes_info(self, note_ids: list[int]) -> list[dict]:
        return self._request("notesInfo", notes=note_ids)

    def find_cards(self, query: str) -> list[int]:
        return self._request("findCards", query=query)

    # ------------------------------------------------------------------
    # Key auto-generation
    # ------------------------------------------------------------------

    def next_key(self) -> int:
        """Return max Key value across all notes that have a Key field, + 1.
        Searches all note types so keys are globally unique."""
        note_ids = self.find_notes("Key:_*")
        if not note_ids:
            return 1
        notes = self.get_notes_info(note_ids)
        keys = []
        for note in notes:
            raw = note.get("fields", {}).get("Key", {}).get("value", "")
            try:
                keys.append(int(raw))
            except (ValueError, TypeError):
                pass
        return max(keys) + 1 if keys else 1

    # ------------------------------------------------------------------
    # Adding notes
    # ------------------------------------------------------------------

    def _card_to_note_params(self, card: ChineseCard, deck: str) -> dict:
        return {
            "deckName": deck,
            "modelName": NOTE_TYPE,
            "fields": {
                "Key": card.key,
                "Traditional": card.traditional,
                "Pinyin": card.pinyin,
                "Meaning": card.meaning,
                "PartOfSpeech": card.part_of_speech,
                "SentenceTraditional": card.sentence_traditional,
                "SentencePinyin": card.sentence_pinyin,
                "SentenceMeaning": card.sentence_meaning,
                "SentenceAudio": card.sentence_audio,
                "WordAudio": card.word_audio,
            },
            "tags": card.tags,
            "options": {
                "allowDuplicate": False,
                "duplicateScope": "deck",
            },
        }

    def add_note(self, card: ChineseCard, deck: str) -> int | None:
        """Add a single note. Returns note ID, or None if duplicate."""
        try:
            return self._request("addNote", note=self._card_to_note_params(card, deck))
        except AnkiConnectError as e:
            if "duplicate" in str(e).lower():
                return None
            raise

    def add_notes_batch(self, cards: list[ChineseCard], deck: str) -> AddResult:
        """Add notes in one AnkiConnect call. Handles per-note errors gracefully."""
        notes = [self._card_to_note_params(c, deck) for c in cards]
        results: list[int | None] = self._request("addNotes", notes=notes)

        added, duplicates, errors, note_ids = 0, 0, 0, []
        for note_id, card in zip(results, cards):
            if note_id is None:
                # AnkiConnect returns null for duplicates and some errors;
                # treat as duplicate since allowDuplicate=False is set.
                duplicates += 1
            elif isinstance(note_id, int) and note_id > 0:
                added += 1
                note_ids.append(note_id)
            else:
                errors += 1

        return AddResult(added=added, duplicates=duplicates, errors=errors, note_ids=note_ids)

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def store_media_file(self, filename: str, data: bytes) -> None:
        self._request("storeMediaFile", filename=filename, data=base64.b64encode(data).decode())

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        self._request("updateNoteFields", note={"id": note_id, "fields": fields})

    def add_tags(self, note_ids: list[int], tags: list[str]) -> None:
        self._request("addTags", notes=note_ids, tags=" ".join(tags))

    def remove_tags(self, note_ids: list[int], tags: list[str]) -> None:
        self._request("removeTags", notes=note_ids, tags=" ".join(tags))

    # ------------------------------------------------------------------
    # Suspend / unsuspend
    # ------------------------------------------------------------------

    def suspend(self, note_ids: list[int]) -> None:
        """Suspend all cards belonging to the given notes."""
        card_ids = self._notes_to_cards(note_ids)
        if card_ids:
            self._request("suspend", cards=card_ids)

    def unsuspend(self, note_ids: list[int]) -> None:
        """Unsuspend all cards belonging to the given notes."""
        card_ids = self._notes_to_cards(note_ids)
        if card_ids:
            self._request("unsuspend", cards=card_ids)

    def _notes_to_cards(self, note_ids: list[int]) -> list[int]:
        """Resolve note IDs → card IDs via findCards."""
        if not note_ids:
            return []
        query = " OR ".join(f"nid:{nid}" for nid in note_ids)
        return self.find_cards(query)

    # ------------------------------------------------------------------
    # Duplicate filtering
    # ------------------------------------------------------------------

    def existing_traditionals(self, deck: str) -> set[str]:
        """Return all Traditional field values already in the deck."""
        note_ids = self.find_notes(f'deck:"{deck}"')
        if not note_ids:
            return set()
        notes = self.get_notes_info(note_ids)
        return {
            note["fields"]["Traditional"]["value"]
            for note in notes
            if note.get("fields", {}).get("Traditional")
        }

    def filter_duplicates(self, cards: list[ChineseCard], deck: str) -> list[ChineseCard]:
        """Remove cards whose Traditional value already exists in the deck."""
        existing = self.existing_traditionals(deck)
        return [c for c in cards if c.traditional not in existing]

    def known_words(self, decks: list[str]) -> set[str]:
        """Union of Traditional values across several study decks."""
        known: set[str] = set()
        for deck in decks:
            known |= self.existing_traditionals(deck)
        return known

    # ------------------------------------------------------------------
    # Data quality
    # ------------------------------------------------------------------

    AUDIO_FIELDS = ("WordAudio", "SentenceAudio")

    def notes_missing_audio(self, deck: str) -> list[dict]:
        """Notes in the deck that have an audio field but left it blank.

        Notes whose note type lacks the field entirely are not flagged, so this
        stays meaningful in decks holding more than one note type.
        """
        note_ids = self.find_notes(f'deck:"{deck}"')
        if not note_ids:
            return []
        missing = []
        for note in self.get_notes_info(note_ids):
            fields = note.get("fields", {})
            gaps = [
                name
                for name in self.AUDIO_FIELDS
                if name in fields and not fields[name].get("value", "").strip()
            ]
            if gaps:
                missing.append(
                    {
                        "note_id": note["noteId"],
                        "traditional": fields.get("Traditional", {}).get("value", ""),
                        "missing_fields": gaps,
                    }
                )
        return missing

    # ------------------------------------------------------------------
    # Moving / deleting notes
    # ------------------------------------------------------------------

    def change_deck(self, card_ids: list[int], deck: str) -> None:
        """Move the given cards into another deck."""
        if card_ids:
            self._request("changeDeck", cards=card_ids, deck=deck)

    def delete_notes(self, note_ids: list[int]) -> None:
        """Permanently delete the given notes (and their cards)."""
        if note_ids:
            self._request("deleteNotes", notes=note_ids)
