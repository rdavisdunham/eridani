import { describe, expect, it } from "vitest";
import { doneToday, dueCounts, dueParts, dueReason, dueTasks, inboxTasks } from "./today-counts";
import { scheduledBy } from "./productivity";
import type { Task } from "./types";

const TODAY = "2026-11-05";
const task = (id: string, extra: Partial<Task> = {}) => ({
  id, title: id, status: "open", archived: false, due_date: null, planned_date: null, priority: 0, created_at: "2026-11-01T00:00:00Z", ...extra,
}) as Task;
const list = (id: string, extra: Partial<Task> = {}) => task(id, { is_quick_list: true, ...extra });
const itemOf = (id: string, listId: string, extra: Partial<Task> = {}) => task(id, { parent_task_id: listId, quick_list_parent_id: listId, ...extra });
const ids = (tasks: Task[]) => tasks.map(t => t.id).sort();

describe("Today's Due and overdue and Inbox", () => {
  it("lists a quick-list item with its own date while its list is open, and no other item", () => {
    const tasks = [
      list("groceries"),
      itemOf("milk", "groceries", { due_date: TODAY }),
      itemOf("stamps", "groceries", { planned_date: "2026-11-03" }),
      itemOf("eggs", "groceries", { planned_date: "2026-11-06" }),
      itemOf("bread", "groceries"),
      itemOf("butter", "groceries", { due_date: TODAY, status: "completed" }),
      list("errands", { status: "completed" }),
      itemOf("letter", "errands", { due_date: TODAY }),
      // An archived list is not loaded on Today, so its items have no open list.
      itemOf("old", "archived-list", { due_date: TODAY }),
      task("report", { due_date: TODAY }),
    ];
    expect(ids(dueTasks(tasks, TODAY))).toEqual(["milk", "report", "stamps"]);
  });

  it("keeps an undated list with a box out of Due and Inbox, and lists the same list in Due once it has a date", () => {
    const groceries = list("groceries");
    const tasks = [groceries, itemOf("milk", "groceries"), list("loose"), task("idea")];
    const due = dueTasks(tasks, TODAY);
    expect(due).toEqual([]);
    expect(ids(inboxTasks(tasks, due, new Set(["groceries"])))).toEqual(["idea", "loose"]);

    const dated = [{ ...groceries, due_date: TODAY }, ...tasks.slice(1)];
    const datedDue = dueTasks(dated, TODAY);
    expect(ids(datedDue)).toEqual(["groceries"]);
    expect(ids(inboxTasks(dated, datedDue, new Set(["groceries"])))).toEqual(["idea", "loose"]);
  });

  it("never lists a quick-list item in Inbox, dated tomorrow or not", () => {
    const tasks = [list("groceries"), itemOf("eggs", "groceries", { planned_date: "2026-11-06" }), itemOf("bread", "groceries")];
    const due = dueTasks(tasks, TODAY);
    expect(due).toEqual([]);
    expect(ids(inboxTasks(tasks, due, new Set()))).toEqual(["groceries"]);
  });
});

describe("Today's due counts", () => {
  const due = [
    task("late", { due_date: "2026-11-01" }),
    task("late-and-planned", { due_date: "2026-11-02", planned_date: "2026-11-05" }),
    task("deadline-today", { due_date: TODAY, planned_date: "2026-11-01" }),
    task("slipped", { planned_date: "2026-11-03" }),
    task("slipped-future-deadline", { planned_date: "2026-11-04", due_date: "2026-11-20" }),
    task("planned", { planned_date: TODAY }),
  ];
  it("puts every task on the card in exactly one bucket, deadline first", () => {
    expect(due.every(t => scheduledBy(t, TODAY))).toBe(true);
    expect(due.map(t => dueReason(t, TODAY))).toEqual(["overdue", "overdue", "due_today", "slipped", "slipped", "planned"]);
    const counts = dueCounts(due, TODAY);
    expect(counts).toEqual({ overdue: 2, due_today: 1, slipped: 2, planned: 1 });
    expect(Object.values(counts).reduce((a, b) => a + b, 0)).toBe(due.length);
  });
  it("words the header and the card the same way", () => {
    expect(dueParts(dueCounts(due, TODAY))).toEqual(["2 overdue", "1 due today", "2 slipped", "1 to do today"]);
    expect(dueParts({ overdue: 16, due_today: 0, slipped: 5, planned: 0 }).join(", ")).toBe("16 overdue, 5 slipped");
    expect(dueParts({ overdue: 0, due_today: 0, slipped: 0, planned: 0 })).toEqual([]);
  });
});

describe("the day ring's done count", () => {
  const at = "2026-11-05T15:00:00Z";
  it("counts completions made in Eridani today, not Linear closures that synced in", () => {
    const tasks = [
      task("mine", { status: "completed", finished_at: at, completed_at: at }),
      task("linked-but-mine", { status: "completed", finished_at: at, completed_at: at, external: { provider: "linear", finished_via: null } }),
      task("closed-in-linear", { status: "completed", finished_at: at, completed_at: at, external: { provider: "linear", finished_via: "linear" } }),
      task("canceled", { status: "cancelled", finished_at: at }),
      task("yesterday", { status: "completed", finished_at: "2026-11-04T15:00:00Z" }),
    ];
    expect(doneToday(tasks, TODAY, "UTC")).toBe(2);
  });
});
