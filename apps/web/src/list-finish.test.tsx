// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { useListFinish, type ListFinish } from "./list-finish";
import { TodayBox } from "./TodayBox";
import type { QuickList, QuickListBoxData, Task } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const item = (id: string, title: string, extra: Partial<Task> = {}) =>
  ({ id, title, status: "open", revision: 1, archived: false, quick_section: "", parent_task_id: "L", quick_list_parent_id: "L", ...extra }) as Task;
const quickList = (items: Task[], extra: Partial<QuickList> = {}) => ({
  id: "L", title: "Groceries", status: "open", revision: 5, archived: false, is_quick_list: true, due_date: null, planned_date: null, items,
  done: items.filter(i => i.status === "completed").length, total: items.length, ...extra,
}) as QuickList;
const box: QuickListBoxData = { kind: "quick_list", target_id: "L", reason: "pinned", pinned: true, date: null, title: "Groceries",
  list: quickList([item("m", "Milk"), item("b", "Bread", { status: "completed" })]) };

type Reply = { status: number; body: unknown };
type Call = { url: string; body: { tool?: string; arguments?: Record<string, unknown> } };
let host: HTMLDivElement, root: Root, calls: Call[], serve: (call: Call) => Reply, finish: ListFinish;
const onChanged = vi.fn();
const done = (data: unknown): Reply => ({ status: 200, body: { command_id: "c", status: "succeeded", data } });
beforeEach(() => {
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); calls = []; onChanged.mockClear();
  serve = () => { throw Error("Unexpected request"); };
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const call = { url, body: init.body ? JSON.parse(String(init.body)) : {} };
    calls.push(call);
    const reply = serve(call);
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body, headers: new Headers() };
  });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

/** The app shell: Today (with one box) or the Tasks page, and the app-level finish toast and confirmation. */
function Shell({ view }: { view: "today" | "tasks" }) {
  finish = useListFinish({ titleOf: id => (id === "L" ? "Groceries" : undefined), onChanged });
  return <>
    {view === "today" && <TodayBox box={box} today="2026-11-18" canEdit onOpen={() => {}} onChanged={() => {}} onFinished={list => finish.finished(list)}/>}
    <button type="button">Elsewhere</button>
    {finish.element}
  </>;
}
const render = (view: "today" | "tasks" = "tasks") => act(async () => root.render(<Shell view={view}/>));
const flush = () => act(async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0)); });
const toast = () => host.querySelector(".toast")?.querySelector("span")?.textContent ?? null;
const undo = () => [...host.querySelectorAll<HTMLButtonElement>(".toast button")].find(b => b.textContent === "Undo") ?? null;
const button = (text: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent === text)!;
const commands = () => calls.filter(c => c.url === "/api/v1/commands").map(c => ({ tool: c.body.tool, arguments: c.body.arguments }));
const refusal = (open: number) => new ApiError("LIST_HAS_OPEN_ITEMS", open + " items aren't checked.",
  { task_id: "L", revision: 5, open_count: open, open_item_ids: ["a", "b", "c", "d"].slice(0, open) }, 409);
const ok = (body: unknown): Reply => ({ status: 200, body });
const refused = (code: string, data?: unknown): Reply => ({ status: 409, body: { error: { code, message: code, data } } });
const dialog = () => document.querySelector('[role="dialog"]');

describe("a list finished from its box", () => {
  it("says the list is done, moves focus to Undo as the box leaves, survives a switch to Tasks, and Undo unchecks that item", async () => {
    serve = () => done({ ...quickList([item("m", "Milk", { status: "completed", revision: 2 }), item("b", "Bread", { status: "completed" })], { status: "completed", revision: 7 }), list_finished: true, list_id: "L", list_revision: 7 });
    await render("today");
    const check = host.querySelector<HTMLButtonElement>('[aria-label="Check off Milk"]')!;
    check.focus();
    await act(async () => check.click());
    await flush();
    expect(toast()).toBe("Groceries is done.");
    expect(document.activeElement).toBe(undo());
    // The box leaves (Today reads its boxes again) and the person switches to Tasks: the toast stays.
    await render("tasks");
    expect(host.querySelector(".today-box")).toBeNull();
    expect(toast()).toBe("Groceries is done.");
    expect(document.activeElement).toBe(undo());
    serve = () => done({ ...quickList([item("m", "Milk", { revision: 3 })], { revision: 8 }), list_reopened: true });
    await act(async () => undo()!.click());
    await flush();
    expect(commands().at(-1)).toEqual({ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 7, operation: "edit", item_id: "m", expected_item_revision: 2, completed: false } });
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(toast()).toBe("Undone.");
  });
});

describe("the finish toast", () => {
  it("stays while Undo has focus and leaves six seconds after focus moves on", async () => {
    vi.useFakeTimers();
    await render();
    await act(async () => finish.finished({ id: "L", title: "Groceries", undo: async () => {}, focus: true }));
    expect(document.activeElement).toBe(undo());
    await act(async () => { vi.advanceTimersByTime(20_000); });
    expect(toast()).toBe("Groceries is done.");
    await act(async () => button("Elsewhere").focus());
    await act(async () => { vi.advanceTimersByTime(5_900); });
    expect(toast()).toBe("Groceries is done.");
    await act(async () => { vi.advanceTimersByTime(200); });
    expect(toast()).toBeNull();
  });

  it("leaves focus where it is when the finished list did not hold it, and closes after six seconds", async () => {
    vi.useFakeTimers();
    await render();
    button("Elsewhere").focus();
    await act(async () => finish.finished({ id: "L", title: "Groceries", undo: async () => {} }));
    expect(document.activeElement).toBe(button("Elsewhere"));
    await act(async () => { vi.advanceTimersByTime(6_100); });
    expect(toast()).toBeNull();
  });
});

describe("finishing a list that still has unchecked items", () => {
  it("asks first; Cancel sends nothing; confirming completes the list and its items, and Undo reopens all three", async () => {
    await render();
    let handled = false;
    await act(async () => { handled = finish.refused(refusal(2)); });
    expect(handled).toBe(true);
    expect(dialog()!.textContent).toContain("Groceries");
    expect(dialog()!.textContent).toContain("2 items aren't checked. Finish the whole list?");
    await act(async () => button("Cancel").click());
    expect(dialog()).toBeNull();
    expect(commands()).toEqual([]);

    await act(async () => { finish.refused(refusal(2)); });
    serve = () => done({ ...quickList([], { status: "completed", revision: 6 }), completed_item_ids: ["a", "b"] });
    await act(async () => button("Finish list").click());
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 5, complete_open_items: true, open_item_ids: ["a", "b"] } }]);
    expect(dialog()).toBeNull();
    expect(toast()).toBe("Groceries is done.");
    expect(document.activeElement).toBe(undo());
    expect(onChanged).toHaveBeenCalledTimes(1);

    serve = () => done({ ...quickList([], { revision: 7 }), reopened_item_ids: ["a", "b"] });
    await act(async () => undo()!.click());
    await flush();
    expect(commands().at(-1)).toEqual({ tool: "task.reopen", arguments: { task_id: "L", expected_revision: 6, item_ids: ["a", "b"] } });
    expect(toast()).toBe("Undone.");
  });

  it("asks again with the server's count when the list changed while it asked, and never resends consent by itself", async () => {
    await render();
    await act(async () => { finish.refused(refusal(2)); });
    serve = () => refused("LIST_HAS_OPEN_ITEMS", { task_id: "L", revision: 5, open_count: 3, open_item_ids: ["a", "b", "c"] });
    await act(async () => button("Finish list").click());
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 5, complete_open_items: true, open_item_ids: ["a", "b"] } }]);
    expect(dialog()!.textContent).toContain("3 items aren't checked. Finish the whole list?");
    expect(dialog()!.querySelector('[role="alert"]')).toBeNull();

    // The list's revision moved: read it again and ask about what it holds now.
    calls = [];
    serve = call => call.url === "/api/v1/quick-lists/L"
      ? ok(quickList([item("a", "A"), item("b", "B"), item("c", "C"), item("d", "D"), item("x", "X", { status: "completed" })], { revision: 6 }))
      : refused("REVISION_CONFLICT");
    await act(async () => button("Finish list").click());
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 5, complete_open_items: true, open_item_ids: ["a", "b", "c"] } }]);
    expect(dialog()!.textContent).toContain("4 items aren't checked. Finish the whole list?");
    expect(dialog()!.querySelector('[role="alert"]')).toBeNull();

    calls = [];
    serve = () => done({ ...quickList([], { status: "completed", revision: 7 }), completed_item_ids: ["a", "b", "c", "d"] });
    await act(async () => button("Finish list").click());
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 6, complete_open_items: true, open_item_ids: ["a", "b", "c", "d"] } }]);
    expect(toast()).toBe("Groceries is done.");
  });

  it("drops a finish that failed to send once the question is cancelled", async () => {
    await render();
    await act(async () => { finish.refused(refusal(2)); });
    serve = () => { throw Error("offline"); };
    await act(async () => button("Finish list").click());
    await flush();
    expect(dialog()!.querySelector('[role="alert"]')!.textContent).toContain("Connection lost");
    await act(async () => button("Cancel").click());
    expect(dialog()).toBeNull();
    // A later question about another list sends only its own finish.
    await act(async () => { finish.refused(new ApiError("LIST_HAS_OPEN_ITEMS", "1 item isn't checked.", { task_id: "K", revision: 2, open_count: 1, open_item_ids: ["k"] }, 409)); });
    calls = [];
    serve = () => done({ ...quickList([], { id: "K", status: "completed", revision: 3 }), completed_item_ids: ["k"] });
    await act(async () => button("Finish list").click());
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "K", expected_revision: 2, complete_open_items: true, open_item_ids: ["k"] } }]);
  });

  it("names a single unchecked item, and lets other refusals through", async () => {
    await render();
    await act(async () => { finish.refused(refusal(1)); });
    expect(document.querySelector('[role="dialog"]')!.textContent).toContain("1 item isn't checked. Finish the whole list?");
    expect(finish.refused(new ApiError("REVISION_CONFLICT", "This changed.", undefined, 409))).toBe(false);
  });
});

describe("a command result from a row", () => {
  it("offers Undo when checking an item finished its list, from a Today row or the Tasks page", async () => {
    await render();
    let shown = false;
    await act(async () => { shown = finish.result("task.complete", { id: "m", title: "Milk", status: "completed", revision: 3, quick_list_parent_id: "L", list_finished: true, list_id: "L", list_revision: 7 }); });
    expect(shown).toBe(true);
    expect(toast()).toBe("Groceries is done.");
    serve = () => done({ id: "m", revision: 4, list_reopened: true });
    await act(async () => undo()!.click());
    await flush();
    expect(commands().at(-1)).toEqual({ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 7, operation: "edit", item_id: "m", expected_item_revision: 3, completed: false } });

    await act(async () => { finish.result("record.update", { id: "record-m", task_id: "m", task_revision: 3, quick_list_parent_id: "L", list_finished: true, list_id: "L", list_revision: 9 }); });
    await act(async () => undo()!.click());
    await flush();
    expect(commands().at(-1)).toEqual({ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 9, operation: "edit", item_id: "m", expected_item_revision: 3, completed: false } });
  });

  it("offers Undo when a row finished the list itself, and stays quiet for any other result", async () => {
    await render();
    await act(async () => { finish.result("task.complete", { ...quickList([], { status: "completed", revision: 6 }), completed_item_ids: [] }); });
    expect(toast()).toBe("Groceries is done.");
    serve = () => done({ ...quickList([], { revision: 7 }), reopened_item_ids: [] });
    await act(async () => undo()!.click());
    await flush();
    expect(commands().at(-1)).toEqual({ tool: "task.reopen", arguments: { task_id: "L", expected_revision: 6, item_ids: [] } });

    expect(finish.result("task.complete", { id: "r", title: "Write the report", status: "completed", revision: 2 })).toBe(false);
    expect(finish.result("notification.complete", { id: "n", list_finished: true, list_id: "L", list_revision: 7 })).toBe(false);
  });
});
