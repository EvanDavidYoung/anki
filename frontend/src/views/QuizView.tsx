import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AnswerResult, Question, SessionDetail } from "../types";

const LETTERS = ["A", "B", "C", "D"];

export default function QuizView({ session }: { session: SessionDetail }) {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [index, setIndex] = useState(0);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [chosen, setChosen] = useState<number | null>(null);
  const [score, setScore] = useState({ correct: 0, answered: 0 });
  const [missed, setMissed] = useState<Question[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [size, setSize] = useState(8);

  useEffect(() => {
    api
      .getQuiz(session.id)
      .then((qs) => {
        setQuestions(qs);
        reset(qs);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id]);

  const reset = (qs: Question[]) => {
    setQuestions(qs);
    setIndex(0);
    setResult(null);
    setChosen(null);
    setScore({ correct: 0, answered: 0 });
    setMissed([]);
  };

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      reset(await api.createQuiz(session.id, size));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const question = questions[index];

  const choose = useCallback(
    async (i: number) => {
      if (!question || result) return;
      setChosen(i);
      try {
        const res = await api.answerQuestion(question.id, i);
        setResult(res);
        setScore((s) => ({ correct: s.correct + (res.correct ? 1 : 0), answered: s.answered + 1 }));
        if (!res.correct) setMissed((m) => [...m, question]);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setChosen(null);
      }
    },
    [question, result],
  );

  const next = useCallback(() => {
    setResult(null);
    setChosen(null);
    setIndex((i) => i + 1);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (result && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        next();
      } else if (!result && ["1", "2", "3", "4"].includes(e.key)) {
        e.preventDefault();
        choose(Number(e.key) - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [choose, next, result]);

  if (questions.length === 0) {
    return (
      <div className="panel">
        <h2>Quiz</h2>
        {error && <div className="error">{error}</div>}
        <p className="muted">
          Generate a multiple-choice quiz from this session's vocabulary and source text.
          Approved cards are used if you've approved any, otherwise everything not rejected.
        </p>
        <div className="row">
          <label htmlFor="size" style={{ margin: 0 }}>
            Questions
          </label>
          <input
            id="size"
            type="number"
            min={1}
            max={25}
            value={size}
            style={{ width: 80 }}
            onChange={(e) => setSize(Number(e.target.value))}
          />
          <button className="primary" disabled={busy} onClick={generate}>
            {busy ? <span className="spinner" /> : null} {busy ? "Writing quiz…" : "Generate quiz"}
          </button>
        </div>
      </div>
    );
  }

  if (!question) {
    const pct = score.answered ? Math.round((score.correct / score.answered) * 100) : 0;
    return (
      <div className="panel">
        <h2>
          Quiz complete — {score.correct}/{score.answered} ({pct}%)
        </h2>
        {missed.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <h3>Missed</h3>
            {missed.map((q) => (
              <div key={q.id} className="small muted" style={{ padding: "3px 0" }}>
                {q.prompt}
              </div>
            ))}
          </div>
        )}
        <div className="row">
          {missed.length > 0 && (
            <button
              onClick={() => {
                const retry = missed;
                reset(retry);
              }}
            >
              Retry {missed.length} missed
            </button>
          )}
          <button className="primary" disabled={busy} onClick={generate}>
            New quiz
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="progress">
        <div style={{ width: `${(index / questions.length) * 100}%` }} />
      </div>
      <div className="row small muted" style={{ marginBottom: 12 }}>
        <span>
          Question {index + 1} of {questions.length}
        </span>
        <span className="spacer" />
        <span>
          {score.correct}/{score.answered} correct
        </span>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="question">{question.prompt}</div>
      <div className="choices">
        {question.choices.map((choice, i) => {
          let cls = "choice";
          if (result) {
            if (i === result.answer_index) cls += " correct";
            else if (i === chosen) cls += " wrong";
          }
          return (
            <button key={i} className={cls} disabled={!!result} onClick={() => choose(i)}>
              <span className="key">{LETTERS[i]}</span>
              <span>{choice}</span>
            </button>
          );
        })}
      </div>

      {result && (
        <div style={{ marginTop: 16 }}>
          <div className={result.correct ? "" : "error"} style={{ marginBottom: 10 }}>
            <strong style={{ color: result.correct ? "var(--green)" : undefined }}>
              {result.correct ? "Correct" : "Not quite"}
            </strong>
            {result.explanation ? ` — ${result.explanation}` : ""}
          </div>
          <button className="primary" onClick={next}>
            Next <kbd>↵</kbd>
          </button>
        </div>
      )}
      {!result && (
        <div className="small muted" style={{ marginTop: 12 }}>
          Press <kbd>1</kbd>–<kbd>4</kbd> to answer.
        </div>
      )}
    </div>
  );
}
