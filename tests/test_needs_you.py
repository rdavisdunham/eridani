"""The one "Needs you" list (needs_you.py): every waiting decision, each with its decision, recommendation, evidence
and what accepting does, urgent first; sources that do not apply are skipped, and one failing source hides nothing."""

import asyncio

from jarvis import needs_you
from jarvis.db import session_scope
from jarvis.models import now
from jarvis.session_models import AgentRun
from jarvis.tools import call_tool
from test_agent_runs import OWNER, attached, quiet, task  # noqa: F401 - pytest fixtures
from test_agent_runs import host as host  # noqa: F401 - pytest fixture
from test_agent_plan import start
from test_review_questions import setup_question


def parked(run_id, state, reason="", summary=""):
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        run.state, run.state_reason, run.summary, run.state_since = state, reason, summary, now()


def test_runs_proposals_and_questions_come_back_as_one_list_with_what_to_decide(host, client):
    done = start(host, task("Rename the helper")["id"])["id"]
    attached(host, done)
    parked(done, "awaiting_approval", summary="Renamed it and updated the four callers.")
    broken = start(host, task("Fix uploads")["id"])["id"]
    attached(host, broken)
    parked(broken, "needs_you", "host_offline")
    setup_question("field")

    out = client.get("/api/v1/needs-you").json()
    assert out["unavailable"] == [] and out["counts"]["run"] == 2 and out["counts"]["question"] == 1
    first, *rest = out["items"]
    # An offline computer blocks work, so it comes first; it has no single accept, only what to do.
    assert first["run_id"] == broken and first["urgent"] and first["accept"] is None
    assert "offline" in first["decision"].lower() and first["recommendation"]
    approve = next(i for i in rest if i.get("run_id") == done)
    assert approve["decision"] == "Accept the finished work"
    assert approve["evidence"] == ["Renamed it and updated the four callers."]
    assert approve["accept"]["kind"] == "final_acceptance" and "approve" in approve["accept"]["actions"]
    assert "task is completed" in approve["if_accepted"] and approve["open"] == {"view": "remotea", "run_id": done}
    question = next(i for i in rest if i["kind"] == "question")
    assert question["title"] == "Does Client mean a company or a person?" and question["open"] == {"view": "questions"}


def test_a_failing_source_is_named_and_the_others_still_show(host, monkeypatch):
    done = start(host, task("Rename the helper")["id"])["id"]
    attached(host, done)
    parked(done, "awaiting_approval")
    monkeypatch.setattr(needs_you, "questions", lambda *a: 1 / 0)
    with session_scope() as db:
        out = needs_you.listing(db, OWNER)
    assert out["unavailable"] == ["questions"] and [i["run_id"] for i in out["items"]] == [done]


def test_nothing_from_remotea_while_it_is_off(client):
    setup_question("memory")
    out = client.get("/api/v1/needs-you").json()
    assert [i["kind"] for i in out["items"]] == ["question"] and out["unavailable"] == []


def test_dani_reads_the_list_urgent_first(host):
    broken = start(host, task("Fix uploads")["id"])["id"]
    attached(host, broken)
    parked(broken, "needs_you", "host_offline")
    out = asyncio.run(call_tool(OWNER, "turn-n", 0, "needs_you", {}))
    assert out["total"] == 1 and out["urgent"] == 1
    assert out["items"][0]["run_id"] == broken and "urgent" in out["next"]
