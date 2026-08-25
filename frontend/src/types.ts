export type CardStatus = "pending" | "approved" | "rejected";

export interface Card {
  id: number;
  session_id: number;
  traditional: string;
  pinyin: string;
  meaning: string;
  part_of_speech: string;
  sentence_traditional: string;
  sentence_pinyin: string;
  sentence_meaning: string;
  status: CardStatus;
  anki_note_id: number | null;
}

export interface SessionSummary {
  id: number;
  title: string;
  created_at: string;
  card_count: number;
  approved_count: number;
  pending_count: number;
}

export interface SessionDetail extends SessionSummary {
  source_text: string;
  cards: Card[];
}

export interface Question {
  id: number;
  prompt: string;
  choices: string[];
  position: number;
  answered: boolean;
}

export interface AnswerResult {
  correct: boolean;
  answer_index: number;
  explanation: string;
}

export interface StudyCard {
  card: Card;
  due_count: number;
  new_count: number;
  reps: number;
  interval_days: number;
}

export interface StudyState {
  due_count: number;
  new_count: number;
  total: number;
  unpushed_reviews: number;
}

export interface AnkiStatus {
  reachable: boolean;
  decks: string[];
  default_deck: string;
  error: string;
}

export interface ExportResult {
  added: number;
  duplicates: number;
  errors: number;
  note_ids: number[];
  deck: string;
}

export interface PushedReview {
  card_id: number;
  traditional: string;
  ease: number;
  pushed: boolean;
  reason: string;
}

export interface PushReviewsResult {
  attempted: number;
  pushed: number;
  results: PushedReview[];
}

export const EDITABLE_FIELDS = [
  ["traditional", "Traditional"],
  ["pinyin", "Pinyin"],
  ["meaning", "Meaning"],
  ["part_of_speech", "Part of speech"],
  ["sentence_traditional", "Sentence"],
  ["sentence_pinyin", "Sentence pinyin"],
  ["sentence_meaning", "Sentence meaning"],
] as const;

export type EditableField = (typeof EDITABLE_FIELDS)[number][0];
