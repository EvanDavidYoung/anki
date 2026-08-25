import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  AnkiStatus,
  ExportResult,
  PushReviewsResult,
  SessionDetail,
  StudyState,
} from "../types";

export default function AnkiView({
  session,
  anki,
  onRefreshAnki,
  onChanged,
}: {
  session: SessionDetail;
  anki: AnkiStatus | null;
  onRefreshAnki: () => void;
  onChanged: () => void | Promise<void>;
}) {
  const [deck, setDeck] = useState(anki?.default_deck ?? "QA");
  const [withAudio, setWithAudio] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [exported, setExported] = useState<ExportResult | null>(null);
  const [pushed, setPushed] = useState<PushReviewsResult | null>(null);
  const [study, setStudy] = useState<StudyState | null>(null);

  useEffect(() => {
    if (anki?.default_deck) setDeck((d) => d || anki.default_deck);
  }, [anki?.default_deck]);

  useEffect(() => {
    api.studyState(session.id).then(setStudy).catch(() => undefined);
  }, [session.id, pushed]);

  const approved = session.cards.filter((c) => c.status === "approved");
  const unexported = approved.filter((c) => !c.anki_note_id);
  const reachable = anki?.reachable ?? false;

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div>
      <div className="panel">
        <h2>Anki</h2>
        <div className="row" style={{ marginBottom: 12 }}>
          <span className={`dot ${reachable ? "on" : "off"}`} />
          <span>{reachable ? "AnkiConnect reachable" : "AnkiConnect not reachable"}</span>
          <button className="ghost small" onClick={onRefreshAnki}>
            Recheck
          </button>
        </div>
        {!reachable && (
          <div className="notice">
            Anki isn't running (or AnkiConnect isn't installed). You can still export a{" "}
            <strong>.apkg</strong> file below and import it by hand.
            {anki?.error ? <div className="small">{anki.error}</div> : null}
          </div>
        )}
        {error && <div className="error">{error}</div>}

        <div className="kv">
          <span className="muted">Approved cards in this session</span>
          <span>{approved.length}</span>
        </div>
        <div className="kv">
          <span className="muted">Not yet in Anki</span>
          <span>{unexported.length}</span>
        </div>
        <div className="kv">
          <span className="muted">Reviews waiting to push</span>
          <span>{study?.unpushed_reviews ?? 0}</span>
        </div>
      </div>

      <div className="panel">
        <h3>Export cards</h3>
        <div className="row" style={{ marginBottom: 12 }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <label htmlFor="deck">Deck</label>
            {reachable && anki!.decks.length > 0 ? (
              <select id="deck" value={deck} onChange={(e) => setDeck(e.target.value)}>
                {!anki!.decks.includes(deck) && <option value={deck}>{deck} (new)</option>}
                {anki!.decks.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            ) : (
              <input id="deck" value={deck} onChange={(e) => setDeck(e.target.value)} />
            )}
          </div>
          <label
            style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 18, width: "auto" }}
          >
            <input
              type="checkbox"
              checked={withAudio}
              style={{ width: "auto" }}
              onChange={(e) => setWithAudio(e.target.checked)}
            />
            Generate audio (TTS)
          </label>
        </div>

        <div className="row">
          <button
            className="primary"
            disabled={!reachable || unexported.length === 0 || busy !== ""}
            onClick={() =>
              run("export", async () => {
                setExported(await api.exportToAnki(session.id, deck, withAudio));
                await onChanged();
              })
            }
          >
            {busy === "export" ? <span className="spinner" /> : null} Push{" "}
            {unexported.length || ""} card{unexported.length === 1 ? "" : "s"} to Anki
          </button>
          <a href={api.apkgUrl(session.id, deck)} download>
            <button disabled={approved.length === 0}>Export .apkg</button>
          </a>
        </div>

        {exported && (
          <div className="notice" style={{ marginTop: 12 }}>
            Added {exported.added} note{exported.added === 1 ? "" : "s"} to{" "}
            <strong>{exported.deck}</strong>
            {exported.duplicates ? `, skipped ${exported.duplicates} duplicate(s)` : ""}
            {exported.errors ? `, ${exported.errors} error(s)` : ""}.
          </div>
        )}
        <div className="small muted" style={{ marginTop: 10 }}>
          .apkg export always works, but importing it creates a separate copy of the
          "Chinese Learning Model" note type. Pushing over AnkiConnect is the lossless path.
        </div>
      </div>

      <div className="panel">
        <h3>Push study progress</h3>
        <p className="muted small">
          Sends your in-app answers to Anki as real reviews. Anki only accepts an answer for a
          card that is currently due, so anything not due stays queued for a later push.
        </p>
        <button
          disabled={!reachable || !study?.unpushed_reviews || busy !== ""}
          onClick={() =>
            run("push", async () => {
              setPushed(await api.pushReviews(session.id));
            })
          }
        >
          {busy === "push" ? <span className="spinner" /> : null} Push{" "}
          {study?.unpushed_reviews ?? 0} review{study?.unpushed_reviews === 1 ? "" : "s"} to Anki
        </button>

        {pushed && (
          <>
            <div className="notice" style={{ marginTop: 12 }}>
              Pushed {pushed.pushed} of {pushed.attempted}
              {pushed.attempted - pushed.pushed > 0
                ? ` — ${pushed.attempted - pushed.pushed} weren't due in Anki and stay queued.`
                : "."}
            </div>
            <div className="result-list">
              {pushed.results.map((r) => (
                <div key={r.card_id} className="result-row">
                  <span className={`dot ${r.pushed ? "on" : "off"}`} />
                  <span className="han">{r.traditional}</span>
                  <span className="muted">ease {r.ease}</span>
                  <span className="spacer" />
                  <span className="muted">{r.pushed ? "pushed" : r.reason}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
