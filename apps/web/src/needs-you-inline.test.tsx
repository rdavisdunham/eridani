// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Proposal, Review } from "./context/context-model";
import { inlineLabel, type NeedsYouItem } from "./needs-you-model";

const getReview = vi.fn(), approve = vi.fn(), done = vi.fn();
vi.mock("./context/context-api", () => ({
  getReview: (...a: unknown[]) => getReview(...a), approve: (...a: unknown[]) => approve(...a),
  applyUpdates: vi.fn(), done: (...a: unknown[]) => done(...a), isStale: () => false,
}));
const { MeetingProposals } = await import("./context/MeetingProposals");

const proposal = (id: string, extra: Partial<Proposal> = {}) => ({
  id, revision: 1, kind: "task", title: `Task ${id}`, disposition: "pending", preselected: true, publication: null,
  reason: null, evidence: [], destination: "eridani", ...extra }) as unknown as Proposal;
const review = (proposals: Proposal[]) => ({ revision: 3, destination: "eridani", proposals }) as unknown as Review;

let root: Root, host: HTMLDivElement;
beforeEach(() => { host = document.createElement("div"); document.body.append(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });
const flush = () => act(async () => { await new Promise(r => setTimeout(r, 0)); });
const button = (text: string) => [...host.querySelectorAll("button")].find(b => b.textContent?.startsWith(text))!;

describe("deciding in the Needs you list", () => {
  it("offers to decide meetings and answer questions in place, and nothing else", () => {
    const item = (extra: Partial<NeedsYouItem>) => ({ key: "k", kind: "run", title: "", decision: "", recommendation: null,
      evidence: [], if_accepted: null, open: null, accept: null, urgent: false, since: null, ...extra }) as NeedsYouItem;
    expect(inlineLabel(item({ kind: "meeting", source_id: "s" }))).toBe("Decide here");
    expect(inlineLabel(item({ kind: "question", question: { key: "q" } as never }))).toBe("Answer here");
    expect(inlineLabel(item({ kind: "question" }))).toBeNull();
    expect(inlineLabel(item({ kind: "run" }))).toBeNull();
  });

  it("adds the preselected proposals, then finishes by dismissing the rest", async () => {
    getReview.mockResolvedValue(review([proposal("a"), proposal("b", { preselected: false })]));
    approve.mockResolvedValue({ review: review([proposal("a", { disposition: "approved", publication: { id: "p", status: "queued" } } as never), proposal("b", { preselected: false })]) });
    done.mockResolvedValue({ review: review([]) });
    const settled = vi.fn();
    act(() => root.render(<MeetingProposals sourceId="s1" onSettled={settled} onOpen={() => {}}/>));
    await flush();
    expect(getReview).toHaveBeenCalledWith("s1");
    expect(button("Add selected").textContent).toBe("Add selected (1) to Eridani");
    // Finishing would dismiss what is selected, so it waits until the selection is added or cleared.
    expect(button("Dismiss the rest").disabled).toBe(true);
    await act(async () => { button("Add selected").click(); });
    await flush();
    expect(approve).toHaveBeenCalledWith("s1", "eridani", [{ proposal_id: "a", revision: 1 }]);
    expect(settled).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain("Adding 1 to Eridani.");
    await act(async () => { button("Dismiss the rest").click(); });
    await flush();
    expect(done).toHaveBeenCalledWith("s1", 3, [{ proposal_id: "b", revision: 1 }]);
    expect(settled).toHaveBeenCalledTimes(2);
  });
});
