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


def test_the_summary_goes_out_once_per_slot_and_only_when_something_waits(host):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from jarvis.domain import preferences
    from jarvis.models import Notification
    from sqlalchemy import select

    with session_scope() as db:
        zone = ZoneInfo(preferences(db, OWNER)["timezone"])
    at = datetime(2026, 11, 17, 9, 20, tzinfo=zone)
    with session_scope() as db:
        assert needs_you.summary(db, OWNER, at) is None  # Nothing waits: no notice.
    done = start(host, task("Rename the helper")["id"])["id"]
    attached(host, done)
    parked(done, "awaiting_approval")
    with session_scope() as db:
        assert needs_you.summary(db, OWNER, datetime(2026, 11, 17, 8, 59, tzinfo=zone)) is None  # Not a slot.
        row = needs_you.summary(db, OWNER, at)
        assert row.title == "1 thing needs you" and "Accept the finished work: Rename the helper" in row.body
        assert row.target == {"view": "needs", "keys": [f"run:{done}"]}
        assert needs_you.summary(db, OWNER, at) is None  # Once per slot.
        assert needs_you.still_current(db, row)
    parked(done, "completed")
    with session_scope() as db:
        row = db.scalar(select(Notification).where(Notification.category == "needs_you"))
        assert not needs_you.still_current(db, row)  # Decided before it went out: dropped.


def test_the_summary_can_be_turned_off_and_its_times_changed(client):
    assert client.get("/api/v1/bootstrap").json()["preferences"]["needs_you_times"] == ["09:00", "17:00"]
    out = client.post("/api/v1/commands", json={"command_id": "4c1c6a3e-5b0f-4b55-9a7e-0c2b2d1e9f01", "tool": "settings.update",
                                                "arguments": {"needs_you_summary": False, "needs_you_times": ["08:30"]}})
    assert out.status_code == 200, out.text
    prefs = client.get("/api/v1/bootstrap").json()["preferences"]
    assert prefs["needs_you_summary"] is False and prefs["needs_you_times"] == ["08:30"]
    bad = client.post("/api/v1/commands", json={"command_id": "4c1c6a3e-5b0f-4b55-9a7e-0c2b2d1e9f02", "tool": "settings.update",
                                                "arguments": {"needs_you_times": ["25:00"]}})
    assert bad.status_code in (400, 422)


def test_a_meeting_with_proposals_sends_the_summary_once_between_set_times(host, monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from jarvis.domain import preferences

    with session_scope() as db:
        zone = ZoneInfo(preferences(db, OWNER)["timezone"])
    at = datetime(2026, 11, 17, 14, 0, tzinfo=zone)  # Between the 09:00 and 17:00 summaries.
    ready = []

    def meetings(db, owner, account, device):
        return [needs_you.item("meeting", f"meeting:{sid}", title, "Review 2 proposals from this meeting",
                               since=since, source_id=sid) for sid, title, since in ready]

    monkeypatch.setattr(needs_you, "meetings", meetings)
    with session_scope() as db:
        assert needs_you.summary(db, OWNER, at) is None  # No meeting: nothing until 17:00.
    ready += [("m-old", "Monday sync", at - timedelta(hours=9)), ("m-1", "Pricing review", at - timedelta(minutes=50)),
              ("m-2", "Design crit", at - timedelta(minutes=20))]
    with session_scope() as db:
        row = needs_you.summary(db, OWNER, at)
        # One notice for both new meetings; the one from this morning is left to the set times.
        assert row.title == "3 things need you" and row.target["meetings"] == ["m-2", "m-1"]
        assert needs_you.summary(db, OWNER, at + timedelta(minutes=5)) is None  # Already announced.
    ready.append(("m-3", "Client call", at + timedelta(minutes=10)))
    with session_scope() as db:
        assert needs_you.summary(db, OWNER, at + timedelta(minutes=20)) is None  # Too soon after the last one.
        later = needs_you.summary(db, OWNER, at + timedelta(minutes=40))
        assert later.target["meetings"] == ["m-3"]
    ready.append(("m-4", "Retro", at + timedelta(minutes=50)))
    with session_scope() as db:  # Turned off: only the set times.
        from uuid import uuid4

        from jarvis.domain import execute

        execute(db, OWNER, str(uuid4()), "settings.update", {"needs_you_after_meetings": False})
    with session_scope() as db:
        assert needs_you.summary(db, OWNER, at + timedelta(minutes=90)) is None
