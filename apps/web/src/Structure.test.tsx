// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { StructureWorkspace } from "./Structure";
import type { CustomRecord, Schema } from "./structure-types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const TODAY = "2026-11-18";
const field = (id: string, name: string, binding: string) =>
  ({ id, name, description: "", kind: "date", options: [], target_types: [], multiple: false, inherit: false, visible: true, archived: false, binding });
const schema = {
  revision: 1, relationships: [], understandings: [],
  types: [{
    id: "task", name: "Task", plural: "Tasks", description: "", capabilities: ["work"], parent_types: ["task"], archived: false,
    statuses: [{ id: "open", name: "Open", meaning: "open" }, { id: "done", name: "Done", meaning: "completed" }],
    fields: [field("due", "Due date", "due_date"), field("do", "Do date", "planned_date")],
  }],
} as unknown as Schema;
const record = (id: string, title: string, extra: Partial<CustomRecord> = {}): CustomRecord => ({
  id, revision: 1, schema_revision: 1, type_id: "task", type_name: "Task", title, body: "", values: {}, inherited: {}, parent_id: null,
  status_id: "open", status_meaning: "open", archived: false, task_id: "task-" + id, note_id: null, capabilities: ["work"], home: [], links: [], ...extra,
});
const groceries = record("groceries", "Groceries", { task_id: "L", is_quick_list: true, quick_done: 0, quick_total: 2 });
const milk = record("milk", "Milk", { task_id: "M", parent_id: "groceries", quick_list_parent_id: "L", values: { due: TODAY } });
const records = [
  groceries, milk,
  record("eggs", "Eggs", { task_id: "E", parent_id: "groceries", quick_list_parent_id: "L" }),
  record("errands", "Errands", { task_id: "X", is_quick_list: true, status_id: "done", status_meaning: "completed" }),
  record("letter", "Post the letter", { task_id: "T", parent_id: "errands", quick_list_parent_id: "X", values: { due: TODAY } }),
  record("report", "Write the report", { values: { do: TODAY } }),
];

type Reply = { status: number; body: unknown };
type Call = { method: string; url: string; body: { tool?: string; arguments?: Record<string, unknown> } };
let host: HTMLDivElement, root: Root, calls: Call[], command: (call: Call) => Reply;
const listFinish = { result: vi.fn((_tool: string, _data: unknown) => true), refused: vi.fn((_error: unknown) => true) };
beforeEach(() => {
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); calls = [];
  listFinish.result.mockClear(); listFinish.refused.mockClear();
  command = () => { throw Error("Unexpected command"); };
  vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const call = { method: init.method ?? "GET", url, body: init.body ? JSON.parse(String(init.body)) : {} };
    calls.push(call);
    const path = url.replace("/api/v1", "");
    const reply: Reply = call.method === "POST" ? command(call)
      : path === "/structure" ? { status: 200, body: schema }
      : path.startsWith("/structure/records?") ? { status: 200, body: { items: records, next_offset: null } }
      : path.startsWith("/structure/records/") ? { status: 200, body: { ...records.find(r => path.endsWith("/" + r.id)), contents: { work_open: 2 } } }
      : { status: 200, body: { items: [] } };
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body, headers: new Headers() };
  });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

const flush = () => act(async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0)); });
async function tasksPage(tab: "today" | "all") {
  await act(async () => root.render(<StructureWorkspace capability="work" tab={tab} today={TODAY} listFinish={listFinish}/>));
  await flush();
}
const rows = () => [...host.querySelectorAll(".work-row .row-title")].map(e => e.textContent);
const check = (title: string) => host.querySelector<HTMLButtonElement>(`[aria-label="Complete ${title}"]`)!;
const commands = () => calls.filter(c => c.url === "/api/v1/commands").map(c => c.body.tool);

describe("quick lists on the Tasks page", () => {
  it("lists a quick-list item with its own date on the Today tab while its list is open", async () => {
    await tasksPage("today");
    expect(rows().sort()).toEqual(["Milk", "Write the report"]);
  });

  it("hands a refusal to finish a list with unchecked items to the app's confirmation, without its own warning", async () => {
    command = () => ({ status: 409, body: { error: { code: "LIST_HAS_OPEN_ITEMS", message: "2 items aren't checked.", data: { task_id: "L", revision: 4, open_count: 2 } } } });
    await tasksPage("all");
    await act(async () => check("Groceries").click());
    await flush();
    expect(commands()).toEqual(["record.update"]);
    expect(listFinish.refused).toHaveBeenCalledTimes(1);
    const refusal = listFinish.refused.mock.calls[0][0] as ApiError;
    expect([refusal.code, refusal.data]).toEqual(["LIST_HAS_OPEN_ITEMS", { task_id: "L", revision: 4, open_count: 2 }]);
    expect(window.confirm).not.toHaveBeenCalled();
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("hands the result of checking a list's last item to the app, so it can offer Undo", async () => {
    const saved = { ...milk, status_id: "done", status_meaning: "completed", task_revision: 3, list_finished: true, list_id: "L", list_revision: 7 };
    command = () => ({ status: 200, body: { command_id: "c", status: "succeeded", data: saved } });
    await tasksPage("today");
    await act(async () => check("Milk").click());
    await flush();
    expect(commands()).toEqual(["record.update"]);
    expect(listFinish.result).toHaveBeenCalledWith("record.update", saved);
  });
});
