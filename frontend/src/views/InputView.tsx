import { useState } from "react";
import { api } from "../api";
import type { SessionDetail } from "../types";

const SAMPLE = `台灣的夜市文化已經有超過一百年的歷史。每到傍晚，攤販陸續擺出攤位，遊客絡繹不絕。`;

export default function InputView({
  onCreated,
}: {
  onCreated: (session: SessionDetail) => void;
}) {
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      onCreated(await api.createSession(text, title));
      setText("");
      setTitle("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>Paste Chinese text</h2>
      {error && <div className="error">{error}</div>}

      <div style={{ marginBottom: 12 }}>
        <label htmlFor="title">Title (optional)</label>
        <input
          id="title"
          value={title}
          placeholder="e.g. 夜市文化 article"
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>

      <label htmlFor="text">Text</label>
      <textarea
        id="text"
        rows={14}
        value={text}
        placeholder="貼上一段中文…"
        style={{ fontFamily: "var(--han)", fontSize: 17 }}
        onChange={(e) => setText(e.target.value)}
      />

      <div className="row" style={{ marginTop: 14 }}>
        <button className="primary" disabled={busy || !text.trim()} onClick={submit}>
          {busy ? <span className="spinner" /> : null} {busy ? "Generating…" : "Generate vocab list"}
        </button>
        <button className="ghost" disabled={busy} onClick={() => setText(SAMPLE)}>
          Use sample text
        </button>
        <span className="muted small">
          The model extracts 5–15 words with pinyin, meaning and an example sentence.
        </span>
      </div>
    </div>
  );
}
