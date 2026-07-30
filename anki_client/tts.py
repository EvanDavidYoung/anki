import asyncio
import hashlib
import html
import random
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import edge_tts

if TYPE_CHECKING:
    from .client import AnkiClient

VOICES = ["zh-TW-HsiaoChenNeural", "zh-TW-YunJheNeural"]

_CLOZE_RE = re.compile(r"\{\{c\d+::(.+?)(?:::.+?)?\}\}")
_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text: str) -> str:
    """Prepare text for TTS: strip cloze markers, HTML/SSML tags, and unescape HTML entities."""
    text = _CLOZE_RE.sub(r"\1", text)   # {{c1::word}} or {{c1::word::hint}} → word
    text = _TAG_RE.sub("", text)         # <b>, <speak>, SSML tags, etc.
    text = html.unescape(text)           # &amp; → &, &lt; → <, etc.
    return text.strip()


def random_voice() -> str:
    return random.choice(VOICES)


def _filename(text: str, voice: str) -> str:
    digest = hashlib.sha256(f"{voice}:{text}".encode()).hexdigest()[:12]
    return f"tts_{digest}.mp3"


async def _synthesize_one(text: str, voice: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp = f.name
    try:
        await edge_tts.Communicate(clean_text(text), voice).save(tmp)
        return Path(tmp).read_bytes()
    finally:
        Path(tmp).unlink(missing_ok=True)


def generate_and_store(texts_voices: list[tuple[str, str]], anki: "AnkiClient") -> list[str]:
    """Generate TTS audio for (text, voice) pairs concurrently, store in Anki's media
    collection, and return a [sound:filename.mp3] tag for each pair."""
    filenames = [_filename(text, voice) for text, voice in texts_voices]

    async def _run_all() -> list[bytes]:
        return list(await asyncio.gather(*[_synthesize_one(t, v) for t, v in texts_voices]))

    audio_list = asyncio.run(_run_all())
    for filename, audio in zip(filenames, audio_list):
        anki.store_media_file(filename, audio)

    return [f"[sound:{fn}]" for fn in filenames]
