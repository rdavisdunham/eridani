import { useEffect, useId, useRef, useState } from "react";
import { CircleCheck, Ellipsis, ListChecks, ListPlus, Pin, PinOff } from "lucide-react";
import { ApiError } from "./api";
import { doLabel } from "./date-picks";
import { heldFocus } from "./list-finish";
import { QuickListBody, isOpenItem, parseChecklist, useQuickList, type FinishedList } from "./QuickLists";
import { useStructureActions } from "./structure-actions";
import type { QuickList, TodayBoxData } from "./types";
import { Popover } from "./ux";
import { shortDate } from "./work-views";
import "./today.css";

type BoxActions = {
  /** Opens the whole list in its dialog. */
  onOpen: (list: QuickList) => void;
  /** A pin changed or a list was started: Today reads its boxes again. */
  onChanged: () => void;
  /** A list finished from its box. `undo` sends the command that brings it back. */
  onFinished: (finished: FinishedList) => void;
};

function dateLabel(date: string, list: QuickList, today: string) {
  if (date !== list.due_date) return doLabel(date, today);
  const day = shortDate(date, today);
  return "Due " + (["Today", "Tomorrow", "Yesterday"].includes(day) ? day.toLowerCase() : day);
}

/** One quick list on Today: its open items, an add field, the checked items folded into "N done", and a menu. */
export function TodayBox({ box, today, canEdit, focusAdd = false, onOpen, onChanged, onFinished }: BoxActions & {
  box: TodayBoxData; today: string; canEdit: boolean;
  /** A list just started here: bring the box into view with its add field focused. */
  focusAdd?: boolean;
}) {
  const heading = useId(), panel = useRef<HTMLElement>(null), field = useRef<HTMLInputElement | null>(null);
  // A finished list's box leaves Today; when it held focus, the toast's Undo takes it.
  const quick = useQuickList(box.target_id, { snapshot: box.list, remember: true, onFinished: finished => onFinished({ ...finished, focus: heldFocus(panel.current) }) });
  const list = quick.list ?? box.list;
  const [confirm, setConfirm] = useState<number | null>(null), [pinning, setPinning] = useState(false);
  const open = list.items.filter(isOpenItem).length;
  useEffect(() => {
    if (!focusAdd) return;
    field.current?.focus();
    panel.current?.scrollIntoView?.({ block: "nearest" });
  }, [focusAdd]);
  const finish = (consent: boolean) => {
    setConfirm(null);
    void quick.finish(consent).catch(e => {
      // Items arrived since this box was read: ask first, with the server's count.
      if (!(e instanceof ApiError) || e.code !== "LIST_HAS_OPEN_ITEMS") return;
      quick.setError("");
      setConfirm((e.data as { open_count?: number } | undefined)?.open_count ?? open);
    });
  };
  const cancel = () => { setConfirm(null); panel.current?.querySelector<HTMLButtonElement>(".panel-action > button")?.focus(); };
  const pin = () => { setPinning(true); void quick.pin(!box.pinned).then(onChanged, () => {}).finally(() => setPinning(false)); };
  return <section ref={panel} className="panel today-box" aria-labelledby={heading}>
    <header className="panel-header">
      <h2 id={heading}>{list.title}</h2>
      {!!open && <span className="panel-count">{open}</span>}
      {/* A box here because of its date has no pin to remove; it shows the date instead. */}
      {box.reason === "dated" && box.date && <span className="chip box-date">{dateLabel(box.date, list, today)}</span>}
      <Popover floating label={"Options for " + list.title} className="panel-action" panelClassName="menu-popover"
        buttonClassName="btn btn-ghost btn-sm btn-icon" button={<Ellipsis size={18} aria-hidden="true" />}>
        {close => <div className="menu-list">
          <button type="button" className="menu-item" disabled={pinning} onClick={() => { close(); pin(); }}>
            {box.pinned ? <><PinOff size={16} aria-hidden="true" />Unpin from Today</> : <><Pin size={16} aria-hidden="true" />Pin to Today</>}
          </button>
          <button type="button" className="menu-item" onClick={() => { close(); onOpen(list); }}><ListChecks size={16} aria-hidden="true" />Open full list</button>
          {canEdit && <button type="button" className="menu-item" onClick={() => { close(); if (open) setConfirm(open); else finish(false); }}>
            <CircleCheck size={16} aria-hidden="true" />Finish list</button>}
        </div>}
      </Popover>
    </header>
    {confirm !== null && <div className="box-confirm" role="group" aria-label="Finish this list?"
      onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); cancel(); } }}>
      <p>{confirm === 1 ? "1 item isn't checked." : confirm + " items aren't checked."} Finish the whole list?</p>
      <div className="box-confirm-actions">
        <button type="button" className="btn btn-primary btn-sm" autoFocus onClick={() => finish(true)}>Finish list</button>
        <button type="button" className="btn btn-sm" onClick={cancel}>Cancel</button>
      </div>
    </div>}
    <QuickListBody compact quick={quick} canEdit={canEdit} label={list.title} addRef={field} />
  </section>;
}

/** The title-and-items form that starts a list right on Today. An empty list is fine; it holds up to 100 items. */
function StartList({ onStarted }: { onStarted: (list: QuickList) => void }) {
  const [open, setOpen] = useState(false), [title, setTitle] = useState(""), [text, setText] = useState("");
  const { run, busy, error, setError } = useStructureActions();
  const heading = useId(), launcher = useRef<HTMLButtonElement>(null), returning = useRef(false);
  useEffect(() => { if (!open && returning.current) { returning.current = false; launcher.current?.focus(); } }, [open]);
  const reset = () => { setOpen(false); setTitle(""); setText(""); setError(""); };
  const cancel = () => { if (busy) return; returning.current = true; reset(); };
  const items = parseChecklist(text);
  if (!open) return <button ref={launcher} type="button" className="btn btn-soft today-start" onClick={() => setOpen(true)}>
    <ListPlus size={16} aria-hidden="true" />Start a list</button>;
  return <form className="panel today-start-form" aria-labelledby={heading}
    onKeyDown={e => { if (e.key === "Escape") { e.preventDefault(); cancel(); } }}
    onSubmit={e => {
      e.preventDefault();
      // Started on Today, so it is pinned to Today.
      void run<QuickList>("quicklist.create", { title: title.trim(), items, pinned: true }).then(list => { reset(); onStarted(list); }).catch(() => {});
    }}>
    <h2 id={heading}>Start a list</h2>
    <label className="field">List title<input aria-label="List title" autoFocus required maxLength={500} value={title} onChange={e => setTitle(e.target.value)} /></label>
    <label className="field">Items<textarea aria-label="Items" rows={4} value={text} onChange={e => setText(e.target.value)} placeholder={"One item per line\n# A heading starts a section"} /></label>
    {items.length > 100 && <p className="field-error">A list holds up to 100 items.</p>}
    {error && <p className="today-error" role="alert">{error}</p>}
    <div className="today-start-actions">
      <button className="btn btn-primary btn-sm" disabled={busy || !title.trim() || items.length > 100}>Start list</button>
      <button type="button" className="btn btn-sm" disabled={busy} onClick={cancel}>Cancel</button>
    </div>
  </form>;
}

/**
 * Today's boxes in order, then the control that starts a new list. A list started here shows at once, before
 * Today's next read of its boxes includes it.
 */
export function TodayBoxes({ boxes, today, canEdit, onOpen, onChanged, onFinished }: BoxActions & {
  boxes: TodayBoxData[] | null; today: string; canEdit: boolean;
}) {
  const [started, setStarted] = useState<QuickList[]>([]), [focus, setFocus] = useState<string | null>(null);
  const read = boxes ?? [], known = new Set(read.map(box => box.target_id));
  useEffect(() => { setStarted(lists => lists.filter(list => !known.has(list.id))); }, [boxes]);
  const drop = (id: string) => setStarted(lists => lists.filter(list => list.id !== id));
  const shown = [...read, ...started.filter(list => !known.has(list.id))
    .map((list): TodayBoxData => ({ kind: "quick_list", target_id: list.id, reason: "pinned", pinned: true, date: null, list }))];
  return <>
    {shown.map(box => <TodayBox key={box.target_id} box={box} today={today} canEdit={canEdit} focusAdd={focus === box.target_id} onOpen={onOpen}
      onChanged={() => { drop(box.target_id); onChanged(); }} onFinished={finished => { drop(box.target_id); onFinished(finished); }} />)}
    {canEdit && <StartList onStarted={list => {
      if (list.pinned !== false) { setStarted(lists => [...lists, list]); setFocus(list.id); }
      onChanged();
    }} />}
  </>;
}
