import pytest
from conftest import QUIZ_JSON, StubLLM

from vocabapp.services.quiz import QuizGenerationError, generate

CARDS = [
    {
        "id": 1,
        "traditional": "夜市",
        "pinyin": "yè shì",
        "meaning": "night market",
        "part_of_speech": "noun",
    },
    {
        "id": 2,
        "traditional": "攝販",
        "pinyin": "tān fàn",
        "meaning": "street vendor",
        "part_of_speech": "noun",
    },
]


def test_generate_returns_normalized_questions():
    questions = generate("passage", CARDS, n=2, llm=StubLLM(QUIZ_JSON))

    assert len(questions) == 2
    for q in questions:
        assert len(q["choices"]) == 4
        assert 0 <= q["answer_index"] < 4
        assert q["prompt"]
        assert q["word"] in {"夜市", "攝販"}


def test_generate_includes_vocab_and_passage_in_the_prompt():
    llm = StubLLM(QUIZ_JSON)
    generate("台灣的夜市文化", CARDS, n=2, llm=llm)
    _, user = llm.calls[0]

    assert "夜市" in user
    assert "night market" in user
    assert "台灣的夜市文化" in user


def test_word_not_in_the_vocab_list_is_dropped():
    payload = QUIZ_JSON.replace('"word": "夜市"', '"word": "不存在"')
    questions = generate("passage", CARDS, n=2, llm=StubLLM(payload))
    words = {q["word"] for q in questions}

    assert "不存在" not in words
    assert "" in words  # unmatched word becomes empty, so no bogus card link


def test_no_cards_raises():
    with pytest.raises(QuizGenerationError, match="no cards"):
        generate("passage", [], n=4, llm=StubLLM(QUIZ_JSON))


@pytest.mark.parametrize(
    "payload, match",
    [
        ("not json at all", "valid JSON"),
        ("[]", "non-empty JSON array"),
        ('[{"prompt": "x", "choices": ["a", "b"], "answer_index": 0}]', "4 choices"),
        ('[{"prompt": "x", "choices": ["a","b","c","d"], "answer_index": 9}]', "out of range"),
        ('[{"prompt": "x", "choices": ["a","b","c","d"]}]', "answer_index"),
        ('[{"prompt": "", "choices": ["a","b","c","d"], "answer_index": 0}]', "missing prompt"),
    ],
)
def test_malformed_llm_output_raises_cleanly(payload, match):
    with pytest.raises(QuizGenerationError, match=match):
        generate("passage", CARDS, n=2, llm=StubLLM(payload))
