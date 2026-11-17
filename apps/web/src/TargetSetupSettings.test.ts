import { describe, expect, it } from "vitest";
import { checkLine, gateLine, type SetupResult } from "./TargetSetupSettings";

const base: SetupResult = { saved: false, source: "harness", target: { id: "budget", repo: "/r" }, checks: [],
  ci: { pull_request: false }, gate: "local" };

describe("target setup lines", () => {
  it("says a proposed check waits for the save, and how a tried one went", () => {
    expect(checkLine({ id: "t", argv: ["npm", "test"], cwd: "web", status: "not_run", needs_confirmation: true }))
      .toBe("npm test (in web): tried in the sandbox when you save");
    expect(checkLine({ id: "t", argv: ["npm", "test"], status: "passed", duration_ms: 8123, kept: true })).toBe("npm test: passed in 8.1 s");
    expect(checkLine({ id: "t", argv: ["pytest"], status: "failed", exit_code: 1, duration_ms: 42_000, kept: false }))
      .toBe("pytest: failed (exit 1) after 42 s, left out");
  });
  it("names what gates work", () => {
    expect(gateLine({ ...base, ci: { pull_request: true } })).toContain("then by CI");
    expect(gateLine({ ...base, gate: "ci" })).toContain("only the pull request's CI");
    expect(gateLine({ ...base, gate: "none" })).toContain("Nothing checks work here");
  });
});
