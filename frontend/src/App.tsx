import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { AnkiStatus, SessionDetail, SessionSummary } from "./types";
import AnkiView from "./views/AnkiView";
import CardsView from "./views/CardsView";
import InputView from "./views/InputView";
import QuizView from "./views/QuizView";
import StudyView from "./views/StudyView";

type Tab = "input" | "cards" | "quiz" | "study" | "anki";

const TABS: { id: Tab; label: string }[] = [
  { id: "input", label: "Text" },
  { id: "cards", label: "Cards" },
  { id: "quiz", label: "Quiz" },
  { id: "study", label: "Study" },
  { id: "anki", label: "Anki" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("input");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [anki, setAnki] = useState<AnkiStatus | null>(null);

  const refreshSessions = useCallback(async () => {
    setSessions(await api.listSessions());
  }, []);

  const refreshSession = useCallback(async (id: number) => {
    setSession(await api.getSession(id));
  }, []);

  useEffect(() => {
    refreshSessions().catch(() => undefined);
    api.ankiStatus().then(setAnki).catch(() => undefined);

    // ?session=N deep-links straight to a review queue, which is how agents
    // (and the MCP server) hand a staged session off to a human.
    const wanted = Number(new URLSearchParams(window.location.search).get("session"));
    if (wanted) {
      api
        .getSession(wanted)
        .then((detail) => {
          setSession(detail);
          setTab("cards");
        })
        .catch(() => undefined);
    }
  }, [refreshSessions]);

  const onCreated = async (detail: SessionDetail) => {
    setSession(detail);
    await refreshSessions();
    setTab("cards");
  };

  const selectSession = async (id: number) => {
    if (!id) {
      setSession(null);
      return;
    }
    await refreshSession(id);
  };

  const hasSession = session !== null;

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">中文 Vocab</span>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? "active" : ""}`}
              disabled={t.id !== "input" && !hasSession}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <span className="spacer" />
        {sessions.length > 0 && (
          <div className="session-picker">
            <select
              value={session?.id ?? ""}
              onChange={(e) => selectSession(Number(e.target.value))}
            >
              <option value="">— pick a session —</option>
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title} ({s.approved_count}/{s.card_count})
                </option>
              ))}
            </select>
          </div>
        )}
        <span className="small muted" title={anki?.error || ""}>
          <span className={`dot ${anki ? (anki.reachable ? "on" : "off") : ""}`} />{" "}
          {anki ? (anki.reachable ? "Anki connected" : "Anki offline") : "checking…"}
        </span>
      </header>

      {tab === "input" && <InputView onCreated={onCreated} />}
      {tab === "cards" && session && (
        <CardsView session={session} onChanged={() => refreshSession(session.id)} />
      )}
      {tab === "quiz" && session && <QuizView session={session} />}
      {tab === "study" && session && <StudyView session={session} />}
      {tab === "anki" && session && (
        <AnkiView
          session={session}
          anki={anki}
          onRefreshAnki={() => api.ankiStatus().then(setAnki).catch(() => undefined)}
          onChanged={() => refreshSession(session.id)}
        />
      )}
    </div>
  );
}
