import pytest
from conftest import VOCAB_JSON, StubLLM

from anki_client.generator import ChineseCardGenerator, _extract_json
from anki_client.sources.base import ContentItem


def test_extract_json_handles_fenced_output():
    assert _extract_json('```json\n[{"a": 1}]\n```') == '[{"a": 1}]'


def test_extract_json_handles_chatty_output():
    text = 'Sure! Here you go:\n[{"a": 1}]\nHope that helps.'
    assert _extract_json(text) == '[{"a": 1}]'


def test_extract_json_passes_through_bare_array():
    assert _extract_json('[{"a": 1}]') == '[{"a": 1}]'


def test_generate_with_explicit_next_key_never_touches_anki():
    # anki is left unset, so AnkiClient would only be built lazily — passing
    # next_key means the web app can generate cards with Anki closed.
    gen = ChineseCardGenerator(llm=StubLLM(VOCAB_JSON))
    cards = gen.generate(ContentItem(raw_text="text", title="t"), next_key=7)

    assert [c.traditional for c in cards] == ["夜市", "攝販"]
    assert [c.key for c in cards] == ["7", "8"]
    assert cards[0].meaning == "night market"
    assert cards[0].sentence_pinyin.startswith("wǒ men")


def test_generate_raises_on_unparseable_output():
    gen = ChineseCardGenerator(llm=StubLLM("I'm afraid I can't do that."))
    with pytest.raises(Exception):
        gen.generate(ContentItem(raw_text="x", title="t"), next_key=1)
