// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, post } from "./api";
import { renderToStaticMarkup } from "react-dom/server";
import { BotSettings, permissionScopes } from "./BotSettings";
import { WorkCard, type WorkItem } from "./Activity";

describe("connected agents", () => {
  it("exposes only selected grants and keeps paid queued work opt-in", () => {
    expect(permissionScopes({ tasks:"write", organization:"read", notes:"none" }, false)).toEqual(["tasks:write", "organization:read"]);
    expect(permissionScopes({ tasks:"read", notes:"none" }, true)).toEqual(["tasks:read", "work:run"]);
    expect(permissionScopes({ tasks:"write", notes:"write" }, false, true)).toEqual(["tasks:write", "notes:write", "agents:session"]);
    expect(permissionScopes({ tasks:"write" }, false, false)).not.toContain("agents:session");
    expect(permissionScopes({ tasks:"read" }, false, false, true)).toEqual(["tasks:read", "agents:read"]);
    expect(permissionScopes({ tasks:"read" }, false, true)).not.toContain("agents:read");
    expect(permissionScopes({ context:"write", tasks:"none" }, false, false, false, true)).toEqual(["context:write", "sources:write"]);
    expect(permissionScopes({ context:"read" }, false)).not.toContain("sources:write");
  });
  it("identifies the selected workspace", () => {
    const html = renderToStaticMarkup(<BotSettings workspace="Team launch"/>);
    expect(html).toContain("Team launch"); expect(html).toContain("Connected agents");
  });
  it("attributes saved actions to the initiating agent", () => {
    const item: WorkItem = { id:"w",parent_id:null,conversation_id:"c",request:"task.create",status:"succeeded",
      revision:1,message:"Saved.",actions:[],cancel_requested:false,seen:false,
      created_at:"2026-09-16T15:00:00Z",updated_at:"2026-09-16T15:00:00Z",can_continue:false,
      actor:{type:"bot",id:"b",name:"Codex"} };
    const html = renderToStaticMarkup(<WorkCard item={item} onRefresh={async()=>{}} onOpen={async()=>{}}/>);
    expect(html).toContain("Codex"); expect(html).toContain("connected agent");
  });
});

vi.mock("./api", async importActual => ({
  ...await importActual<typeof import("./api")>(), api: vi.fn(), post: vi.fn(),
}));

describe("agent key enrollment", () => {
  let host: HTMLDivElement, root: Root;
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  beforeEach(() => {
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    vi.mocked(api).mockResolvedValue({ items: [], api_url: "", mcp_url: "" });
    vi.mocked(post).mockReset().mockResolvedValue({ token: "test-key" });
  });
  afterEach(() => { act(() => root.unmount()); host.remove(); });
  const button = (name: string) => [...host.querySelectorAll("button")].find(b => b.textContent?.trim() === name)!;
  const field = (name: string) => [...host.querySelectorAll("label")].find(l => l.querySelector("span")?.textContent === name);
  function select(name: string, value: string) {
    const element = field(name)!.querySelector("select")!;
    act(() => { element.value = value; element.dispatchEvent(new Event("change", { bubbles: true })); });
  }
  async function open(personal = true, readOnly = false) {
    await act(async () => { root.render(<BotSettings workspace="Personal" personal={personal} readOnly={readOnly}/>); });
    act(() => button("Add agent").click());
  }
  it("submits only the dedicated scope even after choosing other agent grants", async () => {
    await open();
    act(() => host.querySelector<HTMLInputElement>("input[type=checkbox]")!.click());
    select("Key type", "glass");
    expect(field("Task scheduling")).toBeUndefined();
    expect(host.querySelector("input[type=checkbox]")).toBeNull();
    select("Key expires after", "30");
    await act(async () => button("Create key").click());
    expect(post).toHaveBeenCalledExactlyOnceWith("/bot-keys", { name: "Google Glass", scopes: ["glassface:dani"], expires_in_days: 30 });
    expect(host.querySelector<HTMLInputElement>("#bot-secret")?.type).toBe("password");
    act(() => button("Add agent").click());
    expect(field("Key type")!.querySelector("select")!.value).toBe("agent");
    expect(field("Key expires after")!.querySelector("select")!.value).toBe("90");
  });
  it("opens a fresh normal agent form after canceling a Glass key", async () => {
    await open();
    select("Key type", "glass"); act(() => button("Cancel").click());
    act(() => button("Add agent").click());
    expect(field("Key type")!.querySelector("select")!.value).toBe("agent");
    expect(button("Create key").disabled).toBe(true);
    const input = field("Agent name")!.querySelector("input")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "Codex");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => button("Create key").click());
    expect(post).toHaveBeenCalledExactlyOnceWith("/bot-keys", {
      name: "Codex", scopes: ["tasks:write", "organization:read", "schema:read"], expires_in_days: 90,
    });
  });
  it.each([[false, false], [true, true]])("hides the device option when personal=%s and readOnly=%s", async (personal, readOnly) => {
    await open(personal, readOnly);
    expect(host.querySelector('option[value="glass"]')).toBeNull();
    expect(field("Agent name")).toBeDefined();
  });
});
