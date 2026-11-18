import { useRef, useState } from "react";
import { ApiError, command } from "./api";
import type { FinishedList } from "./QuickLists";
import { useStructureActions } from "./structure-actions";
import { useUndoToast } from "./undo-toast";
import { Dialog } from "./ux";

type Data = Record<string, unknown>;
/** The server's refusal to finish a quick list that still has unchecked items, unless the owner agrees. */
export type ListRefusal = { task_id: string; revision: number; open_count: number };

export function listRefusal(error: unknown): ListRefusal | null {
  if (!(error instanceof ApiError) || error.code !== "LIST_HAS_OPEN_ITEMS") return null;
  const data = error.data as Partial<ListRefusal> | undefined;
  return typeof data?.task_id === "string" && typeof data.revision === "number" ? { task_id: data.task_id, revision: data.revision, open_count: data.open_count ?? 0 } : null;
}

/** Nothing has focus, or it is inside `element`: what was focused is leaving, so Undo can take focus. */
export function heldFocus(element?: Element | null) {
  const active = document.activeElement;
  return !active || active === document.body || !!element?.contains(active);
}

/** Sends the command; sending it again after a lost connection reuses its command ID. */
function once(tool: string, args: Data) { const pending = command(tool, args); return () => pending.send(); }

/**
 * The list a command's result finished, with the command that undoes it; null when it finished none. A task or
 * Tasks-page change that checked a list's last item is undone by unchecking that item, which reopens the list.
 * Completing the list itself is undone by reopening it with the items it completed.
 */
export function finishedFrom(tool: string, data: unknown, titleOf: (id: string) => string | undefined): FinishedList | null {
  if (!data || typeof data !== "object") return null;
  const result = data as Data;
  const task = tool === "task.complete" || tool === "task.update";
  if (task && result.is_quick_list && result.status === "completed" && Array.isArray(result.completed_item_ids))
    return { id: String(result.id), title: String(result.title), undo: once("task.reopen", { task_id: result.id, expected_revision: result.revision, item_ids: result.completed_item_ids }) };
  const list = result.list_id;
  if (!result.list_finished || typeof list !== "string" || result.quick_list_parent_id !== list) return null;
  const item = task ? { id: result.id, revision: result.revision } : tool === "record.update" ? { id: result.task_id, revision: result.task_revision } : null;
  if (!item) return null;
  return { id: list, title: titleOf(list) ?? "Your list", undo: once("quicklist.item", {
    list_id: list, expected_revision: result.list_revision, operation: "edit", item_id: item.id, expected_item_revision: item.revision, completed: false,
  }) };
}

export type ListFinish = ReturnType<typeof useListFinish>;
/**
 * The app-wide side of finishing a quick list, so it outlives the box or row it came from. A finished list shows
 * "Groceries is done." with Undo for six seconds; it stays while Undo has focus, and Undo takes focus when what
 * finished the list held it. A refusal to finish a list with unchecked items asks first, then completes them with it.
 */
export function useListFinish({ titleOf, onChanged }: { titleOf: (id: string) => string | undefined; onChanged: () => Promise<unknown> | void }) {
  const latest = useRef({ titleOf, onChanged });
  latest.current = { titleOf, onChanged };
  const toast = useUndoToast(async () => { await latest.current.onChanged(); });
  const [asking, setAsking] = useState<(ListRefusal & { title?: string }) | null>(null);
  const { run, busy, error, setError } = useStructureActions();
  const finished = (list: FinishedList) => toast.show({ message: list.title + " is done.", undo: list.undo, focus: !!list.focus });
  /** A command's result: when it finished a quick list, shows the toast and returns true. */
  const result = (tool: string, data: unknown) => {
    const list = finishedFrom(tool, data, id => latest.current.titleOf(id));
    if (list) finished({ ...list, focus: heldFocus() });
    return !!list;
  };
  /** A command's error: when it refused to finish a list with unchecked items, asks first and returns true. */
  const refused = (e: unknown) => {
    const refusal = listRefusal(e);
    if (refusal) { setError(""); setAsking({ ...refusal, title: latest.current.titleOf(refusal.task_id) }); }
    return !!refusal;
  };
  const confirm = (ask: ListRefusal) => void run<Data>("task.complete", { task_id: ask.task_id, expected_revision: ask.revision, complete_open_items: true })
    .then(async data => {
      setAsking(null);
      const list = finishedFrom("task.complete", data, id => latest.current.titleOf(id));
      // The row that asked leaves with the list, so Undo takes focus.
      if (list) finished({ ...list, focus: true });
      await latest.current.onChanged();
    }).catch(() => {});
  const count = asking?.open_count === 1 ? "1 item isn't checked." : asking?.open_count + " items aren't checked.";
  const element = <>
    {toast.element}
    {asking && <Dialog className="dialog" aria-label="Finish the whole list?" onEscape={busy ? undefined : () => setAsking(null)}>
      <header className="dialog-heading"><h2>{asking.title ?? "Quick list"}</h2></header>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <p>{count} Finish the whole list?</p>
      {/* The same order as the question inside a box. On a phone it also keeps Cancel out of the bottom-left
          corner, where Report a bug sits while a dialog is open. */}
      <div className="dialog-actions">
        <button type="button" className="btn btn-primary" autoFocus disabled={busy} onClick={() => confirm(asking)}>Finish list</button>
        <button type="button" className="btn" disabled={busy} onClick={() => setAsking(null)}>Cancel</button>
      </div>
    </Dialog>}
  </>;
  return { finished, result, refused, element };
}
