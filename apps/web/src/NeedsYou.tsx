import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { respondDecision } from "./RunWorkflow";
import { useAgentRefresh } from "./remotea-refresh";
import { acceptAction, acceptLabel, KIND_LABELS, needsYouSummary, unavailableLine, type NeedsYou, type NeedsYouItem, type NeedsYouOpen } from "./needs-you-model";
import "./needs-you.css";

/** Everything waiting for the owner, as one list (needs_you.py). Each card says the decision, the recommendation,
 * the evidence and what accepting does; Open goes to where the item is decided, Accept answers it in one tap. */
export function NeedsYouPage({ refresh, onOpen }: { refresh: number; onOpen: (open: NeedsYouOpen) => void }) {
  const [value, setValue] = useState<NeedsYou | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api<NeedsYou>("/needs-you").then(v => { setValue(v); setError(""); }).catch(e => setError(e instanceof Error ? e.message : "Could not load."));
  }, []);
  useEffect(load, [load, refresh]);
  useAgentRefresh(load);
  useEffect(() => {
    const events = ["eri-context-changed", "eri-work-changed", "eri-voice-drafts-changed"];
    events.forEach(e => window.addEventListener(e, load));
    return () => events.forEach(e => window.removeEventListener(e, load));
  }, [load]);
  if (!value) return <section className="needs-you-page" aria-label="Needs you"><h2>Needs you</h2>
    {error ? <p role="alert" className="work-error">{error}</p> : <p role="status">Loading…</p>}</section>;
  const missing = unavailableLine(value.unavailable);
  return <section className="needs-you-page" aria-label="Needs you">
    <h2>Needs you</h2>
    <p className="needs-you-summary">{needsYouSummary(value)}</p>
    {missing && <p className="footnote" role="note">{missing}</p>}
    {error && <p role="alert" className="work-error">{error}</p>}
    {value.items.map(item => <NeedsYouCard key={item.key} item={item} onOpen={onOpen} onDone={load}/>)}
    {value.total > value.items.length && <p className="footnote">Showing the first {value.items.length} of {value.total}.</p>}
  </section>;
}

function NeedsYouCard({ item, onOpen, onDone }: { item: NeedsYouItem; onOpen: (open: NeedsYouOpen) => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const label = acceptLabel(item), action = acceptAction(item);
  const accept = async () => {
    if (!item.accept || !action) return;
    setBusy(true); setError("");
    try { await respondDecision(item.accept, action); onDone(); }
    catch (e) { setError(e instanceof Error ? e.message : "That did not go through."); }
    setBusy(false);
  };
  return <article className={item.urgent ? "needs-you-card urgent" : "needs-you-card"} aria-label={`${item.decision}: ${item.title}`}>
    <div className="needs-you-meta"><span className="chip">{KIND_LABELS[item.kind] ?? item.kind}</span>
      {item.urgent && <span className="chip needs-you-urgent">Blocking work</span>}</div>
    <h3>{item.decision}</h3>
    <p className="needs-you-title">{item.title}</p>
    {item.recommendation && <p><strong>Suggested:</strong> {item.recommendation}</p>}
    {item.evidence.length > 0 && <ul className="needs-you-evidence">{item.evidence.map((line, i) => <li key={i}>{line}</li>)}</ul>}
    {item.if_accepted && <p className="footnote"><strong>If you accept:</strong> {item.if_accepted}</p>}
    <div className="question-actions">
      {label && <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void accept()}>{label}</button>}
      {item.open && <button className={label ? "btn btn-ghost btn-sm" : "btn btn-primary btn-sm"} onClick={() => onOpen(item.open!)}>Open</button>}
    </div>
    {error && <p role="alert" className="work-error">{error}</p>}
  </article>;
}
