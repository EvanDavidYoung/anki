import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { EDITABLE_FIELDS, type Card, type EditableField, type SessionDetail } from "../types";

export default function CardsView({
  session,
  onChanged,
}: {
  session: SessionDetail;
  onChanged: () => void | Promise<void>;
}) {
  const [selected, setSelected] = useState(0);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const cards = session.cards;
  const refs = useRef<(HTMLDivElement | null)[]>([]);

  const run = async (fn: () => Promise<unknown>) => {
    setError("");
    try {
      await fn();
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const setStatus = (card: Card, action: "approve" | "reject" | "reset") =>
    run(() => api.setCardStatus(card.id, action));

  // Keyboard review: j/k to move, a/r to decide, e to edit.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (editingId !== null) return;
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const card = cards[selected];
      if (e.key === "j" || e.key === "ArrowDown") {
        setSelected((i) => Math.min(i + 1, cards.length - 1));
      } else if (e.key === "k" || e.key === "ArrowUp") {
        setSelected((i) => Math.max(i - 1, 0));
      } else if (card && e.key === "a") {
        setStatus(card, "approve");
        setSelected((i) => Math.min(i + 1, cards.length - 1));
      } else if (card && e.key === "r") {
        setStatus(card, "reject");
        setSelected((i) => Math.min(i + 1, cards.length - 1));
      } else if (card && e.key === "e") {
        e.preventDefault();
        setEditingId(card.id);
      } else {
        return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cards, selected, editingId]);

  useEffect(() => {
    refs.current[selected]?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const counts = {
    pending: cards.filter((c) => c.status === "pending").length,
    approved: cards.filter((c) => c.status === "approved").length,
    rejected: cards.filter((c) => c.status === "rejected").length,
  };

  return (
    <div>
      <div className="card-toolbar">
        <strong>{session.title}</strong>
        <span className="pill pending">{counts.pending} pending</span>
        <span className="pill approved">{counts.approved} approved</span>
        <span className="pill rejected">{counts.rejected} rejected</span>
        <span className="spacer" />
        <button
          disabled={counts.pending === 0}
          onClick={() => run(() => api.bulkStatus(session.id, "approved"))}
        >
          Approve all pending
        </button>
        <span className="muted small">
          <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>a</kbd> approve · <kbd>r</kbd> reject ·{" "}
          <kbd>e</kbd> edit
        </span>
      </div>

      {error && <div className="error">{error}</div>}
      {cards.length === 0 && <div className="empty">This session has no cards.</div>}

      {cards.map((card, i) => (
        <div
          key={card.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          className={`vocab-card ${card.status} ${i === selected ? "selected" : ""}`}
          onClick={() => setSelected(i)}
        >
          {editingId === card.id ? (
            <CardEditor
              card={card}
              onCancel={() => setEditingId(null)}
              onSave={async (patch) => {
                await run(() => api.updateCard(card.id, patch));
                setEditingId(null);
              }}
            />
          ) : (
            <>
              <div className="head">
                <span className="hanzi">{card.traditional}</span>
                <span className="pinyin">{card.pinyin}</span>
                <span className="pos">{card.part_of_speech}</span>
                <span className="spacer" />
                <span className={`pill ${card.status}`}>{card.status}</span>
                {card.anki_note_id && <span className="pill">in Anki</span>}
              </div>
              <div className="meaning">{card.meaning}</div>
              {card.sentence_traditional && (
                <>
                  <div className="sentence">{card.sentence_traditional}</div>
                  <div className="sentence-sub">{card.sentence_pinyin}</div>
                  <div className="sentence-sub">{card.sentence_meaning}</div>
                </>
              )}
              <div className="card-actions">
                <button
                  className="good"
                  disabled={card.status === "approved"}
                  onClick={() => setStatus(card, "approve")}
                >
                  Approve
                </button>
                <button
                  className="bad"
                  disabled={card.status === "rejected"}
                  onClick={() => setStatus(card, "reject")}
                >
                  Reject
                </button>
                <button className="ghost" onClick={() => setEditingId(card.id)}>
                  Edit
                </button>
                {card.status !== "pending" && (
                  <button className="ghost" onClick={() => setStatus(card, "reset")}>
                    Undo
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function CardEditor({
  card,
  onSave,
  onCancel,
}: {
  card: Card;
  onSave: (patch: Partial<Card>) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Record<EditableField, string>>(() =>
    Object.fromEntries(EDITABLE_FIELDS.map(([f]) => [f, card[f]])) as Record<EditableField, string>,
  );

  return (
    <div>
      <div className="edit-grid">
        {EDITABLE_FIELDS.map(([field, label]) => (
          <div key={field} className={field.startsWith("sentence") ? "full" : ""}>
            <label htmlFor={`${card.id}-${field}`}>{label}</label>
            <input
              id={`${card.id}-${field}`}
              value={draft[field]}
              style={field.includes("traditional") ? { fontFamily: "var(--han)" } : undefined}
              onChange={(e) => setDraft({ ...draft, [field]: e.target.value })}
            />
          </div>
        ))}
      </div>
      <div className="card-actions">
        <button className="primary" onClick={() => onSave(draft)}>
          Save
        </button>
        <button className="ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
