"""When the agent's own session reports a failure: carry on under another model, or stop with the reason
(run_trouble.py)."""

from jarvis import agent_control as control
from jarvis import agent_link, run_brainstorm
from jarvis import run_coordinator as coordinator
from jarvis.db import session_scope
from jarvis.models import now
from jarvis.session_models import AgentAttempt, AgentHost, AgentRun, AgentSession
from test_agent_plan import start, turn
from test_agent_runs import attached, commands, quiet, state, task  # noqa: F401 - pytest fixtures
from test_agent_runs import host as host  # noqa: F401 - pytest fixture
from test_planning_depth import CATALOG

LIMIT = {"kind": "rate_limited", "since": 7, "detail": "rate_limit: You've hit your limit · resets 3pm"}


def modern(host, *, change_model=True):
    """A host with managed sessions, a model catalogue and (by default) in-place model changes."""
    with session_scope() as db:
        row = db.get(AgentHost, host.id)
        caps = [*row.caps["caps"], "role.options", "spawn.roles", "managed.sessions", "trouble.reported",
                *(["input.model"] if change_model else [])]
        row.caps = {**row.caps, "caps": caps, "model_catalog": CATALOG,
                    "harnesses": {**row.caps["harnesses"], "claude": {**row.caps["harnesses"]["claude"], "managed": True}}}


def status(host, run_id, **extra):
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        coordinator.on_status(db, db.get(AgentSession, run.session_pk), agent_link.Status(
            surf=run.surf, incarnation=run.incarnation, state=extra.pop("frame_state", "idle"), since=now(), **extra),
            host_id=host.id)


def shown(run_id):
    with session_scope() as db:
        return control.public_run(db, db.get(AgentRun, run_id), detail=True)


def test_a_planner_whose_model_ran_out_carries_on_under_the_hosts_default(host):
    modern(host)
    run_id = start(host, task("Plan well")["id"], brainstorm=True)["id"]
    attached(host, run_id)
    with session_scope() as db:
        assert db.get(AgentRun, run_id).model == "claude-fable-5-2"
    # The failed turn ends like any other: the conversation reads it as the agent's reply.
    turn(run_id, 1)
    assert state(run_id) == ("needs_you", "brainstorm")
    status(host, run_id, trouble=LIMIT)

    sent = commands(run_id, "input")[-1].payload
    assert sent["model"] == "claude-opus-5-5" and "moved to another model" in sent["text"] and sent["mode"] == "queue"
    assert state(run_id) == ("planning", "model_fallback")
    out = shown(run_id)
    assert out["model"] == "claude-opus-5-5" and out["trouble"] is None
    assert out["model_fallback"] == {**out["model_fallback"], "from": "claude-fable-5-2", "to": "claude-opus-5-5",
                                     "why": "its usage ran out"}
    assert out["brainstorm"]["turns"] == 0  # The failed turn was not the agent's side of the conversation.
    with session_scope() as db:
        assert run_brainstorm.is_open(db.get(AgentRun, run_id))
    # The same report again changes nothing, and a second failure stops for the owner: one fallback per run.
    status(host, run_id, trouble=LIMIT)
    assert len([c for c in commands(run_id, "input") if c.payload.get("model")]) == 1
    status(host, run_id, trouble={**LIMIT, "since": 9})
    assert state(run_id) == ("needs_you", "rate_limited")
    assert "resets 3pm" in shown(run_id)["reason_detail"]


def test_a_model_the_account_cannot_use_also_falls_back(host):
    modern(host)
    run_id = start(host, task("Plan on a model I do not have")["id"])["id"]
    attached(host, run_id)
    turn(run_id, 1)
    assert state(run_id) == ("needs_you", "no_plan")
    status(host, run_id, trouble={"kind": "errored", "since": 3, "detail": "model_not_found: There is an issue with the selected model"})
    assert commands(run_id, "input")[-1].payload["model"] == "claude-opus-5-5"
    assert shown(run_id)["model_fallback"]["why"] == "this account cannot use it"
    assert state(run_id)[1] == "model_fallback"


def test_without_a_way_to_change_model_the_run_stops_and_says_why(host):
    modern(host, change_model=False)
    run_id = start(host, task("Older host")["id"])["id"]
    attached(host, run_id)
    turn(run_id, 1)
    status(host, run_id, trouble=LIMIT)
    assert state(run_id) == ("needs_you", "rate_limited")
    out = shown(run_id)
    assert out["trouble"]["kind"] == "rate_limited" and "resets 3pm" in out["reason_detail"]
    assert "ran out of usage" in out["attention_detail"]["headline"] and "another model" in out["attention_detail"]["action"]
    assert not [c for c in commands(run_id, "input") if c.payload.get("model")]


def test_signed_out_and_errors_stop_execution_instead_of_being_judged(host):
    made = task("Work it", success_criteria=[{"text": "Done"}], verify={"target_id": host.target_id, "verify_id": "quick"})
    run_id = start(host, made["id"], interview=False)["id"]
    attached(host, run_id)
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        db.add(AgentAttempt(owner_id=run.owner_id, run_id=run_id, generation=run.generation, kind="verify", turn_seq=1, status="queued"))
    status(host, run_id, trouble={"kind": "auth_expired", "since": 1, "detail": "authentication_failed: Please run /login"})
    assert state(run_id) == ("needs_you", "auth_expired")
    with session_scope() as db:
        assert [a.status for a in db.query(AgentAttempt).filter_by(run_id=run_id)] == ["superseded"]
    assert "Sign in again" in shown(run_id)["attention_detail"]["action"]
    # The owner fixes it and messages the agent: the run resumes, and new work clears the trouble.
    with session_scope() as db:
        control.send_message(db, run.owner_id, run_id, control.MessageInput(text="Signed in again, carry on."), actor=control.Actor("human"))
    status(host, run_id, frame_state="working")
    assert shown(run_id)["trouble"] is None and state(run_id)[0] == "executing"
    status(host, run_id, trouble={"kind": "errored", "since": 5, "detail": "http_500: upstream error"})
    assert state(run_id) == ("needs_you", "agent_errored") and "http_500" in shown(run_id)["reason_detail"]
