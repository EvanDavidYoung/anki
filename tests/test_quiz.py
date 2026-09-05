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


def test_quiz_llm_falls_back_to_the_main_provider(monkeypatch):
    """With no llm_quiz_* overrides, quiz writing uses the project default."""
    import anki_client.llm_client as llm_module
    from vocabapp.services.quiz import quiz_llm

    captured = {}
    monkeypatch.setattr(
        llm_module.openai,
        "OpenAI",
        lambda base_url, api_key: captured.update(base_url=base_url, api_key=api_key),
    )
    settings = _settings(llm_quiz_model="", llm_quiz_base_url="", llm_quiz_api_key="")
    monkeypatch.setattr("vocabapp.services.quiz.get_settings", lambda: settings)

    assert quiz_llm()._model == "main-model"
    assert captured == {"base_url": "https://main.example/v1", "api_key": "main-key"}


def test_quiz_llm_can_point_at_a_different_provider(monkeypatch):
    import anki_client.llm_client as llm_module
    from vocabapp.services.quiz import quiz_llm

    captured = {}
    monkeypatch.setattr(
        llm_module.openai,
        "OpenAI",
        lambda base_url, api_key: captured.update(base_url=base_url, api_key=api_key),
    )
    settings = _settings(
        llm_quiz_base_url="https://quiz.example/v1",
        llm_quiz_api_key="quiz-key",
        llm_quiz_model="better-model",
    )
    monkeypatch.setattr("vocabapp.services.quiz.get_settings", lambda: settings)

    assert quiz_llm()._model == "better-model"
    assert captured == {"base_url": "https://quiz.example/v1", "api_key": "quiz-key"}


def _settings(**overrides):
    from anki_client.config import Settings

    return Settings(
        llm_base_url="https://main.example/v1",
        llm_api_key="main-key",
        llm_model="main-model",
        default_deck="QA",
        **overrides,
    )
