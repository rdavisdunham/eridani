"""What Eridani does when an agent's own session reports a failure (docs/AGENT_CONTROL.md "When the agent itself fails").

remotea publishes `trouble` on a session's status when the harness says its turn failed (cap `trouble.reported`):

- `rate_limited`: the model's usage ran out, or the provider is refusing for now;
- `auth_expired`: the agent is no longer signed in on that computer;
- `errored`: anything else the harness reported (the model is not available, the API errored, the turn died).

Silence used to be the only signal: a failed turn ended like any other, so planning read it as "ended without a
plan" and execution sent it to be verified and judged. Now:

1. **Carry on under another model when that fixes it.** A run whose model ran out of usage, or is not available
   on that account, moves the same session to the computer's default model and tells the agent to continue
   (`input` with `model`, cap `input.model`): the conversation is kept. Once per run, and only when there is a
   different model to move to. The owner is told, and the run says so (`model_fallback`).
2. **Otherwise stop for the owner with the reason**: `needs_you(rate_limited | auth_expired | agent_errored)`,
   carrying the harness's own words (a usage limit says when it resets). A message to the agent resumes the run.

The failed turn has already been recorded when the report arrives (remotea sends it after the turn ends), so
whatever that turn set in motion is undone here: queued verification and judging are superseded, and a planning
stop that came from the failed turn (`no_plan`, a brainstorm reply that was really an error) is replaced.
"""

from sqlalchemy import select

from .models import now
from .session_models import AgentAttempt, AgentHost

KINDS = ("rate_limited", "auth_expired", "errored")
REASONS = {"rate_limited": "rate_limited", "auth_expired": "auth_expired", "errored": "agent_errored"}
# Failures another model fixes: this one's usage ran out, or the account cannot use it.
MODEL_NOT_AVAILABLE = ("model_not_found",)


def state(run) -> dict:
    return dict((run.sync_state or {}).get("trouble") or {})


def cleared(run):
    """The session started work again (remotea dropped the trouble): nothing is wrong any more."""
    if state(run):
        run.sync_state = {k: v for k, v in (run.sync_state or {}).items() if k != "trouble"}


def model_problem(trouble) -> bool:
    return trouble.kind == "rate_limited" or (
        trouble.kind == "errored" and str(trouble.detail or "").split(":", 1)[0].strip() in MODEL_NOT_AVAILABLE)


def current_model(run):
    """(model, harness) of the session acting now: the worker once the plan was handed over, else the planner."""
    handoff = (run.sync_state or {}).get("handoff") or {}
    worker = (run.roles or {}).get("worker") or {}
    if handoff and worker.get("model"):
        return worker["model"], worker.get("harness") or run.tool
    return run.model, run.tool


def fallback_model(db, run):
    """The model to carry on under, or None: the computer's default for the harness, when the session can change
    model in place, this run has not fallen back before, and that default is not the model that just failed."""
    from . import run_coordinator as coordinator

    if (run.sync_state or {}).get("model_fallback") or not run.surf or not run.host_id:
        return None
    if (run.sync_state or {}).get("execution_mode") != "managed" or not coordinator.host_cap(db, run.host_id, "input.model"):
        return None
    model, harness = current_model(run)
    host = db.get(AgentHost, run.host_id)
    usual = next((m.get("model") for m in (host.caps or {}).get("model_catalog", []) if isinstance(m, dict)
                  and m.get("harness") == harness and (m.get("default") or m.get("is_default") or m.get("isDefault"))), None)
    return usual if usual and usual != model else None


def reported(db, run, trouble):
    """A status frame carried a harness failure for the run's own session. Acts once per failure."""
    from . import run_coordinator as coordinator

    key = f"{trouble.kind}:{getattr(trouble, 'since', None) or ''}:{(trouble.detail or '')[:80]}"
    if state(run).get("key") == key:
        return
    run.sync_state = {**(run.sync_state or {}), "trouble": {
        "kind": trouble.kind, "detail": trouble.detail or "", "at": now().isoformat(), "key": key}}
    if run.freestyle or run.paused or run.state == "stopping":
        return  # Shown on the run; a freestyle or paused run has no loop to steer.
    # Whatever the failed turn set in motion says nothing about the work.
    for attempt in db.scalars(select(AgentAttempt).where(AgentAttempt.run_id == run.id,
                                                         AgentAttempt.status.in_(("queued", "running")))):
        attempt.status, attempt.updated_at = "superseded", now()
    target = fallback_model(db, run) if model_problem(trouble) else None
    if target:
        return fall_back(db, run, trouble, target)
    reason = REASONS[trouble.kind]
    if run.state == "needs_you" and run.state_reason == reason:
        return
    if run.state == "needs_you":
        # The failed turn already parked the run (no plan, a "reply" that was the error text): say what really happened.
        run.state_reason, run.state_revision, run.updated_at = reason, run.state_revision + 1, now()
        coordinator.note(run, "trouble", kind=trouble.kind, detail=(trouble.detail or "")[:300])
    else:
        coordinator.transition(db, run, "needs_you", reason=reason, detail=trouble.detail or "")
    coordinator.notify(db, run, "agent_trouble", TITLES[trouble.kind], (trouble.detail or coordinator.REASON_TEXT[reason])[:300],
                       key=f"{run.id}:{key}")


TITLES = {"rate_limited": "An agent ran out of usage", "auth_expired": "An agent is signed out",
          "errored": "An agent hit an error"}


def fall_back(db, run, trouble, target):
    """Move the session to `target` and tell the agent to carry on. The conversation is kept (remotea changes the
    model in place); the run returns to the phase the failed turn interrupted."""
    from . import agent_prompts as prompts
    from . import run_brainstorm
    from . import run_coordinator as coordinator

    before, _ = current_model(run)
    handoff = (run.sync_state or {}).get("handoff") or {}
    if handoff and (run.roles or {}).get("worker"):
        run.roles = {**run.roles, "worker": {**run.roles["worker"], "model": target}}
    else:
        run.model = target
    why = "its usage ran out" if trouble.kind == "rate_limited" else "this account cannot use it"
    run.sync_state = {**(run.sync_state or {}), "model_fallback": {
        "from": before, "to": target, "why": why, "detail": (trouble.detail or "")[:300], "at": now().isoformat()}}
    coordinator.note(run, "model_fallback", **{"from": before}, to=target, why=why)
    talk = run_brainstorm.state(run)
    if talk.get("open") and int(talk.get("turns") or 0) > 0:
        # The failed turn was counted as the agent's side of the conversation; it said nothing.
        run.sync_state = {**run.sync_state, "brainstorm": {**talk, "turns": int(talk["turns"]) - 1}}
    back = coordinator.phase(run) if run.state == "needs_you" else run.state
    if run.state in ("needs_you", "verifying", "judging"):
        coordinator.transition(db, run, back if back in ("planning", "interviewing", "executing") else "executing",
                               reason="model_fallback", detail=f"{before} → {target}")
    coordinator.command(db, run, "input", {"surf": run.surf, "incarnation": run.incarnation, "mode": "queue",
                                           "text": prompts.model_fallback(why), "model": target}, source="eridani")
    coordinator.note(run, "sent", actor={"kind": "eridani"}, text=prompts.model_fallback(why), kind="model_fallback")
    coordinator.notify(db, run, "agent_trouble", "An agent changed model",
                       f"{before} could not go on ({why}); the run carries on under {target}.", key=f"{run.id}:fallback")
    run.sync_state = {k: v for k, v in run.sync_state.items() if k != "trouble"}


def public(run):
    """For the run page: what is wrong now (`trouble`), and a model change that already happened."""
    value, moved = state(run), (run.sync_state or {}).get("model_fallback")
    return ({"kind": value["kind"], "detail": value.get("detail") or "", "at": value.get("at")} if value else None,
            {k: moved.get(k) for k in ("from", "to", "why", "at")} if moved else None)
