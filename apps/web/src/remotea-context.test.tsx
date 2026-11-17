// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { api, postAction } from "./api";
import { respondDecision } from "./RunWorkflow";
import { decisionList, RemoteaProvider, useRemotea, useRemoteaActions, type RemoteaActions, type RemoteaData } from "./remotea-context";

vi.mock("./api", () => ({ api: vi.fn(), flushActions: vi.fn(), postAction: vi.fn() }));
vi.mock("./RunWorkflow", () => ({ respondDecision: vi.fn(), flushDrafts: vi.fn() }));
vi.mock("./RunModels", () => ({ flushRolePreferences: vi.fn() }));
vi.mock("./remotea-refresh", () => ({ useAgentRefresh: vi.fn() }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.resetAllMocks());

it("coalesces overlapping run refreshes and discards results after disabling the integration", async () => {
  const pending: Array<() => void> = [];
  vi.mocked(api).mockImplementation(url => new Promise(resolve => {
    pending.push(() => resolve(url === "/remotea/status" ? { connected: true } : { items: [] }));
  }));
  let actions!: RemoteaActions;
  let data!: RemoteaData;
  function Probe() {
    actions = useRemoteaActions();
    data = useRemotea();
    return null;
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<RemoteaProvider><Probe/></RemoteaProvider>));
    await act(async () => actions.setEnabled(true));
    expect(api).toHaveBeenCalledTimes(4);
    await act(async () => {
      for (let index = 0; index < 20; index++) actions.refresh();
    });
    expect(api).toHaveBeenCalledTimes(4);
    await act(async () => pending.splice(0).forEach(resolve => resolve()));
    expect(api).toHaveBeenCalledTimes(8);
    expect(data.status).toEqual({ connected: true });
    await act(async () => actions.setEnabled(false));
    await act(async () => pending.splice(0).forEach(resolve => resolve()));
    expect(data.status).toBeNull();
    expect(data.activeRuns).toEqual([]);
    expect(api).toHaveBeenCalledTimes(8);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("reads the open decisions under the key the server sends, so Confirm answers through them", async () => {
  expect(decisionList({ decisions: [{ id: "a" } as never] }).map(d => d.id)).toEqual(["a"]);
  expect(decisionList({ items: [{ id: "b" } as never] }).map(d => d.id)).toEqual(["b"]);
  expect(decisionList({})).toEqual([]);
  const proposal = { id: "p1", kind: "control", revision: 1, status: "pending", actions: ["confirm", "decline"] };
  vi.mocked(api).mockImplementation(async url => url === "/remotea/status" ? { connected: true }
    : url === "/remotea/decisions" ? { decisions: [proposal] } : { items: [] });
  vi.mocked(respondDecision).mockResolvedValue({ result: { run: null } } as never);
  let actions!: RemoteaActions;
  function Probe() { actions = useRemoteaActions(); return null; }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<RemoteaProvider><Probe/></RemoteaProvider>));
    await act(async () => actions.setEnabled(true));
    await act(async () => { await actions.decide("p1", "confirm"); });
    expect(respondDecision).toHaveBeenCalledWith(expect.objectContaining({ id: "p1" }), "confirm", {});
    expect(postAction).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
