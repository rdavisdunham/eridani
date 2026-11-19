import type { Task } from "./types";
import { scheduledBy } from "./productivity";
import { finishedBySync, finishedToday, isFinishedTask } from "./task-finished";

/** Not finished, archived or a template. */
export const live = (t: Task) => !t.archived && !t.is_template && !isFinishedTask(t);
/** Open work of its own: live, and not an item inside a quick list. */
const isOpen = (t: Task) => live(t) && !t.quick_list_parent_id;

/**
 * Today's "Due and overdue": every open task planned or due by today, in date order. It is the safety net, so a
 * task that also shows in a box stays here, and so does a quick-list item with its own date while its list is open.
 */
export function dueTasks(tasks: Task[], today: string) {
  const openLists = new Set(tasks.filter(t => t.is_quick_list && !t.archived && !isFinishedTask(t)).map(t => t.id));
  return tasks.filter(t => live(t) && (!t.quick_list_parent_id || openLists.has(t.quick_list_parent_id)) && scheduledBy(t, today)).sort((a, b) =>
    (a.due_date ?? a.planned_date ?? "9999").localeCompare(b.due_date ?? b.planned_date ?? "9999") ||
    (a.due_time ?? "99:99").localeCompare(b.due_time ?? "99:99") || b.priority - a.priority || a.title.localeCompare(b.title));
}

/** Today's Inbox: open, unfiled tasks that are not already due. A quick list with a box on Today is not also a row. */
export function inboxTasks(tasks: Task[], due: Task[], boxed: Set<string>) {
  const dueIds = new Set(due.map(t => t.id));
  return tasks.filter(t => isOpen(t) && !dueIds.has(t.id) && !boxed.has(t.id) && !t.project_id && !t.space_id && !t.area_id)
    .sort((a, b) => b.priority - a.priority || b.created_at.localeCompare(a.created_at));
}

/** Why an open task is on Today's "Due and overdue" list. Each task lands in exactly one bucket, so the
 *  parts always add up to the card's count: a deadline wins over a planned day, the past over today. */
export type DueReason = "overdue" | "due_today" | "slipped" | "planned";
export function dueReason(task: Pick<Task, "due_date" | "planned_date">, today: string): DueReason | null {
  if (task.due_date && task.due_date < today) return "overdue";
  if (task.due_date === today) return "due_today";
  if (task.planned_date && task.planned_date < today) return "slipped";
  if (task.planned_date === today) return "planned";
  return null;
}

export type DueCounts = Record<DueReason, number>;
export function dueCounts(due: Pick<Task, "due_date" | "planned_date">[], today: string): DueCounts {
  const counts: DueCounts = { overdue: 0, due_today: 0, slipped: 0, planned: 0 };
  for (const task of due) { const reason = dueReason(task, today); if (reason) counts[reason]++; }
  return counts;
}

/** The phrases both the header and the card use, in one order: "16 overdue, 5 slipped". */
export function dueParts(counts: DueCounts): string[] {
  return [
    counts.overdue && `${counts.overdue} overdue`,
    counts.due_today && `${counts.due_today} due today`,
    counts.slipped && `${counts.slipped} slipped`,
    counts.planned && `${counts.planned} to do today`,
  ].filter((part): part is string => !!part);
}

/** Completions the owner made in Eridani today; Linear closures that synced in today do not count. */
export function doneToday(tasks: Task[], today: string, zone: string) {
  return finishedToday(tasks, today, zone).filter(task => task.status === "completed" && !finishedBySync(task)).length;
}
