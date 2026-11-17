import { useEffect, useState } from "react";
import { api } from "./api";
import { SettingRow } from "./SettingsLayout";
import type { ModelOption } from "./RunModels";

/** The choices for "Planning model": the two rules, then every model a connected computer offers (once each). */
export function plannerChoices(catalog: ModelOption[], current: string): { value: string; label: string }[] {
  const seen = new Set<string>(), models: { value: string; label: string }[] = [];
  for (const m of catalog) {
    if (!m.model || seen.has(m.model)) continue;
    seen.add(m.model);
    models.push({ value: m.model, label: m.label ?? m.model });
  }
  const fixed = [{ value: "strongest", label: "Strongest available (Fable)" }, { value: "host", label: "The computer's default" }];
  const missing = current && current !== "strongest" && current !== "host" && !seen.has(current)
    ? [{ value: current, label: `${current} (not offered now)` }] : [];
  return [...fixed, ...models, ...missing];
}

/** What planning runs on when a start names no model (agent_control.planning_default). */
export function PlannerModelSetting({ value, readOnly, busy, onChange }: { value: string; readOnly: boolean; busy: boolean; onChange: (value: string) => void }) {
  const [catalog, setCatalog] = useState<ModelOption[]>([]);
  useEffect(() => { api<{ models: ModelOption[] }>("/remotea/model-catalog").then(r => setCatalog(r.models ?? [])).catch(() => {}); }, []);
  return <SettingRow as="label" label="Planning model"
    hint="What plans, brainstorms and looks for ideas when you do not pick a model for a run. The work itself runs on the computer's default. If the planning model runs out of usage, the run moves to the computer's default and tells you.">
    <select aria-label="Planning model" value={value} disabled={busy || readOnly} onChange={e => onChange(e.target.value)}>
      {plannerChoices(catalog, value).map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
    </select>
  </SettingRow>;
}
