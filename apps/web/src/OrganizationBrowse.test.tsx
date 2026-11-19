// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OrganizationBrowse } from "./OrganizationBrowse";
import type { CustomRecord, Schema } from "./structure-types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const schema = { revision: 1, types: [], relationships: [], understandings: [] } as unknown as Schema;
const home = (type_id: string, extra: Partial<CustomRecord> = {}) =>
  ({ id: "P", type_id, title: "Eridani", body: "", home: [], archived: false, ...extra }) as CustomRecord;

let host: HTMLDivElement, root: Root, calls: { method: string; url: string; body: Record<string, unknown> }[];
let parent: CustomRecord, pins: { kind: string; target_id: string }[];
beforeEach(() => {
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); calls = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const call = { method: init.method ?? "GET", url, body: init.body ? JSON.parse(String(init.body)) : {} };
    calls.push(call);
    const body = url.startsWith("/api/v1/structure/browse") ? { parent, items: [], total: 0, next_offset: null }
      : url === "/api/v1/today/pins" && call.method === "GET" ? { pins }
      : url === "/api/v1/today/pins" ? { data: { kind: "project", target_id: "P", pinned: call.body.pinned } }
      : { items: [] };
    return { ok: true, status: 200, json: async () => body, headers: new Headers() };
  });
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

const flush = () => act(async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0)); });
const button = (text: string) => [...host.querySelectorAll("button")].find(b => b.textContent === text);
async function browse(canEdit = true) {
  await act(async () => root.render(<OrganizationBrowse schema={schema} parent="P" section="work" onSection={() => {}} query="" archived={false}
    status="active" refresh={0} canEdit={canEdit} onBrowse={() => {}} onOpen={() => {}} onCreate={async () => {}}/>));
  await flush();
}

describe("pinning a project to Today from Organize", () => {
  it("pins and unpins the open project from its header, for a viewer too", async () => {
    parent = home("project"); pins = [];
    await browse(false);
    await act(async () => button("Pin to Today")!.click());
    await flush();
    expect(calls.filter(c => c.method === "POST").map(c => [c.url, c.body.target_id, c.body.pinned])).toEqual([["/api/v1/today/pins", "P", true]]);
    expect(button("Unpin from Today")).toBeDefined();
    await act(async () => button("Unpin from Today")!.click());
    await flush();
    expect(button("Pin to Today")).toBeDefined();
  });

  it("shows a project already on this person's Today as pinned", async () => {
    parent = home("project"); pins = [{ kind: "project", target_id: "P" }];
    await browse();
    expect(button("Unpin from Today")).toBeDefined();
  });

  it("offers no pin for other homes or an archived project", async () => {
    for (const record of [home("client"), home("project", { archived: true })]) {
      parent = record; pins = [];
      await browse();
      expect(button("Pin to Today")).toBeUndefined();
      expect(button("Unpin from Today")).toBeUndefined();
    }
  });
});
