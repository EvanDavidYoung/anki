"""Turn a body of Chinese text into candidate vocab cards.

Reuses the prompt and JSON-repair logic already proven in
``anki_client.generator`` rather than re-inventing them here.
"""

from anki_client.generator import ChineseCardGenerator
from anki_client.models import ChineseCard
from anki_client.sources.base import ContentItem

# Keys are placeholders; the real Anki ``Key`` is assigned at export time from a
# live ``AnkiClient.next_key()``, so generation never needs Anki running.
PLACEHOLDER_KEY = 0

_generator: ChineseCardGenerator | None = None


def _get_generator() -> ChineseCardGenerator:
    global _generator
    if _generator is None:
        _generator = ChineseCardGenerator()
    return _generator


def extract(text: str, title: str = "") -> list[ChineseCard]:
    """Extract vocab cards from a passage of Chinese text."""
    item = ContentItem(raw_text=text, title=title or "pasted text")
    return _get_generator().generate(item, next_key=PLACEHOLDER_KEY)
