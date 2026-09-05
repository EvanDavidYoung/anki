"""Generate multiple-choice quizzes from a session's vocab + source text."""

import json
import random

from anki_client.config import get_settings
from anki_client.generator import _extract_json
from anki_client.llm_client import LLMClient

QUIZ_SYSTEM_PROMPT = """\
You are a Mandarin Chinese quiz writer for an advanced learner.

You are given a passage of Chinese text and a list of vocabulary words drawn
from it. Write {n} multiple-choice questions testing comprehension of that
vocabulary as used in the passage.

Mix these question types roughly evenly:
- Meaning: give the Traditional word, ask which English meaning is correct.
- Recognition: give an English meaning, ask which Traditional word matches.
- Cloze: give a sentence from (or in the style of) the passage with one word
  replaced by ___, ask which word fills the blank.
- Usage: ask which sentence uses the word correctly.

Rules:
- Traditional characters only. Never use Simplified.
- Exactly 4 choices per question. Exactly one is correct.
- Distractors must be plausible: other words from the list, or near-synonyms.
  Never use joke or obviously wrong options.
- "explanation" is one short sentence saying why the answer is right.
- Vary which index is correct; do not always put the answer first.

Output a JSON array only - no markdown, no explanation, nothing else.

Schema for each element:
{{
  "word": "the Traditional vocabulary word this question is about",
  "prompt": "the question text",
  "choices": ["...", "...", "...", "..."],
  "answer_index": 0,
  "explanation": "..."
}}
"""


class QuizGenerationError(RuntimeError):
    pass


def quiz_llm() -> LLMClient:
    """The model used for quiz writing, which may be a different provider."""
    s = get_settings()
    return LLMClient(
        settings=s,
        model=s.llm_quiz_model or None,
        base_url=s.llm_quiz_base_url or None,
        api_key=s.llm_quiz_api_key or None,
    )


def _build_user_message(source_text: str, cards: list[dict]) -> str:
    lines = ["Vocabulary list:"]
    for c in cards:
        lines.append(
            f"- {c['traditional']} ({c['pinyin']}) = {c['meaning']}"
            f" [{c['part_of_speech']}]"
        )
    lines.append("")
    lines.append("Source passage:")
    lines.append(source_text)
    return "\n".join(lines)


def _normalize(obj: dict, words: set[str]) -> dict:
    choices = obj.get("choices") or []
    if not isinstance(choices, list) or len(choices) != 4:
        raise QuizGenerationError(f"question does not have 4 choices: {obj!r}")
    choices = [str(c) for c in choices]

    try:
        answer_index = int(obj["answer_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QuizGenerationError(f"missing/invalid answer_index: {obj!r}") from exc
    if not 0 <= answer_index < 4:
        raise QuizGenerationError(f"answer_index out of range: {obj!r}")

    prompt = str(obj.get("prompt") or "").strip()
    if not prompt:
        raise QuizGenerationError(f"missing prompt: {obj!r}")

    word = str(obj.get("word") or "").strip()
    return {
        "word": word if word in words else "",
        "prompt": prompt,
        "choices": choices,
        "answer_index": answer_index,
        "explanation": str(obj.get("explanation") or "").strip(),
    }


def generate(
    source_text: str,
    cards: list[dict],
    n: int = 8,
    llm: LLMClient | None = None,
) -> list[dict]:
    """Return normalized question dicts. Raises QuizGenerationError on bad output."""
    if not cards:
        raise QuizGenerationError("no cards to build a quiz from")

    n = max(1, min(n, len(cards) * 2))
    client = llm or quiz_llm()
    raw = client.complete(
        system=QUIZ_SYSTEM_PROMPT.format(n=n),
        user=_build_user_message(source_text, cards),
    )
    try:
        items = json.loads(_extract_json(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise QuizGenerationError(f"LLM did not return valid JSON: {raw[:200]!r}") from exc
    if not isinstance(items, list) or not items:
        raise QuizGenerationError(f"expected a non-empty JSON array, got: {raw[:200]!r}")

    words = {c["traditional"] for c in cards}
    questions = [_normalize(obj, words) for obj in items if isinstance(obj, dict)]
    if not questions:
        raise QuizGenerationError("no usable questions in LLM output")
    random.shuffle(questions)
    return questions[:n]
