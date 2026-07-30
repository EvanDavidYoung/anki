import hashlib
from typing import Protocol

from pydantic import BaseModel

# Message.kind values — the typed-message seam. "text" goes through the text
# card generator; "image-only" and "text+image" carry images for the (future)
# vision/OCR path. A "text+image" message still contributes its text to a batch.
KIND_TEXT = "text"
KIND_TEXT_IMAGE = "text+image"
KIND_IMAGE_ONLY = "image-only"


class ImageRef(BaseModel):
    """An image referenced in a source message.

    Used both to attach incoming images to cards and to drive OCR for
    image-only messages (post-MVP). ``message_text`` is the text of the
    message the image appeared in, if any.
    """

    url: str
    alt: str = ""
    message_text: str = ""


class ContentItem(BaseModel):
    raw_text: str
    title: str
    url: str = ""
    suggested_deck: str = ""
    # Bold/emphasized words the author flagged → vocab or cloze deletion targets.
    priority_terms: list[str] = []
    # Absolute path of the source file, used to "mark as ingested" after review.
    source_path: str = ""
    # Images referenced in the source (attached to cards / OCR'd post-MVP).
    images: list[ImageRef] = []
    # When a ContentItem is built from a batch of messages spanning files, these
    # carry provenance into card tags (one chatlog:<stem> tag per source file).
    source_files: list[str] = []
    message_ids: list[int] = []


class Message(BaseModel):
    """One chat message parsed from a source file.

    The persisted, typed unit of ingestion. Text messages are batched into
    card-generation requests; image-bearing messages keep their ``image_refs``
    for the future vision/OCR path. ``content_hash`` makes re-parsing idempotent.
    """

    source_file: str  # stem of the .md (no extension)
    kind: str = KIND_TEXT  # KIND_TEXT | KIND_TEXT_IMAGE | KIND_IMAGE_ONLY
    author: str = ""
    ts: str = ""  # HH:MM from the bullet
    text: str = ""  # cleaned Chinese, markers/zero-width stripped
    image_refs: list[ImageRef] = []
    priority_terms: list[str] = []
    content_hash: str = ""

    def compute_hash(self) -> str:
        """Stable hash over the message's identity for dedup on re-parse."""
        urls = "|".join(img.url for img in self.image_refs)
        basis = f"{self.source_file}|{self.ts}|{self.author}|{self.text}|{urls}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()


class ContentSource(Protocol):
    def fetch(self) -> list[ContentItem]: ...
