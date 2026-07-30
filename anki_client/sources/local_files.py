from pathlib import Path

from ..config import get_settings
from .base import ContentItem


class LocalFileSource:
    def __init__(self, input_dir: Path | None = None):
        self._input_dir = input_dir or get_settings().input_dir
        self._processed_dir = self._input_dir / "processed"

    def fetch(self) -> list[ContentItem]:
        self._processed_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for path in sorted(self._input_dir.glob("*.md")) + sorted(
            self._input_dir.glob("*.txt")
        ):
            text = path.read_text(encoding="utf-8")
            items.append(
                ContentItem(
                    raw_text=text,
                    title=path.stem,
                    suggested_deck=get_settings().default_deck,
                )
            )
            path.rename(self._processed_dir / path.name)
        return items
