import { useCallback, useEffect, useRef, useState } from "react";
import * as context from "./context-api";
import { chosen, DESTINATION_LABELS, nextSelection, proposalGroup, selectable, type Destination, type Review } from "./context-model";

/** A meeting's open proposals, decided in place (Needs you): the same preselection, writes and stale handling as the
 * full meeting review (MeetingReview.tsx), without the transcript and context. `onSettled` runs after every write so
 * the list can drop the meeting once nothing is left open; `onOpen` goes to the full review. */
export function MeetingProposals({ sourceId, onSettled, onOpen }: { sourceId: string; onSettled: () => void; onOpen: () => void }) {
  const [review, setReview] = useState<Review | null>(null), [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const current = useRef<Review | null>(null);
  const apply = useCallback((next: Review) => {
    setSelected(previous => nextSelection(previous, current.current?.proposals ?? null, next.proposals));
    current.current = next; setReview(next);
  }, []);
  const load = useCallback(async () => {
    try { apply(await context.getReview(sourceId)); setError(""); } catch (e) { setError((e as Error).message); }
  }, [sourceId, apply]);
  useEffect(() => { void load(); }, [load]);

  async function act(run: () => Promise<context.WriteResult>, done: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await run();
      if (result.review) apply(result.review); else await load();
      setNotice(done); onSettled();
    } catch (e) {
      if (context.isStale(e)) { setError("This meeting changed, so nothing was saved. It has been reloaded; check it and try again."); await load(); }
      else setError((e as Error).message);
    } finally { setBusy(false); }
  }

  if (!review) return error ? <p role="alert" className="work-error">{error}</p> : <p role="status" className="footnote">Loading the proposals…</p>;
  const open = review.proposals.filter(selectable);
  const target: Destination = review.destination ?? "eridani";
  const toAdd = chosen(review.proposals, selected, "approvable"), toUpdate = chosen(review.proposals, selected, "updates");
  const toggle = (id: string, on: boolean) => setSelected(s => { const next = new Set(s); if (on) next.add(id); else next.delete(id); return next; });
  const rest = open.map(p => ({ proposal_id: p.id, revision: p.revision }));
  return <div className="needs-you-inline" role="group" aria-label="Proposals from this meeting">
    {!open.length && <p className="footnote">Nothing is left to decide here.</p>}
    {open.map(p => <label key={p.id} className="check-label needs-you-proposal">
      <input type="checkbox" checked={selected.has(p.id)} disabled={busy} onChange={e => toggle(p.id, e.target.checked)}
        aria-label={`${p.kind === "update" ? "Apply" : p.kind === "link" ? "Link" : "Add"}: ${p.title}`}/>
      <span><strong>{p.title}</strong>
        {proposalGroup(p) === "waiting" && <small> Someone else owes this; add it only to track it.</small>}
        {p.kind === "update" && <small> Changes an existing task.</small>}
        {p.reason && <small className="needs-you-reason">{p.reason}</small>}</span>
    </label>)}
    {!!open.length && <div className="question-actions">
      <button className="btn btn-primary btn-sm" disabled={busy || !toAdd.length}
        onClick={() => void act(() => context.approve(sourceId, target, toAdd), `Adding ${toAdd.length} to ${DESTINATION_LABELS[target]}.`)}>
        Add selected{toAdd.length ? ` (${toAdd.length})` : ""} to {DESTINATION_LABELS[target]}</button>
      {open.some(p => proposalGroup(p) === "updates") && <button className="btn btn-sm" disabled={busy || !toUpdate.length}
        onClick={() => void act(() => context.applyUpdates(sourceId, toUpdate), `Applying ${toUpdate.length} ${toUpdate.length === 1 ? "update" : "updates"}.`)}>
        Apply selected updates{toUpdate.length ? ` (${toUpdate.length})` : ""}</button>}
      <button className="btn btn-sm" disabled={busy || !!toAdd.length || !!toUpdate.length} title={toAdd.length || toUpdate.length ? "Add or clear the selected ones first" : undefined}
        onClick={() => void act(() => context.done(sourceId, review.revision, rest), "Review finished.")}>Dismiss the rest and finish</button>
      <button className="btn btn-ghost btn-sm" onClick={onOpen}>Full review</button>
    </div>}
    {notice && <p role="status" className="footnote">{notice}</p>}
    {error && <p role="alert" className="work-error">{error}</p>}
  </div>;
}
