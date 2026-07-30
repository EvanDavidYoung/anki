import json
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel

from .client import AnkiClient
from .llm_client import LLMClient
from .models import ChineseCard
from .sources.base import ContentItem


class GenerationContext(BaseModel):
    """Learner context injected into the generation prompt."""

    estimated_level: str = ""  # e.g. "HSK 4"
    known_sample: list[str] = []  # a sample of words the learner already knows
    # card_type drives vocab vs cloze selection. MVP implements "vocab"; "auto"
    # currently behaves as vocab and will route bolded words to cloze post-MVP.
    card_type: str = "auto"

CHINESE_SYSTEM_PROMPT = """\
You are a Mandarin Chinese flashcard generator for an advanced learner.

Given an article or passage in Chinese, extract 5–15 vocabulary words worth studying.
Focus on words that are useful, non-trivial, and appear in the source text.
Skip extremely common words (你好, 是, 的, etc.) the learner already knows.

Rules:
- Traditional characters only. Never use Simplified.
- Pinyin must use Unicode tone marks (e.g. nǐ hǎo, not ni3 hao3).
- part_of_speech: one of noun, verb, adjective, adverb, measure word, phrase, conjunction, preposition, particle.
- sentence_traditional / sentence_pinyin / sentence_meaning: use a sentence from the source text when possible, otherwise compose one.
- Sentences must be natural, complete, and demonstrate the word in context.

Output a JSON array only — no markdown, no explanation, nothing else.

Schema for each element:
{
  "traditional": "...",
  "pinyin": "...",
  "meaning": "...",
  "part_of_speech": "...",
  "sentence_traditional": "...",
  "sentence_pinyin": "...",
  "sentence_meaning": "..."
}
"""

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


class CardGenerator(ABC):
    def __init__(self, llm: LLMClient | None = None, anki: AnkiClient | None = None):
        self._llm = llm or LLMClient()
        self._anki = anki or AnkiClient()

    @abstractmethod
    def _system_prompt(self) -> str: ...

    @abstractmethod
    def _parse(self, text: str, next_key: int) -> list[BaseModel]: ...

    def generate(
        self,
        item: ContentItem,
        context: GenerationContext | None = None,
    ) -> list[BaseModel]:
        next_key = self._anki.next_key()
        system = self._system_prompt()
        if context or item.priority_terms:
            system = self._augment_system(system, item, context)
        response = self._llm.complete(system=system, user=item.raw_text)
        return self._parse(response, next_key)

    def _augment_system(
        self,
        system: str,
        item: ContentItem,
        context: GenerationContext | None,
    ) -> str:
        """Append learner context + flagged words to the system prompt."""
        lines = ["\n\nLearner context:"]
        if context and context.estimated_level:
            lines.append(f"- Estimated level: {context.estimated_level}.")
        if context and context.known_sample:
            sample = "、".join(context.known_sample[:60])
            lines.append(
                "- The learner already knows these words — do NOT make cards for "
                f"them: {sample}."
            )
        if item.priority_terms:
            flagged = "、".join(item.priority_terms)
            lines.append(
                "- The learner explicitly flagged these words — prioritize making "
                f"cards for them: {flagged}."
            )
        return system + "\n".join(lines)


class ChineseCardGenerator(CardGenerator):
    def _system_prompt(self) -> str:
        return CHINESE_SYSTEM_PROMPT

    def _parse(self, text: str, next_key: int) -> list[ChineseCard]:
        raw = _extract_json(text)
        items = json.loads(raw)
        cards = []
        for i, obj in enumerate(items):
            cards.append(
                ChineseCard(
                    key=str(next_key + i),
                    traditional=obj["traditional"],
                    pinyin=obj["pinyin"],
                    meaning=obj["meaning"],
                    part_of_speech=obj.get("part_of_speech", ""),
                    sentence_traditional=obj.get("sentence_traditional", ""),
                    sentence_pinyin=obj.get("sentence_pinyin", ""),
                    sentence_meaning=obj.get("sentence_meaning", ""),
                )
            )
        return cards


class ImageCardGenerator:
    """Seam for the (deferred) vision/OCR path — see plan §4b.

    Image-only and text+image messages persist their ``image_refs`` in the
    message store and stay in state ``new`` until this owner consumes them.
    Wiring it up means: read the image bytes (Google Drive MCP / HTTP), call a
    vision-capable model (``LLMClient.complete_vision`` + ``config.vision_model``)
    to OCR/describe → produce cards, and attach the source image to the card via
    ``AnkiClient.store_media_file``. Until then this is an explicit no-op so the
    pending image messages have a clear, named owner rather than silently piling
    up untyped.
    """

    def __init__(self, llm: LLMClient | None = None, anki: AnkiClient | None = None):
        self._llm = llm
        self._anki = anki or AnkiClient()

    def generate_pending_images(self, messages: list) -> list[BaseModel]:
        if messages:
            raise NotImplementedError(
                f"{len(messages)} image message(s) awaiting the vision path "
                "(plan §4b) — not yet implemented."
            )
        return []


def _extract_json(text: str) -> str:
    m = _JSON_BLOCK.search(text)
    if m:
        return m.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text.strip()
