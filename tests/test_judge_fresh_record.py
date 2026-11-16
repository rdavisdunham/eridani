"""The judge asks the host for a fresh record when the one it has predates the turn (agent_judge.fresh_record).

Found by the sandbox pull-request smoke test: an agent had committed, pushed and opened a pull request, the judge
read a host report from before the work, sent the agent back three times for work already done, then gave up."""

from datetime import timedelta

from jarvis import agent_judge as judge
from jarvis.db import session_scope
from jarvis.models import now
from jarvis.session_models import AgentAttempt, AgentHost, AgentRun
from test_agent_plan import start
from test_agent_runs import OWNER, attached, commands, quiet, task  # noqa: F401 - pytest fixtures
from test_agent_runs import host as host  # noqa: F401 - pytest fixture


def judged(host, *, report_age, scan=True):
    """A run with a queued judge attempt (no turn row: the attempt's own time stands in for the turn's); the host's
    last worktrees report is `report_age` old (None: it never sent one; negative: it came after the turn)."""
    run_id = start(host, task("Add a greeting")["id"], interview=False)["id"]
    attached(host, run_id)
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        run.branch = "task/greeting"
        attempt = AgentAttempt(owner_id=OWNER, run_id=run_id, generation=run.generation, kind="judge", turn_seq=1)
        db.add(attempt)
        row = db.get(AgentHost, run.host_id)
        caps = dict(row.caps or {})
        caps["caps"] = sorted({*(caps.get("caps") or []), "worktrees.scan"} if scan else set(caps.get("caps") or []) - {"worktrees.scan"})
        if report_age is None:
            caps.pop("worktrees", None)
        else:
            caps["worktrees"] = {"at": (now() - report_age).isoformat(), "worktrees": []}
        row.caps = caps
        db.flush()
        return run_id, attempt.id


def report_arrives(run_id):
    def sleep(_):
        with session_scope() as db:
            row = db.get(AgentHost, db.get(AgentRun, run_id).host_id)
            row.caps = {**row.caps, "worktrees": {"at": (now() + timedelta(seconds=5)).isoformat(), "worktrees": []}}
    return sleep


def test_a_record_older_than_the_turn_is_refreshed_before_judging(host):
    run_id, attempt_id = judged(host, report_age=timedelta(minutes=3))
    with session_scope() as db:
        assert judge.record_behind(db, db.get(AgentAttempt, attempt_id)) is True
    waited = judge.fresh_record(attempt_id, sleep=report_arrives(run_id))
    assert waited == 1.0  # It went on as soon as the report was newer than the turn.
    asked = commands(run_id, "worktrees.scan")
    assert len(asked) == 1 and asked[0].payload["branch"] == "task/greeting"
    with session_scope() as db:
        attempt = db.get(AgentAttempt, attempt_id)
        assert attempt.result["record_scan"] == asked[0].op_id and judge.record_behind(db, attempt) is False
    assert judge.fresh_record(attempt_id, sleep=lambda _: None) == 0.0 and len(commands(run_id, "worktrees.scan")) == 1


def test_a_record_newer_than_the_turn_is_used_as_it_is(host):
    run_id, attempt_id = judged(host, report_age=timedelta(seconds=-5))
    assert judge.fresh_record(attempt_id, sleep=lambda _: None) == 0.0
    assert commands(run_id, "worktrees.scan") == []


def test_the_wait_is_bounded_and_an_older_host_is_not_asked(host):
    run_id, attempt_id = judged(host, report_age=None)
    assert judge.fresh_record(attempt_id, timeout=3, sleep=lambda _: None) == 3.0  # No answer: judged on what there is.
    assert len(commands(run_id, "worktrees.scan")) == 1
    other, old_attempt = judged(host, report_age=timedelta(minutes=3), scan=False)
    assert judge.fresh_record(old_attempt, sleep=lambda _: None) == 0.0 and commands(other, "worktrees.scan") == []


def test_the_judge_is_told_a_stale_record_is_not_evidence_of_missing_work():
    assert "never send the agent back for it" in judge.SYSTEM and judge.PROMPT_VERSION == "judge-v8"
