from pydantic import BaseModel, Field


# ---------------------------------------------------------------- sessions


class SessionCreate(BaseModel):
    text: str = Field(min_length=1)
    title: str = ""


class CardOut(BaseModel):
    id: int
    session_id: int
    traditional: str
    pinyin: str
    meaning: str
    part_of_speech: str
    sentence_traditional: str
    sentence_pinyin: str
    sentence_meaning: str
    status: str
    anki_note_id: int | None = None


class SessionOut(BaseModel):
    id: int
    title: str
    created_at: str
    card_count: int = 0
    approved_count: int = 0
    pending_count: int = 0


class SessionDetail(SessionOut):
    source_text: str
    cards: list[CardOut] = []


# ------------------------------------------------------------------- cards


class CardUpdate(BaseModel):
    """Every field optional — only what's sent gets written."""

    traditional: str | None = None
    pinyin: str | None = None
    meaning: str | None = None
    part_of_speech: str | None = None
    sentence_traditional: str | None = None
    sentence_pinyin: str | None = None
    sentence_meaning: str | None = None


class BulkStatus(BaseModel):
    status: str  # approved | rejected | pending
    card_ids: list[int] | None = None  # None = every pending card in the session


# -------------------------------------------------------------------- quiz


class QuizCreate(BaseModel):
    n: int = Field(default=8, ge=1, le=25)


class QuestionOut(BaseModel):
    """Answers are never sent to the client until it answers."""

    id: int
    prompt: str
    choices: list[str]
    position: int
    answered: bool = False


class AnswerIn(BaseModel):
    chosen_index: int = Field(ge=0)


class AnswerOut(BaseModel):
    correct: bool
    answer_index: int
    explanation: str


class QuizStats(BaseModel):
    total: int
    answered: int
    correct: int


# ------------------------------------------------------------------- study


class StudyAnswer(BaseModel):
    card_id: int
    ease: int = Field(ge=1, le=4)


class StudyCard(BaseModel):
    card: CardOut
    due_count: int
    new_count: int
    reps: int
    interval_days: float


class StudyState(BaseModel):
    due_count: int
    new_count: int
    total: int
    unpushed_reviews: int


# -------------------------------------------------------------------- anki


class AnkiStatus(BaseModel):
    reachable: bool
    decks: list[str] = []
    default_deck: str
    error: str = ""


class ExportRequest(BaseModel):
    session_id: int
    deck: str = ""
    with_audio: bool = False


class ExportResult(BaseModel):
    added: int
    duplicates: int
    errors: int
    note_ids: list[int] = []
    deck: str


class PushReviewsRequest(BaseModel):
    session_id: int | None = None


class PushedReview(BaseModel):
    card_id: int
    traditional: str
    ease: int
    pushed: bool
    reason: str = ""


class PushReviewsResult(BaseModel):
    attempted: int
    pushed: int
    results: list[PushedReview] = []
