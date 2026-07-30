import uuid

from .client import AnkiClient
from .config import Settings, get_settings
from .generator import ChineseCardGenerator, GenerationContext
from .models import ChineseCard
from .profile import LearnerProfile
from .sources.base import ContentItem
from .sources.slack_export import SlackExportSource
from .store import STATE_DONE, MessageStore
from .tts import generate_and_store, random_voice

PENDING_TAG = "status:pending"


def _chatlog_tag(stem: str) -> str:
    return f"chatlog:{stem}"


def _batch_tag(batch_id: str) -> str:
    return f"msgbatch:{batch_id}"


def _note_summary(note: dict) -> dict:
    f = note.get("fields", {})

    def field(name: str) -> str:
        return f.get(name, {}).get("value", "")

    return {
        "note_id": note["noteId"],
        "traditional": field("Traditional"),
        "pinyin": field("Pinyin"),
        "meaning": field("Meaning"),
        "sentence_traditional": field("SentenceTraditional"),
        "sentence_meaning": field("SentenceMeaning"),
        "tags": note.get("tags", []),
    }


class StagingService:
    """Human-in-the-loop pipeline: sync → stage → review → approve/reject.

    Ingestion is two phases. ``sync_sources`` parses source files into the
    SQLite message store (typed, deduped) and retires the ``.md`` to
    ``processed/``. ``generate_pending`` batches *new text messages across
    files* (``message_batch_size`` per LLM request), generates candidate cards,
    and stages them in Anki — suspended, tagged ``status:pending`` (no audio
    yet). Approval generates audio, moves the note to the target deck,
    unsuspends it, and clears the pending tag.
    """

    def __init__(
        self,
        client: AnkiClient | None = None,
        settings: Settings | None = None,
        store: MessageStore | None = None,
        source_label: str = "slack",
    ):
        self._c = client or AnkiClient()
        self._cfg = settings or get_settings()
        self._store = store or MessageStore(self._cfg.message_db)
        self._gen = ChineseCardGenerator(anki=self._c)
        self._source_label = source_label

    # ------------------------------------------------------------------
    # Phase 1 — sync source files into the message store
    # ------------------------------------------------------------------

    def sync_sources(self, source: SlackExportSource | None = None) -> dict:
        """Parse chat-log files into the message store, then move them to
        ``processed/``. Idempotent: re-parsing the same content inserts nothing
        (dedup on content_hash)."""
        src = source or SlackExportSource(self._cfg.chatlog_dir)
        messages = src.fetch_messages()
        new_ids = self._store.add_messages(messages)

        moved = self._archive_source_files()
        return {
            "parsed_messages": len(messages),
            "new_messages": len(new_ids),
            "files_archived": moved,
        }

    def _archive_source_files(self) -> int:
        processed = self._cfg.chatlog_dir / "processed"
        moved = 0
        for path in sorted(self._cfg.chatlog_dir.glob("*.md")):
            processed.mkdir(parents=True, exist_ok=True)
            path.rename(processed / path.name)
            moved += 1
        return moved

    # ------------------------------------------------------------------
    # Phase 2 — generate cards from pending messages, in batches
    # ------------------------------------------------------------------

    def generate_pending(
        self, card_type: str = "auto", batch_size: int | None = None
    ) -> list[dict]:
        size = batch_size or self._cfg.message_batch_size
        self._ensure_staging_deck()
        context = self._build_context(card_type)
        # Skip words the learner already has anywhere (study decks + staging).
        known = self._c.known_words(self._cfg.study_decks) | self._c.existing_traditionals(
            self._cfg.staging_deck
        )

        batches: list[dict] = []
        for batch in self._store.iter_text_batches(size):
            batch_id = uuid.uuid4().hex[:8]
            message_ids = [m.id for m in batch]
            source_files = sorted({m.source_file for m in batch})

            item = self._batch_to_item(batch, batch_id, source_files)
            cards: list[ChineseCard] = []
            if item.raw_text.strip():
                cards = self._gen.generate(item, context)  # type: ignore[assignment]

            tags = [
                PENDING_TAG,
                f"source:{self._source_label}",
                _batch_tag(batch_id),
                *[_chatlog_tag(stem) for stem in source_files],
            ]
            fresh: list[ChineseCard] = []
            for card in cards:
                if card.traditional in known:
                    continue
                known.add(card.traditional)  # avoid intra-run duplicates
                card.tags = list(tags)
                fresh.append(card)

            note_ids: list[int] = []
            if fresh:
                result = self._c.add_notes_batch(fresh, self._cfg.staging_deck)
                note_ids = result.note_ids
                if note_ids:
                    self._c.suspend(note_ids)

            # Cards generated → staged; nothing generated → done (no review owed).
            if note_ids:
                self._store.mark_staged(message_ids, batch_id, note_ids)
            else:
                self._store.set_state(message_ids, STATE_DONE)

            staged = self._c.get_notes_info(note_ids) if note_ids else []
            batches.append(
                {
                    "batch_id": batch_id,
                    "source_files": source_files,
                    "message_count": len(batch),
                    "staged": [_note_summary(n) for n in staged],
                }
            )
        return batches

    def ingest(self, card_type: str = "auto", batch_size: int | None = None) -> dict:
        """Convenience: sync source files, then generate cards for all pending
        messages. Returns the sync summary plus the staged batches."""
        synced = self.sync_sources()
        batches = self.generate_pending(card_type, batch_size)
        return {"synced": synced, "batches": batches}

    def _batch_to_item(self, batch, batch_id: str, source_files: list[str]) -> ContentItem:
        raw_text = "\n".join(m.text for m in batch if m.text)
        priority_terms: list[str] = []
        for m in batch:
            for term in m.priority_terms:
                if term not in priority_terms:
                    priority_terms.append(term)
        return ContentItem(
            raw_text=raw_text,
            title=f"batch {batch_id}",
            suggested_deck=self._cfg.target_deck,
            priority_terms=priority_terms,
            source_files=source_files,
            message_ids=[m.id for m in batch],
        )

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def list_pending(self) -> list[dict]:
        query = f'deck:"{self._cfg.staging_deck}" tag:{PENDING_TAG}'
        note_ids = self._c.find_notes(query)
        if not note_ids:
            return []
        return [_note_summary(n) for n in self._c.get_notes_info(note_ids)]

    def _write_audio(self, notes: list[dict]) -> None:
        """Synthesize word + sentence audio for each note and write it back.

        One voice per note, shared by both clips, so the word and the sentence
        it appears in are spoken by the same speaker.
        """
        if not notes:
            return
        texts_voices: list[tuple[str, str]] = []
        for note in notes:
            voice = random_voice()
            f = note.get("fields", {})
            texts_voices.append((f.get("Traditional", {}).get("value", ""), voice))
            texts_voices.append((f.get("SentenceTraditional", {}).get("value", ""), voice))
        audio = generate_and_store(texts_voices, self._c)
        for i, note in enumerate(notes):
            self._c.update_note_fields(
                note["noteId"],
                {"WordAudio": audio[i * 2], "SentenceAudio": audio[i * 2 + 1]},
            )

    def approve(self, note_ids: list[int], target_deck: str | None = None) -> dict:
        if not note_ids:
            return {"approved": 0}
        target = target_deck or self._cfg.target_deck
        self._write_audio(self._c.get_notes_info(note_ids))

        card_ids = self._c._notes_to_cards(note_ids)
        self._c.change_deck(card_ids, target)
        self._c.unsuspend(note_ids)
        self._c.remove_tags(note_ids, [PENDING_TAG])
        return {"approved": len(note_ids), "target_deck": target}

    def approve_batch(self, batch_id: str, target_deck: str | None = None) -> dict:
        """Approve every still-pending card staged under one generation batch."""
        query = (
            f'deck:"{self._cfg.staging_deck}" tag:{PENDING_TAG} tag:{_batch_tag(batch_id)}'
        )
        note_ids = self._c.find_notes(query)
        if not note_ids:
            return {"approved": 0, "batch_id": batch_id}
        return {**self.approve(note_ids, target_deck), "batch_id": batch_id}

    def regenerate_audio(self, note_ids: list[int]) -> dict:
        """Re-synthesize audio from the notes' current text.

        Editing Traditional or SentenceTraditional leaves the existing
        ``[sound:]`` tags pointing at clips of the pre-edit text; this repairs
        them.
        """
        if not note_ids:
            return {"regenerated": 0}
        self._write_audio(self._c.get_notes_info(note_ids))
        return {"regenerated": len(note_ids)}

    def reject(self, note_ids: list[int]) -> dict:
        if not note_ids:
            return {"rejected": 0}
        self._c.delete_notes(note_ids)
        return {"rejected": len(note_ids)}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_context(self, card_type: str) -> GenerationContext | None:
        try:
            prof = LearnerProfile(self._c, self._cfg)
            level = prof.estimate_level().get("estimated_level", "")
            known_sample = sorted(prof.known_words())[:60]
        except Exception:
            return GenerationContext(card_type=card_type)
        return GenerationContext(
            estimated_level=level, known_sample=known_sample, card_type=card_type
        )

    def _ensure_staging_deck(self) -> None:
        if self._cfg.staging_deck not in self._c.deck_names():
            self._c.create_deck(self._cfg.staging_deck)
