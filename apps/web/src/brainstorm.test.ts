import { describe, expect, it } from "vitest";
import { attentionKey, brainstormSaid, DEFAULT_DRAFT, startBody, stopCard, type Run, type RunDetail } from "./remotea-model";

describe("brainstorm: talk it through before planning", () => {
  it("is a start option beside Auto and Skip", () => {
    expect(startBody("t1", { ...DEFAULT_DRAFT, interview: "talk" })).toMatchObject({ task_id: "t1", brainstorm: true });
    expect(startBody("t1", { ...DEFAULT_DRAFT, interview: "talk" })).not.toHaveProperty("interview");
    expect(startBody("t1", DEFAULT_DRAFT)).not.toHaveProperty("brainstorm");
    expect(startBody("t1", { ...DEFAULT_DRAFT, interview: "skip" })).toMatchObject({ interview: false });
    // Freestyle has no plan to talk towards.
    expect(startBody("t1", { ...DEFAULT_DRAFT, interview: "talk", freestyle: true })).not.toHaveProperty("brainstorm");
  });

  it("shows the agent's latest message of this generation", () => {
    const turn = (seq: number, text: string, extra = {}) => ({ id: "t" + seq, seq, text, clipped: false, truncated: false, generation: 1, at: "", prompt: "", ...extra });
    const run = { generation: 1, turns: [turn(2, "Second question?"), turn(1, "First question?"), turn(3, "my reply", { role: "user" as const }),
      turn(9, "from an older generation", { generation: 0 })] };
    expect(brainstormSaid(run)).toBe("Second question?");
    expect(brainstormSaid({ generation: 1, turns: [] })).toBe("");
  });

  it("waits for a reply: an answer, not a result to approve", () => {
    const run = { id: "r", state: "needs_you", state_reason: "brainstorm", attention_detail: { headline: "h", action: "a" } } as unknown as RunDetail;
    expect(attentionKey(run as unknown as Run)).toBe("answer");
    expect(stopCard(run)).toBeNull();
  });
});

describe("a stop the computer never confirmed", () => {
  it("can be closed by the owner only while the computer is offline", async () => {
    const { canCloseUnconfirmedStop } = await import("./remotea-model");
    const host = (connected: boolean) => ({ id: "h", name: "PC", connected });
    expect(canCloseUnconfirmedStop({ state: "stopping", host: host(false) })).toBe(true);
    expect(canCloseUnconfirmedStop({ state: "stopping", host: host(true) })).toBe(false);
    expect(canCloseUnconfirmedStop({ state: "executing", host: host(false) })).toBe(false);
    expect(canCloseUnconfirmedStop({ state: "stopping", host: null })).toBe(false);
  });
});

describe("planning depth: which model plans", () => {
  it("names the planning default when the host has one, else the host's default", async () => {
    const { plannerDefaultLabel } = await import("./RunModels");
    const option = (model: string, extra = {}) => ({ host_id: "h", harness: "claude", model, efforts: [], permission_profiles: [], ...extra });
    expect(plannerDefaultLabel([option("claude-opus-5-5", { default: true, label: "Opus 5.5" }), option("claude-fable-5-2", { planning_default: true, label: "Fable 5.2" })], "claude"))
      .toBe("Planning default (Fable 5.2)");
    expect(plannerDefaultLabel([option("claude-opus-5-5", { default: true, label: "Opus 5.5" })], "claude")).toBe("Model default (Opus 5.5)");
    expect(plannerDefaultLabel([], "claude")).toBe("Model default");
  });
});

describe("model choice: the planning model setting and a run that changed model", () => {
  it("offers the two rules, then each offered model once, and keeps a saved model that is not offered now", async () => {
    const { plannerChoices } = await import("./PlannerModelSetting");
    const option = (model: string, host_id: string, label?: string) => ({ host_id, harness: "claude", model, label, efforts: [], permission_profiles: [] });
    const choices = plannerChoices([option("claude-fable-5-2", "a", "Fable 5.2"), option("claude-fable-5-2", "b"), option("sonnet", "a")], "old-model");
    expect(choices.map(c => c.value)).toEqual(["strongest", "host", "claude-fable-5-2", "sonnet", "old-model"]);
    expect(choices[2].label).toBe("Fable 5.2");
    expect(choices[4].label).toBe("old-model (not offered now)");
  });
  it("says in one line that a run changed model and why", async () => {
    const { modelFallbackLine } = await import("./remotea-model");
    expect(modelFallbackLine({ model_fallback: null })).toBeNull();
    expect(modelFallbackLine({ model_fallback: { from: "claude-fable-5-2", to: "claude-opus-5-5", why: "its usage ran out" } }))
      .toBe("Changed model: claude-fable-5-2 could not go on (its usage ran out), so this run carries on under claude-opus-5-5.");
  });
});

describe("route labels setting", () => {
  it("reads what was typed as label names", async () => {
    const { parseLabels } = await import("./RouteLabelsSettings");
    expect(parseLabels(" AI-Assignable, agent ok ,, ai-assignable")).toEqual(["ai-assignable", "agent ok"]);
    expect(parseLabels("")).toEqual([]);
  });
});
