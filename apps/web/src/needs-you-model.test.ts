import { describe, expect, it } from "vitest";
import { acceptAction, acceptLabel, needsYouSummary, unavailableLine, type NeedsYouItem } from "./needs-you-model";

const item = (extra: Partial<NeedsYouItem> = {}): NeedsYouItem => ({
  key: "run:1", kind: "run", title: "Rename the helper", decision: "Accept the finished work", recommendation: null,
  evidence: [], if_accepted: null, open: { view: "remotea", run_id: "1" }, accept: null, urgent: false, since: null, ...extra });

describe("needs you", () => {
  it("says how many things wait and how many block work", () => {
    expect(needsYouSummary({ total: 0, urgent: 0 })).toBe("Nothing is waiting for you.");
    expect(needsYouSummary({ total: 1, urgent: 0 })).toBe("1 thing is waiting for you.");
    expect(needsYouSummary({ total: 3, urgent: 1 })).toBe("3 things are waiting for you; 1 is blocking work.");
  });
  it("names the sources that could not be read", () => {
    expect(unavailableLine([])).toBeNull();
    expect(unavailableLine(["questions", "runs"])).toBe("Could not read Questions, agent runs just now; those may be missing below.");
  });
  it("labels the one-tap accept by what it answers, and offers none without a shared decision", () => {
    const decision = (kind: string) => ({ id: "d", kind, revision: 1, status: "pending", actions: ["approve"] }) as never;
    expect(acceptLabel(item())).toBeNull();
    expect(acceptAction(item())).toBeNull();
    expect([acceptLabel(item({ accept: decision("final_acceptance") })), acceptAction(item({ accept: decision("final_acceptance") }))]).toEqual(["Accept", "approve"]);
    expect([acceptLabel(item({ accept: decision("plan_approval") })), acceptAction(item({ accept: decision("plan_approval") }))]).toEqual(["Approve", "approve"]);
    expect([acceptLabel(item({ accept: decision("control") })), acceptAction(item({ accept: decision("control") }))]).toEqual(["Confirm", "confirm"]);
  });
});
