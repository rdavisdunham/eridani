import { useEffect, useRef, useState } from "react";
import { api, post } from "./api";
import type { Host } from "./remotea-model";
import { SettingRow } from "./SettingsLayout";

type Step = { id: string; argv: string[]; cwd?: string };
type Check = Step & { why?: string; status: "passed" | "failed" | "timed_out" | "not_run"; exit_code?: number | null;
  duration_ms?: number; reason?: string; needs_confirmation?: boolean; tail?: string; kept?: boolean; left_files?: boolean };
export type SetupResult = {
  saved: boolean; source: "harness" | "heuristics" | "confirmed";
  harness?: { asked: string | null; model?: string | null; fallback_reason?: string };
  target: { id: string; repo: string; base?: string; prepare?: Step[]; verify?: Step[] };
  replaces?: string | null; checks: Check[]; ci: { pull_request: boolean; workflows?: string[] };
  gate: "local" | "ci" | "none"; notes?: string[]; problems?: { level: "fail" | "warn"; check: string; reason: string }[];
};
export type Setup = { op_id: string; host_id: string; repo: string; confirm: boolean; status: string; done: boolean;
  detail: string; result: SetupResult | null; connected?: boolean };

const command = (s: Step) => s.argv.join(" ") + (s.cwd ? ` (in ${s.cwd})` : "");
const seconds = (ms = 0) => ms < 10_000 ? (ms / 1000).toFixed(1) + " s" : Math.round(ms / 1000) + " s";

/** One line per check, as a person reads it: what ran and how it went, or that it waits for a yes. */
export function checkLine(c: Check): string {
  if (c.status === "passed") return `${command(c)}: passed in ${seconds(c.duration_ms)}`;
  if (c.status === "failed") return `${command(c)}: failed (exit ${c.exit_code}) after ${seconds(c.duration_ms)}${c.kept ? "" : ", left out"}`;
  if (c.status === "timed_out") return `${command(c)}: timed out after ${seconds(c.duration_ms)}${c.kept ? "" : ", left out"}`;
  return c.needs_confirmation ? `${command(c)}: tried in the sandbox when you save` : `${command(c)}: not run (${c.reason ?? "no reason given"})`;
}

/** What gates work on this repository once it is saved. */
export function gateLine(r: SetupResult): string {
  if (r.gate === "local") return "Work is checked by the check above" + (r.ci.pull_request ? ", then by CI on the pull request." : ".");
  if (r.gate === "ci") return "No local check: only the pull request's CI says whether a change is sound.";
  return "Nothing checks work here: no local check and no CI on pull requests.";
}

/** Settings → remotea → Add a repository: the host reads it and proposes a target; saving tries the check and keeps
 * it only if it passes (target_setup.py, remotea's `eridani targets setup`). */
export function TargetSetupSettings({ hosts, readOnly }: { hosts: Host[]; readOnly: boolean }) {
  const able = hosts.filter(h => h.caps.includes("target.setup"));
  const [hostId, setHostId] = useState(able[0]?.id ?? ""), [repo, setRepo] = useState("");
  const [setup, setSetup] = useState<Setup | null>(null), [proposal, setProposal] = useState<SetupResult | null>(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => { if (!hostId && able[0]) setHostId(able[0].id); }, [able, hostId]);
  if (!able.length) return null;
  const follow = (value: Setup) => {
    setSetup(value);
    if (value.done) {
      if (!value.confirm && value.status === "executed" && value.result) setProposal(value.result);
      return;
    }
    timer.current = window.setTimeout(() => {
      api<Setup>(`/remotea/target-setup/${encodeURIComponent(value.op_id)}`).then(follow)
        .catch(e => setError(e instanceof Error ? e.message : "Could not read the setup."));
    }, 2500);
  };
  const act = async (run: () => Promise<Setup>) => {
    setBusy(true); setError("");
    try { follow(await run()); } catch (e) { setError(e instanceof Error ? e.message : "That did not work."); }
    setBusy(false);
  };
  const ask = () => { setProposal(null); void act(() => post<Setup>("/remotea/target-setup", { host_id: hostId, repo: repo.trim() })); };
  const save = () => setup && void act(() => post<Setup>(`/remotea/target-setup/${encodeURIComponent(setup.op_id)}/confirm`));
  const reset = () => { window.clearTimeout(timer.current); setSetup(null); setProposal(null); setError(""); };
  const working = !!setup && !setup.done;
  const result = setup?.result ?? null;
  const off = readOnly || busy || working;
  return <div className="target-setup" role="group" aria-label="Add a repository">
    <SettingRow label="Add a repository"
      hint="The server reads the repository with a coding agent and proposes how agents work there: the base branch, the install step and a quick check. Nothing runs until you save; then the check is tried in a sandbox with no network and kept only if it passes.">
      <div className="target-setup-ask">
        {able.length > 1 && <select aria-label="Server" value={hostId} disabled={off} onChange={e => setHostId(e.target.value)}>
          {able.map(h => <option key={h.id} value={h.id}>{h.name || h.machine}</option>)}</select>}
        <input type="text" aria-label="Repository folder" placeholder="/home/you/project" value={repo} disabled={off}
          onChange={e => setRepo(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && repo.trim().startsWith("/")) { e.preventDefault(); ask(); } }}/>
        <button className="btn btn-sm" disabled={off || !repo.trim().startsWith("/")} onClick={ask}>Read it</button>
      </div>
    </SettingRow>
    {working && <p className="footnote" role="status">{setup!.confirm ? "Trying the check and saving…" : "Reading the repository… this can take a few minutes."}{setup!.connected === false ? " The server is offline; it starts when it reconnects." : ""}</p>}
    {setup?.done && setup.status !== "executed" && <p className="work-error" role="alert">
      {setup.status === "expired" ? "The server did not start in time. Try again." : setup.detail || "The setup did not finish."}</p>}
    {proposal && !setup?.confirm && <section className="target-setup-proposal" aria-label="Proposed repository">
      <p>{proposal.source === "harness" ? `Proposed by ${proposal.harness?.asked ?? "an agent"} after reading the repository:` : `Proposed from the repository's files (${proposal.harness?.fallback_reason ?? "no agent was asked"}):`}</p>
      <dl>
        <dt>Name</dt><dd>{proposal.target.id}{proposal.replaces ? ` (replaces ${proposal.replaces})` : ""}</dd>
        <dt>Base branch</dt><dd>{proposal.target.base ?? "main"}</dd>
        <dt>Install</dt><dd>{proposal.target.prepare?.length ? proposal.target.prepare.map(command).join("; ") : "none"}</dd>
        <dt>Check</dt><dd>{proposal.checks.length ? proposal.checks.map(c => <div key={c.id}>{checkLine(c)}{c.why && <small> {c.why}</small>}</div>) : "none proposed"}</dd>
        <dt>CI</dt><dd>{proposal.ci.pull_request ? `runs on pull requests (${(proposal.ci.workflows ?? []).join(", ")})` : "no workflow runs on pull requests"}</dd>
        <dt>Gate</dt><dd>{gateLine(proposal)}</dd>
      </dl>
      {[...(proposal.notes ?? []), ...(proposal.problems ?? []).map(p => `${p.level === "fail" ? "Not ready" : "Warning"}: ${p.check}: ${p.reason}`)].map(n => <p key={n} className="footnote">{n}</p>)}
      {!readOnly && <div className="remotea-control-row">
        <button className="btn btn-sm" disabled={busy} onClick={reset}>Cancel</button>
        <button className="btn btn-sm btn-primary" disabled={busy} onClick={save}>Try the check and save</button>
      </div>}
    </section>}
    {setup?.confirm && setup.done && result && <section className="target-setup-proposal" aria-label="Saved repository" role="status">
      <p>{result.saved ? `Saved ${result.target.id}. Choose it when you pick where a task runs.` : "Not saved."}</p>
      {result.checks.map(c => <p key={c.id} className="footnote">{checkLine(c)}</p>)}
      {result.checks.filter(c => c.tail && c.status !== "passed").map(c => <pre key={c.id + "-tail"} className="target-setup-tail">{c.tail}</pre>)}
      <p className="footnote">{gateLine(result)}</p>
      <div className="remotea-control-row"><button className="btn btn-sm" onClick={() => { reset(); setRepo(""); }}>Done</button></div>
    </section>}
    {error && <p role="alert" className="work-error">{error}</p>}
  </div>;
}
