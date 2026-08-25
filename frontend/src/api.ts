import type {
  AnkiStatus,
  AnswerResult,
  Card,
  ExportResult,
  PushReviewsResult,
  Question,
  SessionDetail,
  SessionSummary,
  StudyCard,
  StudyState,
} from "./types";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  listSessions: () => request<SessionSummary[]>("/sessions"),
  getSession: (id: number) => request<SessionDetail>(`/sessions/${id}`),
  createSession: (text: string, title: string) =>
    post<SessionDetail>("/sessions", { text, title }),
  deleteSession: (id: number) => request(`/sessions/${id}`, { method: "DELETE" }),

  updateCard: (id: number, patch: Partial<Card>) =>
    request<Card>(`/cards/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  setCardStatus: (id: number, action: "approve" | "reject" | "reset") =>
    post<Card>(`/cards/${id}/${action}`),
  bulkStatus: (sessionId: number, status: string, cardIds?: number[]) =>
    post<Card[]>(`/sessions/${sessionId}/cards/bulk`, { status, card_ids: cardIds ?? null }),

  createQuiz: (sessionId: number, n: number) =>
    post<Question[]>(`/sessions/${sessionId}/quiz`, { n }),
  getQuiz: (sessionId: number) => request<Question[]>(`/sessions/${sessionId}/quiz`),
  answerQuestion: (questionId: number, chosenIndex: number) =>
    post<AnswerResult>(`/quiz/questions/${questionId}/answer`, { chosen_index: chosenIndex }),
  resetQuizAttempts: (sessionId: number) =>
    request(`/sessions/${sessionId}/quiz/attempts`, { method: "DELETE" }),

  nextStudyCard: (sessionId: number) =>
    request<StudyCard | null>(`/sessions/${sessionId}/study/next`),
  studyState: (sessionId: number) => request<StudyState>(`/sessions/${sessionId}/study/state`),
  answerStudy: (cardId: number, ease: number) =>
    post<StudyState>("/study/answer", { card_id: cardId, ease }),

  ankiStatus: () => request<AnkiStatus>("/anki/status"),
  exportToAnki: (sessionId: number, deck: string, withAudio: boolean) =>
    post<ExportResult>("/anki/export", { session_id: sessionId, deck, with_audio: withAudio }),
  pushReviews: (sessionId: number) =>
    post<PushReviewsResult>("/anki/push-reviews", { session_id: sessionId }),
  apkgUrl: (sessionId: number, deck: string) =>
    `/api/anki/apkg?session_id=${sessionId}&deck=${encodeURIComponent(deck)}`,
};
