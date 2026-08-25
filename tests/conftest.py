import pytest


@pytest.fixture
def client(tmp_path):
    """A TestClient backed by a throwaway database."""
    from vocabapp import db

    db.set_db_path(tmp_path / "test.db")
    try:
        from fastapi.testclient import TestClient

        from vocabapp.main import app

        with TestClient(app) as c:
            yield c
    finally:
        db.set_db_path(None)


VOCAB_JSON = """[
  {"traditional": "夜市", "pinyin": "yè shì", "meaning": "night market",
   "part_of_speech": "noun", "sentence_traditional": "我們去夜市吃東西。",
   "sentence_pinyin": "wǒ men qù yè shì chī dōng xī.",
   "sentence_meaning": "We go to the night market to eat."},
  {"traditional": "攝販", "pinyin": "tān fàn", "meaning": "street vendor",
   "part_of_speech": "noun", "sentence_traditional": "攝販擺出攝位。",
   "sentence_pinyin": "tān fàn bǎi chū tān wèi.",
   "sentence_meaning": "The vendors set out their stalls."}
]"""

QUIZ_JSON = """[
  {"word": "夜市", "prompt": "夜市 means:",
   "choices": ["night market", "morning market", "vendor", "stall"],
   "answer_index": 0, "explanation": "夜 is night and 市 is market."},
  {"word": "攝販", "prompt": "Which word means 'street vendor'?",
   "choices": ["夜市", "攝販", "遊客", "傍晚"],
   "answer_index": 1, "explanation": "攝販 is the vendor who runs a stall."}
]"""


class StubLLM:
    """Stands in for LLMClient; records the prompts it was given."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.response
