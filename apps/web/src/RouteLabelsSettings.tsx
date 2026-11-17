import { useEffect, useState } from "react";
import { api } from "./api";
import { SettingRow } from "./SettingsLayout";

export type RouteLabels = { auto_labels: string[]; human_labels: string[]; defaults: { auto_labels: string[]; human_labels: string[] } };

/** What the owner typed, as label names: split on commas, trimmed, lower-cased, once each. */
export function parseLabels(text: string): string[] {
  return [...new Set(text.split(",").map(part => part.trim().toLowerCase()).filter(Boolean))];
}

/** Route labels (readiness.py): which labels on a task (its tags or its Linear labels) decide who does it. */
export function RouteLabelsSettings({ readOnly }: { readOnly: boolean }) {
  const [value, setValue] = useState<RouteLabels | null>(null);
  const [draft, setDraft] = useState({ auto: "", human: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const show = (next: RouteLabels) => { setValue(next); setDraft({ auto: next.auto_labels.join(", "), human: next.human_labels.join(", ") }); };
  useEffect(() => { api<RouteLabels>("/remotea/route-labels").then(show).catch(() => {}); }, []);
  if (!value) return null;
  const save = async () => {
    const auto_labels = parseLabels(draft.auto), human_labels = parseLabels(draft.human);
    if (auto_labels.join() === value.auto_labels.join() && human_labels.join() === value.human_labels.join()) return;
    setBusy(true); setError("");
    try {
      show(await api<RouteLabels>("/remotea/route-labels", { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_labels, human_labels }) }));
    } catch (e) { setError(e instanceof Error ? e.message : "That did not save."); }
    setBusy(false);
  };
  const off = busy || readOnly;
  return <>
    <SettingRow as="label" label="Labels that mean an agent can finish it"
      hint={`A task with one of these labels (a tag here, or a label in Linear) takes the Auto route when its repository has a check and nothing about it is risky. Separate names with commas. Default: ${value.defaults.auto_labels.join(", ")}.`}>
      <input type="text" aria-label="Labels that mean an agent can finish it" value={draft.auto} disabled={off}
        onChange={e => setDraft(d => ({ ...d, auto: e.target.value }))} onBlur={() => void save()}
        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); void save(); } }}/>
    </SettingRow>
    <SettingRow as="label" label="Labels that mean it is yours to do"
      hint={`A task with one of these labels is never given to an agent. Default: ${value.defaults.human_labels.join(", ")}.`}>
      <input type="text" aria-label="Labels that mean it is yours to do" value={draft.human} disabled={off}
        onChange={e => setDraft(d => ({ ...d, human: e.target.value }))} onBlur={() => void save()}
        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); void save(); } }}/>
    </SettingRow>
    {error && <p role="alert" className="work-error">{error}</p>}
  </>;
}
