import re
from pathlib import Path

from ..config import get_settings
from .base import (
    KIND_IMAGE_ONLY,
    KIND_TEXT,
    KIND_TEXT_IMAGE,
    ContentItem,
    ImageRef,
    Message,
)

# Message bullet: "- **user.name** [03:21]: 中文…"
_MESSAGE = re.compile(r"^- \*\*(?P<user>.+?)\*\* \[(?P<time>[\d:]+)\]:\s*(?P<text>.*)$")
# Markdown image: ![alt](url)
_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)")
# Bold/emphasis spans Evan uses to flag a word: **word** or *word*
_EMPHASIS = re.compile(r"\*\*([^*\n]+)\*\*|\*([^*\n]+)\*")
# Frontmatter key: value lines
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Zero-width / invisible characters that appear inside exported usernames & text.
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def _clean(text: str) -> str:
    return text.translate(_ZERO_WIDTH).strip()


def _parse_frontmatter(raw: str) -> dict[str, str]:
    m = _FRONTMATTER.match(raw)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


class SlackExportSource:
    """Parse Slack-export markdown chat logs into typed messages.

    ``fetch_messages`` emits one :class:`Message` per bullet — the unit the
    message store and the message-batched generator work with. Each message is
    classified ``text`` / ``text+image`` / ``image-only`` and carries the words
    Evan flagged with *…* / **…** as ``priority_terms`` plus any referenced
    images. The file is left in place — the staging service moves it to
    ``processed/`` once parsed.

    ``fetch`` (file → one :class:`ContentItem`) is retained for back-compat with
    the generic ``LocalFileSource``/podcast path; it aggregates the messages.
    """

    def __init__(self, input_dir: Path | None = None):
        self._input_dir = input_dir or get_settings().chatlog_dir

    # ------------------------------------------------------------------
    # Typed-message API (current ingestion path)
    # ------------------------------------------------------------------

    def fetch_messages(self) -> list[Message]:
        self._input_dir.mkdir(parents=True, exist_ok=True)
        messages: list[Message] = []
        for path in sorted(self._input_dir.glob("*.md")):
            messages.extend(self._parse_messages(path))
        return messages

    def _parse_messages(self, path: Path) -> list[Message]:
        raw = path.read_text(encoding="utf-8")
        stem = path.stem
        messages: list[Message] = []

        for line in raw.splitlines():
            m = _MESSAGE.match(line)
            if not m:
                continue
            author = _clean(m.group("user"))
            ts = m.group("time")
            text = m.group("text")

            # Pull out this line's images, then strip them from the text.
            images = [
                ImageRef(url=img.group("url").strip(), alt=img.group("alt").strip())
                for img in _IMAGE.finditer(text)
            ]
            text = _IMAGE.sub("", text)

            # Capture flagged words, then drop the markers (keep the word).
            priority_terms: list[str] = []
            for em in _EMPHASIS.finditer(text):
                term = _clean(em.group(1) or em.group(2))
                if term and term not in priority_terms:
                    priority_terms.append(term)
            text = _EMPHASIS.sub(lambda mt: mt.group(1) or mt.group(2), text)

            text = _clean(text)
            for img in images:
                img.message_text = text

            if not text and not images:
                continue  # nothing usable on this bullet

            if text and images:
                kind = KIND_TEXT_IMAGE
            elif images:
                kind = KIND_IMAGE_ONLY
            else:
                kind = KIND_TEXT

            msg = Message(
                source_file=stem,
                kind=kind,
                author=author,
                ts=ts,
                text=text,
                image_refs=images,
                priority_terms=priority_terms,
            )
            msg.content_hash = msg.compute_hash()
            messages.append(msg)

        return messages

    # ------------------------------------------------------------------
    # Legacy file → ContentItem API (podcast / LocalFileSource parity)
    # ------------------------------------------------------------------

    def fetch(self) -> list[ContentItem]:
        self._input_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for path in sorted(self._input_dir.glob("*.md")):
            item = self._parse_file(path)
            if item is not None:
                items.append(item)
        return items

    def _parse_file(self, path: Path) -> ContentItem | None:
        messages = self._parse_messages(path)
        if not messages:
            return None

        lines = [msg.text for msg in messages if msg.text]
        images: list[ImageRef] = []
        priority_terms: list[str] = []
        for msg in messages:
            images.extend(msg.image_refs)
            for term in msg.priority_terms:
                if term not in priority_terms:
                    priority_terms.append(term)

        if not lines and not images:
            return None

        meta = _parse_frontmatter(path.read_text(encoding="utf-8"))
        channel = meta.get("channel", path.stem)
        date = (meta.get("created", "") or "").split("T")[0]
        title = f"{channel} {date}".strip()

        return ContentItem(
            raw_text="\n".join(lines),
            title=title,
            suggested_deck=get_settings().target_deck,
            priority_terms=priority_terms,
            source_path=str(path.resolve()),
            images=images,
            source_files=[path.stem],
        )
