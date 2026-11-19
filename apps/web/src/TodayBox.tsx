import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { CircleCheck, Ellipsis, FolderKanban, FolderOpen, ListChecks, ListPlus, Pin, PinOff } from "lucide-react";
import { ApiError } from "./api";
import { doLabel } from "./date-picks";
import { heldFocus, listRefusal, uncheckedCount } from "./list-finish";
import { QuickListBody, isOpenItem, parseChecklist, useQuickList, type FinishedList } from "./QuickLists";
import { useStructureActions } from "./structure-actions";
import { live } from "./today-counts";
import { pinToToday } from "./today-pins";
import type { ProjectBoxData, QuickList, QuickListBoxData, Task, TodayBoxData } from "./types";
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
  box: QuickListBoxData; today: string; canEdit: boolean;
  /** A list just started here: bring the box into view with its add field focused. */
  focusAdd?: boolean;
}) {
  const heading = useId(), panel = useRef<HTMLElement>(null), title = useRef<HTMLHeadingElement>(null), field = useRef<HTMLInputElement | null>(null);
  // A finished list's box leaves Today; when it held focus, the toast's Undo takes it.
  const quick = useQuickList(box.target_id, { snapshot: box.list, remember: true, onFinished: finished => onFinished({ ...finished, focus: heldFocus(panel.current) }) });
  const list = quick.list ?? box.list;
  // The unchecked items the question names: consent to finish the list covers these and no others.
  const [confirm, setConfirm] = useState<{ count: number; ids: string[] } | null>(null), [pinning, setPinning] = useState(false);
  const openIds = list.items.filter(isOpenItem).map(item => item.id), open = openIds.length;
  useEffect(() => {
    if (!focusAdd) return;
    field.current?.focus();
    panel.current?.scrollIntoView?.({ block: "nearest" });
  }, [focusAdd]);
  const finish = (ids?: string[]) => {
    setConfirm(null);
    void quick.finish(ids).catch(e => {
      // Unchecked items the box did not show (added elsewhere): ask first, with the server's count.
      const refusal = listRefusal(e);
      if (refusal) {
        quick.setError("");
        setConfirm({ count: refusal.open_count, ids: refusal.open_item_ids ?? openIds });
        return;
      }
      // The list changed while the person was asked: read it again and ask about what it holds now.
      if (!ids || !(e instanceof ApiError) || e.code !== "REVISION_CONFLICT") return;
      void quick.load().then(fresh => {
        const now = fresh.items.filter(isOpenItem).map(item => item.id);
        if (!now.length) return;
        quick.setError("");
        setConfirm({ count: now.length, ids: now });
      }, () => {});
    });
  };
  const cancel = () => { setConfirm(null); panel.current?.querySelector<HTMLButtonElement>(".panel-action > button")?.focus(); };
  const pin = () => { setPinning(true); void quick.pin(!box.pinned).then(onChanged, () => {}).finally(() => setPinning(false)); };
  return <section ref={panel} className="panel today-box" aria-labelledby={heading}>
    <header className="panel-header">
      <h2 id={heading} ref={title} tabIndex={-1}>{list.title}</h2>
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
          {canEdit && <button type="button" className="menu-item" onClick={() => { close(); if (open) setConfirm({ count: open, ids: openIds }); else finish(); }}>
            <CircleCheck size={16} aria-hidden="true" />Finish list</button>}
        </div>}
      </Popover>
    </header>
    {confirm !== null && <div className="box-confirm" role="group" aria-label="Finish this list?"
      onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); cancel(); } }}>
      <p>{uncheckedCount(confirm.count)} Finish the whole list?</p>
      <div className="box-confirm-actions">
        <button type="button" className="btn btn-primary btn-sm" autoFocus onClick={() => finish(confirm.ids)}>Finish list</button>
        <button type="button" className="btn btn-sm" onClick={cancel}>Cancel</button>
      </div>
    </div>}
    <QuickListBody compact quick={quick} canEdit={canEdit} label={list.title} addRef={field} boxRef={title} />
  </section>;
}

type ProjectActions = {
  /** One of a project's tasks as a Today row, the same row Due and overdue shows. */
  row: (task: Task) => ReactNode;
  /** The workspace's current tasks: a task checked or changed since the boxes were read shows that way at once. */
  tasks: Task[];
  /** Opens the project in Organize. */
  onOpenProject: (id: string) => void;
};

/** A project kept on Today: its open tasks due or planned by today, and a field that adds one for today. */
export function ProjectBox({ box, today, canEdit, row, tasks, onOpenProject, onChanged }: ProjectActions & {
  box: ProjectBoxData; today: string; canEdit: boolean; onChanged: () => void;
}) {
  const heading = useId();
  const [title, setTitle] = useState(""), [pinning, setPinning] = useState(false), [pinError, setPinError] = useState("");
  const { run, busy, error } = useStructureActions();
  const current = useMemo(() => new Map(tasks.map(task => [task.id, task])), [tasks]);
  // The workspace's copy wins, so a task checked here or in Due and overdue leaves both at once.
  const shown = box.tasks.map(task => current.get(task.id) ?? task).filter(live);
  const more = box.total - box.tasks.length, count = shown.length + more;
  const open = () => onOpenProject(box.target_id);
  const unpin = () => {
    setPinning(true); setPinError("");
    void pinToToday(box.target_id, false).then(onChanged, e => setPinError((e as Error).message)).finally(() => setPinning(false));
  };
  const add = (e: FormEvent) => {
    e.preventDefault();
    const text = title.trim();
    if (!text || !box.add) return;
    void run("task.create", { title: text, ...box.add, planned_date: today }).then(() => { setTitle(""); onChanged(); }, () => {});
  };
  return <section className="panel today-box" aria-labelledby={heading}>
    <header className="panel-header">
      <h2 id={heading}><button type="button" className="box-link" onClick={open}><FolderKanban aria-hidden="true" />{box.title}</button></h2>
      {!!count && <span className="panel-count">{count}</span>}
      <Popover floating label={"Options for " + box.title} className="panel-action" panelClassName="menu-popover"
        buttonClassName="btn btn-ghost btn-sm btn-icon" button={<Ellipsis size={18} aria-hidden="true" />}>
        {close => <div className="menu-list">
          <button type="button" className="menu-item" disabled={pinning} onClick={() => { close(); unpin(); }}><PinOff size={16} aria-hidden="true" />Unpin from Today</button>
          <button type="button" className="menu-item" onClick={() => { close(); open(); }}><FolderOpen size={16} aria-hidden="true" />Open project</button>
        </div>}
      </Popover>
    </header>
    {(error || pinError) && <p className="today-error" role="alert">{error || pinError}</p>}
    {shown.length ? <ul className="today-rows">{shown.map(task => row(task))}</ul> : <p className="box-state">Nothing due today.</p>}
    {more > 0 && <button type="button" className="btn btn-ghost btn-sm box-more" onClick={open}>{more} more in {box.title}</button>}
    {canEdit && box.add && <form className="box-add" onSubmit={add}>
      <input aria-label={"Add to " + box.title} placeholder="Add a task for today…" maxLength={500} value={title} onChange={e => setTitle(e.target.value)} />
      <button className="btn btn-soft btn-sm" disabled={busy || !title.trim()}>Add</button>
    </form>}
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
 * Today's boxes in order, quick lists and projects, then the control that starts a new list. A list started here
 * shows at once, before Today's next read of its boxes includes it.
 */
export function TodayBoxes({ boxes, today, canEdit, onOpen, onChanged, onFinished, ...project }: BoxActions & ProjectActions & {
  boxes: TodayBoxData[] | null; today: string; canEdit: boolean;
}) {
  const [started, setStarted] = useState<QuickList[]>([]), [focus, setFocus] = useState<string | null>(null);
  const read = boxes ?? [], known = new Set(read.map(box => box.target_id));
  useEffect(() => { setStarted(lists => lists.some(list => known.has(list.id)) ? lists.filter(list => !known.has(list.id)) : lists); }, [boxes]);
  const drop = (id: string) => setStarted(lists => lists.filter(list => list.id !== id));
  const shown = [...read, ...started.filter(list => !known.has(list.id))
    .map((list): TodayBoxData => ({ kind: "quick_list", target_id: list.id, reason: "pinned", pinned: true, date: null, title: list.title, list }))];
  return <>
    {shown.map(box => box.kind === "project"
      ? <ProjectBox key={box.target_id} box={box} today={today} canEdit={canEdit} onChanged={onChanged} {...project} />
      : <TodayBox key={box.target_id} box={box} today={today} canEdit={canEdit} focusAdd={focus === box.target_id} onOpen={onOpen}
        onChanged={() => { drop(box.target_id); onChanged(); }} onFinished={finished => { drop(box.target_id); onFinished(finished); }} />)}
    {canEdit && <StartList onStarted={list => {
      if (list.pinned !== false) { setStarted(lists => [...lists, list]); setFocus(list.id); }
      onChanged();
    }} />}
  </>;
}
