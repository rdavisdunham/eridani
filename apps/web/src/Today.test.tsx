// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Today } from "./Today";
import type { QuickList, Task, TodayBoxData } from "./types";

const MONDAY = "2026-11-16", TUESDAY = "2026-11-17";
const task = (id: string, title: string, extra: Partial<Task> = {}) => ({
  id, title, notes: "", status: "open", priority: 0, project: null, project_id: null, parent_task_id: null, assignee: "owner",
  work_type: "", tags: [], due_date: null, due_time: null, due_timezone: null, planned_date: null, revision: 1,
  created_at: MONDAY + "T09:00:00Z", updated_at: MONDAY + "T09:00:00Z", completed_at: null, archived: false, occurrence_id: null, ...extra,
}) as Task;
const item = (id: string, title: string, extra: Partial<Task> = {}) => task(id, title, { parent_task_id: "L", quick_list_parent_id: "L", ...extra });
const groceries = (extra: Partial<Task> = {}) => task("L", "Groceries", { is_quick_list: true, ...extra });
const box = (list: Task, items: Task[]): TodayBoxData => ({
  kind: "quick_list", target_id: list.id, reason: "pinned", pinned: true, date: null, title: list.title,
  list: { ...list, items, done: 0, total: items.length } as QuickList,
});

/** Today as static markup, with each section's rows by the label of their check. */
function today(tasks: Task[], boxes: TodayBoxData[], day = MONDAY) {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<Today tasks={tasks} schedules={[]} today={day} zone="UTC" busy={false} noteRevision={0}
    quick="" onQuick={() => {}} onAdd={() => {}} onTask={() => {}} onToggle={() => {}} onEntry={() => {}} onNote={() => {}} onNavigate={() => {}}
    boxes={boxes} onOpenList={() => {}} onBoxesChanged={() => {}} onListFinished={() => {}} onOpenProject={() => {}}/>);
  const rows = (title: string) => [...host.querySelectorAll(`section[aria-labelledby="${title}"] .check`)].map(e => e.getAttribute("aria-label"));
  return { host, due: rows("today-due-title"), inbox: rows("today-inbox-title"), boxes: [...host.querySelectorAll(".today-box h2")].map(e => e.textContent) };
}

describe("Today with quick-list boxes", () => {
  it("shows a pinned list with no date as its box, not as an Inbox or Due row", () => {
    const list = groceries(), milk = item("m", "Milk");
    const screen = today([list, milk, task("t", "Draft the memo")], [box(list, [milk])]);
    expect(screen.boxes).toEqual(["Groceries"]);
    expect(screen.inbox).toEqual(["Complete Draft the memo"]);
    expect(screen.due).toEqual([]);
  });

  it("shows the same list due today as its box and as a Due row, and lists its dated item in Due", () => {
    const list = groceries({ due_date: MONDAY }), milk = item("m", "Milk", { due_date: MONDAY }), eggs = item("e", "Eggs", { planned_date: TUESDAY });
    const screen = today([list, milk, eggs], [box(list, [milk, eggs])]);
    expect(screen.boxes).toEqual(["Groceries"]);
    expect(screen.due).toEqual(["Complete Groceries", "Complete Milk"]);
    expect(screen.inbox).toEqual([]);
  });

  it("places the boxes after Due and overdue and before Inbox", () => {
    const list = groceries();
    const { host } = today([list], [box(list, [])]);
    const order = [...host.querySelectorAll(".today-side > section")].map(s => s.getAttribute("aria-labelledby") === "today-due-title" ? "due"
      : s.classList.contains("today-box") ? "box" : s.getAttribute("aria-labelledby") === "today-inbox-title" ? "inbox" : "other");
    expect(order.filter(s => s !== "other")).toEqual(["due", "box", "inbox"]);
  });

  it("shows a list pinned on Monday with nothing overdue on Tuesday", () => {
    const list = groceries({ created_at: MONDAY + "T08:00:00Z" }), milk = item("m", "Milk");
    const screen = today([list, milk], [box(list, [milk])], TUESDAY);
    expect(screen.boxes).toEqual(["Groceries"]);
    expect(screen.due).toEqual([]);
    expect(screen.host.querySelector(".chip-due-overdue")).toBeNull();
    expect(screen.host.querySelector(".today-summary")!.textContent).toBe("Nothing due today.");
  });
});
