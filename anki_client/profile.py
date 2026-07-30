import re

from .client import AnkiClient
from .config import Settings, get_settings

# Anki considers a card "mature" once its interval reaches 21 days.
MATURE_IVL = 21
_HSK_TAG = re.compile(r"^HSK(\d+)$")


def _hsk_band(tags: list[str]) -> int | None:
    for tag in tags:
        m = _HSK_TAG.match(tag)
        if m:
            return int(m.group(1))
    return None


def _traditional(note: dict) -> str:
    return note.get("fields", {}).get("Traditional", {}).get("value", "")


class LearnerProfile:
    """Derives the learner's known words and estimated level from Anki.

    Known words = Traditional values across the configured study decks.
    Level = highest HSK band (tag ``HSK<n>`` on the HSK deck) for which the
    learner has matured most of the words.
    """

    def __init__(self, client: AnkiClient | None = None, settings: Settings | None = None):
        self._c = client or AnkiClient()
        self._cfg = settings or get_settings()

    def known_words(self) -> set[str]:
        return self._c.known_words(self._cfg.study_decks)

    def mature_words(self) -> set[str]:
        words: set[str] = set()
        for deck in self._cfg.study_decks:
            note_ids = self._c.find_notes(f'deck:"{deck}" prop:ivl>={MATURE_IVL}')
            if not note_ids:
                continue
            for note in self._c.get_notes_info(note_ids):
                trad = _traditional(note)
                if trad:
                    words.add(trad)
        return words

    def coverage_by_band(self, mature: set[str] | None = None) -> dict[int, dict]:
        """Per-HSK-band totals and how many of those words the learner has matured."""
        mature = self.mature_words() if mature is None else mature
        bands: dict[int, dict] = {}
        note_ids = self._c.find_notes(f'deck:"{self._cfg.hsk_deck}"')
        for note in self._c.get_notes_info(note_ids):
            band = _hsk_band(note.get("tags", []))
            if band is None:
                continue
            entry = bands.setdefault(band, {"total": 0, "known": 0})
            entry["total"] += 1
            if _traditional(note) in mature:
                entry["known"] += 1
        return dict(sorted(bands.items()))

    def estimate_level(self, threshold: float = 80.0) -> dict:
        """Estimate level as the highest contiguous HSK band matured to ``threshold``%."""
        mature = self.mature_words()
        bands = self.coverage_by_band(mature)
        coverage = {
            lvl: round(v["known"] / v["total"] * 100, 1) if v["total"] else 0.0
            for lvl, v in bands.items()
        }
        estimated = None
        for lvl in sorted(coverage):
            if coverage[lvl] >= threshold:
                estimated = lvl
            else:
                break
        return {
            "estimated_level": f"HSK {estimated}" if estimated else "below HSK 1",
            "coverage_by_band": coverage,
            "known_word_count": len(self.known_words()),
            "mature_word_count": len(mature),
        }
