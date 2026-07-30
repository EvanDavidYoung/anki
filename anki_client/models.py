from pydantic import BaseModel


class ChineseCard(BaseModel):
    key: str
    traditional: str
    pinyin: str
    meaning: str
    part_of_speech: str
    sentence_traditional: str
    sentence_pinyin: str
    sentence_meaning: str
    sentence_audio: str = ""
    word_audio: str = ""
    tags: list[str] = []


class DeckStats(BaseModel):
    deck_id: int
    name: str
    new_count: int
    learn_count: int
    review_count: int
    total_in_deck: int


class AddResult(BaseModel):
    added: int
    duplicates: int
    errors: int
    note_ids: list[int] = []
