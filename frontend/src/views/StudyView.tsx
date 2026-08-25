import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { SessionDetail, StudyCard, StudyState } from "../types";

const GRADES = [
  { ease: 1, label: "Again", sub: "<1m" },
  { ease: 2, label: "Hard", sub: "~6m" },
  { ease: 3, label: "Good", sub: "1d+" },
  { ease: 4, label: "Easy", sub: "4d+" },
];

export default function StudyView({ session }: { session: SessionDetail }) {
  const [current, setCurrent] = useState<StudyCard | null>(null);
  const [state, setState] = useState<StudyState | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [done, setDone] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [card, st] = await Promise.all([
        api.nextStudyCard(session.id),
        api.studyState(session.id),
      ]);
      setCurrent(card);
      setState(st);
      setRevealed(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [session.id]);

  useEffect(() => {
    load();
  }, [load]);

  const grade = useCallback(
    async (ease: number) => {
      if (!current) return;
      setError("");
      try {
        await api.answerStudy(current.card.id, ease);
        setDone((d) => d + 1);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [current, load],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (!current) return;
      if (!revealed && (e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        setRevealed(true);
      } else if (revealed && ["1", "2", "3", "4"].includes(e.key)) {
        e.preventDefault();
        grade(Number(e.key));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, revealed, grade]);

  if (loading && !current) return <div className="panel empty">Loading…</div>;

  if (!current) {
    return (
      <div className="panel">
        <h2>Study</h2>
        {error && <div className="error">{error}</div>}
        {state && state.total === 0 ? (
          <div className="empty">
            Nothing to study yet — approve some cards on the Cards tab first.
          </div>
        ) : (
          <div className="empty">
            Nothing due right now. {done > 0 && `You reviewed ${done} card${done === 1 ? "" : "s"}.`}
            <div className="small" style={{ marginTop: 10 }}>
              {state?.unpushed_reviews ? (
                <>
                  {state.unpushed_reviews} review{state.unpushed_reviews === 1 ? "" : "s"} waiting to
                  be pushed to Anki — see the Anki tab.
                </>
              ) : null}
            </div>
          </div>
        )}
        <div className="row">
          <button onClick={load}>Refresh</button>
        </div>
      </div>
    );
  }

  const card = current.card;
  return (
    <div>
      <div className="row small muted" style={{ marginBottom: 10 }}>
        <span>{current.due_count} due</span>
        <span>·</span>
        <span>{current.new_count} new</span>
        <span>·</span>
        <span>{done} done this session</span>
        <span className="spacer" />
        <span>
          {current.reps === 0
            ? "new card"
            : `rep ${current.reps} · ${current.interval_days.toFixed(current.interval_days < 1 ? 2 : 0)}d`}
        </span>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="panel study-card">
        <div className="hanzi">{card.traditional}</div>
        {!revealed && card.sentence_traditional && (
          <div className="sentence muted" style={{ marginTop: 24 }}>
            {card.sentence_traditional}
          </div>
        )}

        {revealed ? (
          <div className="study-answer">
            <div className="pinyin" style={{ fontSize: 22 }}>
              {card.pinyin}
            </div>
            <div className="meaning" style={{ fontSize: 19 }}>
              {card.meaning} <span className="pos">{card.part_of_speech}</span>
            </div>
            {card.sentence_traditional && (
              <>
                <div className="sentence">{card.sentence_traditional}</div>
                <div className="sentence-sub">{card.sentence_pinyin}</div>
                <div className="sentence-sub">{card.sentence_meaning}</div>
              </>
            )}
          </div>
        ) : (
          <div style={{ marginTop: 30 }}>
            <button className="primary" onClick={() => setRevealed(true)}>
              Show answer <kbd>space</kbd>
            </button>
          </div>
        )}
      </div>

      {revealed && (
        <div className="grades">
          {GRADES.map((g) => (
            <button key={g.ease} onClick={() => grade(g.ease)}>
              <span>
                {g.label} <kbd>{g.ease}</kbd>
              </span>
              <span className="sub">{g.sub}</span>
            </button>
          ))}
        </div>
      )}

      <div className="small muted" style={{ marginTop: 14 }}>
        Progress is stored locally. Push it to Anki as real reviews from the Anki tab.
      </div>
    </div>
  );
}
