import type { RunDecision } from "./RunWorkflow";

/** Where an item is acted on (needs_you.py `open`): a view and its parameters. */
export type NeedsYouOpen = { view: string; run_id?: string; pending_id?: string; source?: string; work_id?: string; draft_id?: string };

/** One waiting decision (needs_you.py `item`). */
export type NeedsYouItem = {
  key: string; kind: "run" | "proposal" | "meeting" | "question" | "work" | "draft" | "setup";
  title: string; decision: string; recommendation: string | null; evidence: string[]; if_accepted: string | null;
  open: NeedsYouOpen | null; accept: RunDecision | null; urgent: boolean; since: string | null;
  run_id?: string; pending_id?: string; source_id?: string;
};

export type NeedsYou = { items: NeedsYouItem[]; total: number; counts: Record<string, number>; urgent: number; unavailable: string[]; at: string };

export const KIND_LABELS: Record<NeedsYouItem["kind"], string> = {
  run: "Agent run", proposal: "Dani's proposal", meeting: "Meeting", question: "Question", work: "Dani asked",
  draft: "Voice draft", setup: "Setup",
};

const UNAVAILABLE: Record<string, string> = {
  runs: "agent runs", proposals: "Dani's proposals", meetings: "meeting reviews", questions: "Questions",
  work: "Dani's questions", drafts: "voice drafts", setup: "setup",
};

/** The page's one-line summary: how many things are waiting, and how many cannot wait. */
export function needsYouSummary(value: Pick<NeedsYou, "total" | "urgent">): string {
  if (!value.total) return "Nothing is waiting for you.";
  const things = `${value.total} ${value.total === 1 ? "thing is" : "things are"} waiting for you`;
  return value.urgent ? `${things}; ${value.urgent} ${value.urgent === 1 ? "is" : "are"} blocking work.` : `${things}.`;
}

/** Sources that could not be read this time, in words, or null. */
export function unavailableLine(names: string[]): string | null {
  if (!names.length) return null;
  return `Could not read ${names.map(n => UNAVAILABLE[n] ?? n).join(", ")} just now; those may be missing below.`;
}

/** The label on the accept button: what accepting does, in a word or two. */
export function acceptLabel(item: NeedsYouItem): string | null {
  if (!item.accept) return null;
  if (item.accept.kind === "control") return "Confirm";
  if (item.accept.kind === "final_acceptance") return "Accept";
  return "Approve";
}

/** The action the shared decision is answered with for the accept button. */
export function acceptAction(item: NeedsYouItem): string | null {
  if (!item.accept) return null;
  return item.accept.kind === "control" ? "confirm" : "approve";
}
