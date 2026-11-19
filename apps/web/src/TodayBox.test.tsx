// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QuickListDetail, type FinishedList } from "./QuickLists";
import { ProjectBox, TodayBox, TodayBoxes } from "./TodayBox";
import type { ProjectBoxData, QuickList, QuickListBoxData, Task, TodayBoxData } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const TODAY = "2026-11-18";

const item = (id: string, title: string, extra: Partial<Task> = {}) =>
  ({ id, title, status: "open", revision: 1, archived: false, quick_section: "", parent_task_id: "L", quick_list_parent_id: "L", ...extra }) as Task;
const quickList = (items: Task[], extra: Partial<QuickList> = {}) => ({
  id: "L", title: "Groceries", status: "open", revision: 5, archived: false, is_quick_list: true, due_date: null, planned_date: null, items,
  done: items.filter(i => i.status === "completed").length, total: items.filter(i => i.status !== "cancelled").length, ...extra,
}) as QuickList;
const pinnedBox = (list: QuickList, extra: Partial<QuickListBoxData> = {}): QuickListBoxData =>
  ({ kind: "quick_list", target_id: list.id, reason: "pinned", pinned: true, date: null, title: list.title, list, ...extra });
/** What Today hands the boxes for project boxes; these tests have none. */
const noProjects = { row: () => null, tasks: [], onOpenProject: () => {} };

type Reply = { status: number; body: unknown };
type Call = { method: string; url: string; body: Record<string, unknown> & { tool?: string; arguments?: Record<string, unknown> } };
let host: HTMLDivElement, root: Root, calls: Call[];
let serve: (call: Call) => Reply | Promise<Reply>;
const ok = (body: unknown): Reply => ({ status: 200, body });
const done = (data: unknown): Reply => ok({ command_id: "c", status: "succeeded", data });
const refused = (code: string, message: string, data?: unknown): Reply => ({ status: 409, body: { error: { code, message, data } } });
function deferred() {
  let resolve!: (reply: Reply) => void;
  const promise = new Promise<Reply>(r => { resolve = r; });
  return { promise, resolve };
}
beforeEach(() => {
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); calls = [];
  serve = call => { throw Error("Unexpected request " + call.method + " " + call.url); };
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const call = { method: init.method ?? "GET", url, body: init.body ? JSON.parse(String(init.body)) : {} };
    calls.push(call);
    const reply = await serve(call);
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body, headers: new Headers() };
  });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

const flush = () => act(async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0)); });
const render = (node: ReactNode) => act(async () => root.render(node));
const commands = () => calls.filter(c => c.url === "/api/v1/commands").map(c => ({ tool: c.body.tool, arguments: c.body.arguments }));
const byLabel = <T extends HTMLElement = HTMLButtonElement>(label: string) => document.querySelector<T>(`[aria-label="${label}"]`)!;
const button = (text: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent === text);
const openTitles = () => [...host.querySelectorAll<HTMLElement>(".box-open .row-title")].map(e => e.textContent);
const doneLine = () => host.querySelector("summary")?.textContent ?? null;
const alerts = () => [...host.querySelectorAll('[role="alert"]')].map(e => e.textContent);
function type(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}
async function menu(choice: string) {
  await act(async () => byLabel("Options for Groceries").click());
  const entry = button(choice);
  if (!entry) throw Error("No menu entry " + choice);
  await act(async () => entry.click());
}
const box = (data: QuickListBoxData, extra: { canEdit?: boolean; onChanged?: () => void; onFinished?: (f: FinishedList) => void } = {}) =>
  <TodayBox box={data} today={TODAY} canEdit={extra.canEdit ?? true} onOpen={() => {}} onChanged={extra.onChanged ?? (() => {})} onFinished={extra.onFinished ?? (() => {})}/>;

describe("a quick list's box on Today", () => {
  it("shows the title, the open items as Today rows with their section labels, an N done line, and the add field", () => {
    const html = renderToStaticMarkup(box(pinnedBox(quickList([
      item("a", "Milk", { quick_section: "Store" }), item("b", "Eggs", { quick_section: "Store" }),
      item("c", "Bread", { status: "completed" }),
      item("d", "Butter", { status: "completed", archived: true, archive_reason: "automatic" }),
      item("e", "Typo", { status: "cancelled" }),
    ]))));
    expect(html).toMatch(/<h2 id="[^"]+" tabindex="-1">Groceries<\/h2>/);
    expect(html).toContain('aria-label="Check off Milk"');
    expect(html).toContain('aria-label="Check off Eggs"');
    expect(html).toContain(">Store<");
    // Only checked items still on the list count: the auto-archived one and the removed one do not.
    expect(html).toContain("<summary>1 done</summary>");
    expect(html).not.toContain("Butter");
    expect(html).not.toContain("Typo");
    expect(html).toContain('aria-label="Add to Groceries"');
  });

  it("says All done when every item is checked, and asks for a first item when there are none", () => {
    const allDone = renderToStaticMarkup(box(pinnedBox(quickList([item("c", "Bread", { status: "completed" })]))));
    expect(allDone).toContain("All done");
    expect(allDone).toContain('aria-label="Add to Groceries"');
    const empty = renderToStaticMarkup(box(pinnedBox(quickList([]))));
    expect(empty).toContain("Add your first item.");
    expect(empty).not.toContain("All done");
    expect(empty).toContain('aria-label="Add to Groceries"');
  });

  it("checks an item at once and sends two quick taps in order, each with the list's latest revision", async () => {
    const items = [item("a", "Milk"), item("b", "Eggs"), item("c", "Bread")];
    const first = deferred();
    serve = call => call.body.arguments?.item_id === "a" ? first.promise
      : done(quickList([item("a", "Milk", { status: "completed", revision: 2 }), item("b", "Eggs", { status: "completed", revision: 2 }), items[2]], { revision: 7 }));
    await render(box(pinnedBox(quickList(items))));
    await act(async () => byLabel("Check off Milk").click());
    expect(openTitles()).toEqual(["Eggs", "Bread"]);
    expect(doneLine()).toBe("1 done");
    await act(async () => byLabel("Check off Eggs").click());
    expect(openTitles()).toEqual(["Bread"]);
    expect(doneLine()).toBe("2 done");
    // The second tap waits for the first, so it can use the revision the first one produced.
    expect(commands().map(c => c.arguments?.item_id)).toEqual(["a"]);
    await act(async () => first.resolve(done(quickList([item("a", "Milk", { status: "completed", revision: 2 }), items[1], items[2]], { revision: 6 }))));
    await flush();
    expect(commands()).toEqual([
      { tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 5, operation: "edit", item_id: "a", expected_item_revision: 1, completed: true } },
      { tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 6, operation: "edit", item_id: "b", expected_item_revision: 1, completed: true } },
    ]);
    expect(openTitles()).toEqual(["Bread"]);
  });

  it("reloads and retries once after a revision conflict, and shows a second conflict in the box", async () => {
    const items = [item("a", "Milk"), item("b", "Eggs")];
    const fresh = quickList([item("a", "Milk", { revision: 3 }), items[1]], { revision: 9 });
    let posts = 0;
    serve = call => call.method === "GET" ? ok(fresh)
      : ++posts === 1 ? refused("REVISION_CONFLICT", "This changed on another device. Review the latest version.")
      : done(quickList([item("a", "Milk", { status: "completed", revision: 4 }), items[1]], { revision: 10 }));
    await render(box(pinnedBox(quickList(items))));
    await act(async () => byLabel("Check off Milk").click());
    await flush();
    expect(calls.map(c => c.method + " " + c.url)).toEqual(["POST /api/v1/commands", "GET /api/v1/quick-lists/L", "POST /api/v1/commands"]);
    expect(commands().map(c => [c.arguments?.expected_revision, c.arguments?.expected_item_revision])).toEqual([[5, 1], [9, 3]]);
    expect(openTitles()).toEqual(["Eggs"]);
    expect(alerts()).toEqual([]);

    calls = [];
    serve = call => call.method === "GET" ? ok(quickList([item("a", "Milk", { status: "completed", revision: 4 }), item("b", "Eggs", { revision: 5 })], { revision: 12 }))
      : refused("REVISION_CONFLICT", "This changed on another device. Review the latest version.");
    await act(async () => byLabel("Check off Eggs").click());
    await flush();
    expect(commands()).toHaveLength(2);
    expect(alerts()).toEqual(["This changed on another device. Review the latest version."]);
    expect(openTitles()).toEqual(["Eggs"]);
  });

  it("shows a full list's refusal under the add field and keeps the typed item", async () => {
    serve = () => refused("LIST_FULL", "Quick lists hold up to 100 items.");
    await render(box(pinnedBox(quickList([item("a", "Milk")]))));
    const field = byLabel<HTMLInputElement>("Add to Groceries");
    await act(async () => type(field, "Eggs"));
    await act(async () => field.form!.requestSubmit());
    await flush();
    expect(commands()).toEqual([{ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 5, operation: "add", title: "Eggs", section: "" } }]);
    expect(field.form!.nextElementSibling?.getAttribute("role")).toBe("alert");
    expect(field.form!.nextElementSibling?.textContent).toBe("Quick lists hold up to 100 items.");
    expect(byLabel<HTMLInputElement>("Add to Groceries").value).toBe("Eggs");
  });

  it("adds an item and clears the field for the next one", async () => {
    serve = () => done(quickList([item("a", "Milk"), item("n", "Eggs")], { revision: 6 }));
    await render(box(pinnedBox(quickList([item("a", "Milk")]))));
    const field = byLabel<HTMLInputElement>("Add to Groceries");
    await act(async () => type(field, "Eggs"));
    await act(async () => field.form!.requestSubmit());
    await flush();
    expect(openTitles()).toEqual(["Milk", "Eggs"]);
    expect(byLabel<HTMLInputElement>("Add to Groceries").value).toBe("");
  });

  it("keeps a box's unsaved add-field text when the box comes back, and only in the box", async () => {
    const list = quickList([item("a", "Milk")], { id: "D" });
    await render(box(pinnedBox(list)));
    await act(async () => type(byLabel<HTMLInputElement>("Add to Groceries"), "Eggs"));
    act(() => root.unmount());
    root = createRoot(host);
    await render(box(pinnedBox(list)));
    expect(byLabel<HTMLInputElement>("Add to Groceries").value).toBe("Eggs");
    // The full list has its own add field, guarded by its dialog.
    serve = call => call.url === "/api/v1/projects" ? ok({ items: [] }) : ok(list);
    await render(<QuickListDetail id="D" onClose={() => {}} onChanged={() => {}}/>);
    await flush();
    expect(byLabel<HTMLInputElement>("New checklist item").value).toBe("");
  });

  it("removes a mistyped item from the box", async () => {
    serve = () => done(quickList([item("a", "Milk"), item("b", "Mlik", { status: "cancelled", revision: 2 })], { revision: 6 }));
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("b", "Mlik")]))));
    await act(async () => byLabel("Remove Mlik").click());
    expect(openTitles()).toEqual(["Milk"]);
    await flush();
    expect(commands()).toEqual([{ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 5, operation: "remove", item_id: "b", expected_item_revision: 1 } }]);
    expect(openTitles()).toEqual(["Milk"]);
    expect(doneLine()).toBeNull();
  });

  it("edits an item's text in place: Enter saves, Escape cancels", async () => {
    serve = () => done(quickList([item("a", "Oat milk", { revision: 2 })], { revision: 6 }));
    await render(box(pinnedBox(quickList([item("a", "Milk")]))));
    await act(async () => button("Milk")!.click());
    const input = byLabel<HTMLInputElement>("Edit Milk");
    expect(document.activeElement).toBe(input);
    await act(async () => type(input, "Almond milk"));
    await act(async () => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(commands()).toEqual([]);
    expect(openTitles()).toEqual(["Milk"]);
    await act(async () => button("Milk")!.click());
    await act(async () => type(byLabel<HTMLInputElement>("Edit Milk"), "Oat milk"));
    await act(async () => { byLabel<HTMLInputElement>("Edit Milk").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    await flush();
    expect(commands()).toEqual([{ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 5, operation: "edit", item_id: "a", expected_item_revision: 1, title: "Oat milk" } }]);
    expect(openTitles()).toEqual(["Oat milk"]);
  });

  it("moves focus to the next open item's check, then to the add field when checking the last one leaves the list open", async () => {
    let revision = 5;
    serve = call => done({ ...quickList([item("a", "Milk", { status: "completed", revision: 2 }), item("b", "Eggs", { status: call.body.arguments?.item_id === "b" ? "completed" : "open" })], { revision: ++revision }) });
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("b", "Eggs")]))));
    byLabel("Check off Milk").focus();
    await act(async () => byLabel("Check off Milk").click());
    expect(document.activeElement).toBe(byLabel("Check off Eggs"));
    await flush();
    await act(async () => byLabel("Check off Eggs").click());
    await flush();
    expect(document.activeElement).toBe(byLabel("Add to Groceries"));
  });

  it("holds focus on the box while checking its last item finishes the list, so Undo can take it", async () => {
    const onFinished = vi.fn<(f: FinishedList) => void>();
    const reply = deferred();
    serve = () => reply.promise;
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("c", "Bread", { status: "completed" })])), { onFinished }));
    let fieldFocused = 0;
    byLabel("Add to Groceries").addEventListener("focus", () => { fieldFocused++; });
    byLabel("Check off Milk").focus();
    await act(async () => byLabel("Check off Milk").click());
    expect(document.activeElement).toBe(host.querySelector("h2"));
    await act(async () => reply.resolve(done({ ...quickList([item("a", "Milk", { status: "completed", revision: 2 }), item("c", "Bread", { status: "completed" })], { status: "completed", revision: 7 }), list_finished: true, list_id: "L", list_revision: 7 })));
    await flush();
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(onFinished.mock.calls[0][0].focus).toBe(true);
    expect(fieldFocused).toBe(0);
  });

  it("moves focus to the add field when checking the last item is refused", async () => {
    serve = () => refused("NOT_FOUND", "That item is gone.");
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("c", "Bread", { status: "completed" })]))));
    byLabel("Check off Milk").focus();
    await act(async () => byLabel("Check off Milk").click());
    await flush();
    expect(openTitles()).toEqual(["Milk"]);
    expect(document.activeElement).toBe(byLabel("Add to Groceries"));
  });

  it("keeps its newer list when Today hands it an older read after a check, and takes a newer one", async () => {
    serve = () => done(quickList([item("a", "Milk", { status: "completed", revision: 2 }), item("b", "Eggs")], { revision: 6 }));
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("b", "Eggs")]))));
    await act(async () => byLabel("Check off Milk").click());
    await flush();
    // Today read its boxes before the check landed, and that read arrives now.
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("b", "Eggs")]))));
    expect(openTitles()).toEqual(["Eggs"]);
    expect(doneLine()).toBe("1 done");
    await render(box(pinnedBox(quickList([item("a", "Milk", { status: "completed", revision: 2 }), item("b", "Eggs"), item("n", "Bread")], { revision: 8 }))));
    expect(openTitles()).toEqual(["Eggs", "Bread"]);
  });

  it("unchecks an item from the done line", async () => {
    serve = () => done(quickList([item("a", "Milk"), item("c", "Bread", { revision: 3 })], { revision: 6 }));
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("c", "Bread", { status: "completed", revision: 2 })]))));
    await act(async () => byLabel("Uncheck Bread").click());
    expect(openTitles()).toEqual(["Milk", "Bread"]);
    await flush();
    expect(commands()).toEqual([{ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 5, operation: "edit", item_id: "c", expected_item_revision: 2, completed: false } }]);
  });

  it("hands over a list finished by checking its last item, with an undo that unchecks that item", async () => {
    const onFinished = vi.fn<(f: FinishedList) => void>();
    serve = () => done({ ...quickList([item("a", "Milk", { status: "completed", revision: 2 }), item("c", "Bread", { status: "completed" })], { status: "completed", revision: 7 }), list_finished: true, list_id: "L", list_revision: 7 });
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("c", "Bread", { status: "completed" })])), { onFinished }));
    await act(async () => byLabel("Check off Milk").click());
    await flush();
    expect(onFinished).toHaveBeenCalledTimes(1);
    const finished = onFinished.mock.calls[0][0];
    expect(finished).toMatchObject({ id: "L", title: "Groceries" });
    serve = () => done({ ...quickList([item("a", "Milk", { revision: 3 })], { revision: 8 }), list_reopened: true });
    await finished.undo();
    expect(commands().at(-1)).toEqual({ tool: "quicklist.item", arguments: { list_id: "L", expected_revision: 7, operation: "edit", item_id: "a", expected_item_revision: 2, completed: false } });
  });

  it("asks before finishing a list with two open items, then completes them with the list", async () => {
    const onFinished = vi.fn<(f: FinishedList) => void>();
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("b", "Eggs"), item("c", "Bread", { status: "completed" })])), { onFinished }));
    await menu("Finish list");
    expect(host.textContent).toContain("2 items aren't checked. Finish the whole list?");
    await act(async () => button("Cancel")!.click());
    expect(host.textContent).not.toContain("aren't checked");
    expect(commands()).toEqual([]);

    await menu("Finish list");
    serve = () => done({ ...quickList([], { status: "completed", revision: 6 }), completed_item_ids: ["a", "b"] });
    await act(async () => host.querySelector<HTMLButtonElement>(".box-confirm .btn-primary")!.click());
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 5, complete_open_items: true, open_item_ids: ["a", "b"] } }]);
    expect(onFinished).toHaveBeenCalledTimes(1);
    // The undo reopens the list and the items it completed.
    serve = () => done({ ...quickList([], { revision: 7 }), reopened_item_ids: ["a", "b"] });
    await onFinished.mock.calls[0][0].undo();
    expect(commands().at(-1)).toEqual({ tool: "task.reopen", arguments: { task_id: "L", expected_revision: 6, item_ids: ["a", "b"] } });
  });

  it("asks again with the server's count when the list changed while it asked, and never resends consent by itself", async () => {
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("c", "Bread", { status: "completed" })]))));
    const confirm = () => act(async () => host.querySelector<HTMLButtonElement>(".box-confirm .btn-primary")!.click());
    await menu("Finish list");
    expect(host.textContent).toContain("1 item isn't checked. Finish the whole list?");
    // Eggs was added from another device while the question was up.
    serve = call => call.method === "GET" ? ok(quickList([item("a", "Milk"), item("e", "Eggs"), item("c", "Bread", { status: "completed" })], { revision: 6 }))
      : refused("REVISION_CONFLICT", "This changed on another device. Review the latest version.");
    await confirm();
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 5, complete_open_items: true, open_item_ids: ["a"] } }]);
    expect(host.textContent).toContain("2 items aren't checked. Finish the whole list?");
    expect(openTitles()).toEqual(["Milk", "Eggs"]);
    expect(alerts()).toEqual([]);

    // Toast was added as a task, which leaves the list's revision alone: the server refuses with its own count.
    calls = [];
    serve = () => refused("LIST_HAS_OPEN_ITEMS", "3 items aren't checked.", { task_id: "L", revision: 6, open_count: 3, open_item_ids: ["a", "e", "t"] });
    await confirm();
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 6, complete_open_items: true, open_item_ids: ["a", "e"] } }]);
    expect(host.textContent).toContain("3 items aren't checked. Finish the whole list?");
    expect(alerts()).toEqual([]);

    calls = [];
    serve = () => done({ ...quickList([], { status: "completed", revision: 7 }), completed_item_ids: ["a", "e", "t"] });
    await confirm();
    await flush();
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 6, complete_open_items: true, open_item_ids: ["a", "e", "t"] } }]);
  });

  it("finishes a list with nothing open at once", async () => {
    const onFinished = vi.fn<(f: FinishedList) => void>();
    serve = () => done({ ...quickList([], { status: "completed", revision: 6 }), completed_item_ids: [] });
    await render(box(pinnedBox(quickList([item("c", "Bread", { status: "completed" })])), { onFinished }));
    await menu("Finish list");
    await flush();
    expect(host.textContent).not.toContain("aren't checked");
    expect(commands()).toEqual([{ tool: "task.complete", arguments: { task_id: "L", expected_revision: 5 } }]);
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("shows a viewer the items without checks, the add field, remove or Finish list, and lets them unpin", async () => {
    const onChanged = vi.fn();
    serve = () => done({ kind: "quick_list", target_id: "L", pinned: false });
    await render(box(pinnedBox(quickList([item("a", "Milk"), item("c", "Bread", { status: "completed" })])), { canEdit: false, onChanged }));
    expect(host.textContent).toContain("Milk");
    expect(host.querySelector(".check")).toBeNull();
    expect(host.querySelector("input")).toBeNull();
    expect(host.querySelector('[aria-label^="Remove"]')).toBeNull();
    await act(async () => byLabel("Options for Groceries").click());
    expect(button("Finish list")).toBeUndefined();
    expect(button("Open full list")).toBeDefined();
    await act(async () => button("Unpin from Today")!.click());
    await flush();
    expect(calls.map(c => [c.method, c.url, c.body.target_id, c.body.pinned, typeof c.body.command_id])).toEqual([["POST", "/api/v1/today/pins", "L", false, "string"]]);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("shows a dated, unpinned box's date instead of an unpin control", async () => {
    const list = quickList([item("a", "Milk")], { due_date: TODAY });
    await render(box(pinnedBox(list, { reason: "dated", pinned: false, date: TODAY })));
    expect(host.querySelector(".panel-header")!.textContent).toContain("Due today");
    await act(async () => byLabel("Options for Groceries").click());
    expect(button("Unpin from Today")).toBeUndefined();
    expect(button("Open full list")).toBeDefined();
  });
});

describe("starting a list on Today", () => {
  it("opens a form in place; saving closes it and shows the new box with focus in its add field, and no dialog", async () => {
    const onChanged = vi.fn();
    await render(<TodayBoxes boxes={[]} today={TODAY} canEdit onOpen={() => {}} onChanged={onChanged} onFinished={() => {}} {...noProjects}/>);
    await act(async () => button("Start a list")!.click());
    const title = byLabel<HTMLInputElement>("List title"), items = byLabel<HTMLTextAreaElement>("Items");
    const save = button("Start list")!;
    await act(async () => type(title, "Packing"));
    // An empty list is fine; more than 100 lines is not.
    expect(save.disabled).toBe(false);
    await act(async () => type(items, Array.from({ length: 101 }, (_, i) => "Thing " + i).join("\n")));
    expect(save.disabled).toBe(true);
    await act(async () => type(items, "Socks\nCharger"));
    serve = () => done(quickList([item("s", "Socks", { parent_task_id: "N" }), item("t", "Charger", { parent_task_id: "N" })], { id: "N", title: "Packing", pinned: true }));
    await act(async () => save.form!.requestSubmit());
    await flush();
    expect(commands()).toEqual([{ tool: "quicklist.create", arguments: { title: "Packing", items: [{ title: "Socks", section: "" }, { title: "Charger", section: "" }], pinned: true } }]);
    expect(host.querySelector("form.today-start-form")).toBeNull();
    expect(host.querySelector("h2")?.textContent).toBe("Packing");
    expect(openTitles()).toEqual(["Socks", "Charger"]);
    expect(document.activeElement).toBe(byLabel("Add to Packing"));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(onChanged).toHaveBeenCalled();
    // When Today's boxes include it, it shows once.
    const created = quickList([item("s", "Socks")], { id: "N", title: "Packing" });
    await render(<TodayBoxes boxes={[pinnedBox(created)]} today={TODAY} canEdit onOpen={() => {}} onChanged={onChanged} onFinished={() => {}} {...noProjects}/>);
    expect(host.querySelectorAll("h2")).toHaveLength(1);
  });

  it("offers no Start a list control to a viewer", async () => {
    await render(<TodayBoxes boxes={[]} today={TODAY} canEdit={false} onOpen={() => {}} onChanged={() => {}} onFinished={() => {}} {...noProjects}/>);
    expect(button("Start a list")).toBeUndefined();
  });
});

describe("a project's box on Today", () => {
  const work = (id: string, title: string, extra: Partial<Task> = {}) =>
    ({ id, title, status: "open", revision: 1, archived: false, due_date: TODAY, planned_date: null, ...extra }) as Task;
  const projectBox = (tasks: Task[], extra: Partial<ProjectBoxData> = {}): ProjectBoxData => ({
    kind: "project", target_id: "P", reason: "pinned", pinned: true, date: null, title: "Eridani", tasks, total: tasks.length,
    add: { parent_task_id: "PT" }, ...extra });
  // Today hands each project task its own Due and overdue row; this stands in for it.
  const row = (task: Task) => <li key={task.id} className="row today-row"><button className="row-title">{task.title}</button></li>;
  const rows = () => [...host.querySelectorAll<HTMLElement>(".today-rows .row-title")].map(e => e.textContent);
  const project = (data: ProjectBoxData, extra: { canEdit?: boolean; tasks?: Task[]; onChanged?: () => void; onOpenProject?: (id: string) => void } = {}) =>
    <ProjectBox box={data} today={TODAY} canEdit={extra.canEdit ?? true} row={row} tasks={extra.tasks ?? []}
      onOpenProject={extra.onOpenProject ?? (() => {})} onChanged={extra.onChanged ?? (() => {})}/>;

  it("shows the project's tasks as Today rows, and Nothing due today when it has none", async () => {
    await render(project(projectBox([work("a", "Ship the release"), work("b", "Fix the voice toggle")])));
    expect(host.querySelector("h2")?.textContent).toBe("Eridani");
    expect(host.querySelector(".panel-count")?.textContent).toBe("2");
    expect(rows()).toEqual(["Ship the release", "Fix the voice toggle"]);
    await render(project(projectBox([])));
    expect(rows()).toEqual([]);
    expect(host.querySelector(".box-state")?.textContent).toBe("Nothing due today.");
    expect(host.querySelector(".panel-count")).toBeNull();
    // An empty project box keeps its add field.
    expect(byLabel("Add to Eridani")).not.toBeNull();
  });

  it("adds a task filed in the project and planned for today, then reads the boxes again", async () => {
    const onChanged = vi.fn();
    serve = () => done(work("n", "Fix the voice toggle", { due_date: null, planned_date: TODAY }));
    await render(project(projectBox([]), { onChanged }));
    const field = byLabel<HTMLInputElement>("Add to Eridani");
    await act(async () => type(field, "Fix the voice toggle"));
    await act(async () => field.form!.requestSubmit());
    await flush();
    expect(commands()).toEqual([{ tool: "task.create", arguments: { title: "Fix the voice toggle", parent_task_id: "PT", planned_date: TODAY } }]);
    expect(field.value).toBe("");
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("keeps the next task typed while one saves, and gives a failed one back its text", async () => {
    const save = deferred();
    serve = () => save.promise;
    await render(project(projectBox([])));
    const field = byLabel<HTMLInputElement>("Add to Eridani");
    await act(async () => type(field, "Fix the voice toggle"));
    await act(async () => field.form!.requestSubmit());
    expect(field.value).toBe("");
    await act(async () => type(field, "Write notes"));
    await act(async () => save.resolve(done(work("n", "Fix the voice toggle"))));
    await flush();
    expect(field.value).toBe("Write notes");
    serve = () => refused("NOT_FOUND", "That record is no longer available.");
    await act(async () => field.form!.requestSubmit());
    await flush();
    expect(field.value).toBe("Write notes");
    expect(alerts()).toEqual(["That record is no longer available."]);
  });

  it("drops a task the moment it is finished anywhere, such as in Due and overdue", async () => {
    const release = work("a", "Ship the release");
    await render(project(projectBox([release, work("b", "Write notes")]), { tasks: [{ ...release, status: "completed" }] }));
    expect(rows()).toEqual(["Write notes"]);
    expect(host.querySelector(".panel-count")?.textContent).toBe("1");
  });

  it("opens the project from its title and menu, and offers the rest when it has more than it shows", async () => {
    const onOpenProject = vi.fn();
    await render(project(projectBox([work("a", "Ship the release")], { total: 53 }), { onOpenProject }));
    expect(host.querySelector(".panel-count")?.textContent).toBe("53");
    await act(async () => button("Eridani")!.click());
    await act(async () => button("52 more in Eridani")!.click());
    await act(async () => byLabel("Options for Eridani").click());
    await act(async () => button("Open project")!.click());
    expect(onOpenProject.mock.calls).toEqual([["P"], ["P"], ["P"]]);
  });

  it("lets a viewer unpin it but not add to it", async () => {
    const onChanged = vi.fn();
    serve = () => done({ kind: "project", target_id: "P", pinned: false, on_today: false, reason: null });
    await render(project(projectBox([work("a", "Ship the release")]), { canEdit: false, onChanged }));
    expect(host.querySelector("input")).toBeNull();
    await act(async () => byLabel("Options for Eridani").click());
    await act(async () => button("Unpin from Today")!.click());
    await flush();
    expect(calls.map(c => [c.method, c.url, c.body.target_id, c.body.pinned])).toEqual([["POST", "/api/v1/today/pins", "P", false]]);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("shows no box for a kind this page does not know yet", async () => {
    const later = { kind: "goal", target_id: "G", reason: "pinned", pinned: true, date: null, title: "Run a marathon" } as unknown as TodayBoxData;
    await render(<TodayBoxes boxes={[later, pinnedBox(quickList([item("a", "Milk")]))]} today={TODAY} canEdit onOpen={() => {}}
      onChanged={() => {}} onFinished={() => {}} {...noProjects}/>);
    expect([...host.querySelectorAll(".today-box h2")].map(e => e.textContent)).toEqual(["Groceries"]);
  });

  it("sits among the quick-list boxes in Today's order", async () => {
    await render(<TodayBoxes boxes={[pinnedBox(quickList([item("a", "Milk")])), projectBox([work("b", "Ship the release")])]}
      today={TODAY} canEdit onOpen={() => {}} onChanged={() => {}} onFinished={() => {}} row={row} tasks={[]} onOpenProject={() => {}}/>);
    expect([...host.querySelectorAll(".today-box h2")].map(e => e.textContent)).toEqual(["Groceries", "Eridani"]);
  });
});
