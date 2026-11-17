"""Dani carries a brainstorm: start with "talk it through", relay the conversation, "plan it", pick ideas.

The conversation lives on the run, so voice, chat and the run page are one thread (agent_control.conversation)."""

import asyncio

from jarvis import agent_control as control
from jarvis import run_brainstorm, run_ideas
from jarvis.db import session_scope
from jarvis.session_models import AgentPendingControl, AgentRun, AgentTurn
from jarvis.tool_catalog import DESCRIPTIONS, GROUPS
from jarvis.tool_policy import CONTROL_TOOLS
from jarvis.tools import call_tool, registry
from sqlalchemy import select
from test_agent_plan import turn
from test_agent_runs import HUMAN, OWNER, attached, commands, quiet, task  # noqa: F401 - pytest fixtures
from test_agent_runs import host as host  # noqa: F401 - pytest fixture
from test_agent_voice import confirm, default_target, say


def agent_says(run_id, seq, text):
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        db.add(AgentTurn(owner_id=OWNER, run_id=run_id, session_pk=run.session_pk, host_id=run.host_id, provider_session_id="s",
                         provider_turn_id=f"t{seq}", generation=run.generation, seq=seq, role="assistant", text=text))
    turn(run_id, seq)


def status(run_id):
    out = asyncio.run(call_tool(OWNER, "turn-s", 0, "control_status", {"run_id": run_id}))
    return next(r for r in out["runs"] if r["run_id"] == run_id)


def test_dani_offers_to_talk_an_unshaped_task_through_and_the_new_proposal_replaces_the_old(host):
    made = task("Make the greeting friendlier")
    default_target(host, made["id"])
    first = say("control.start", task_id=made["id"])
    assert "talk it through" in first["offer"] and "talking it through" not in first["summary"]
    second = say("control.start", task_id=made["id"], brainstorm=True)
    assert "talking it through with you before it plans" in second["summary"] and "offer" not in second
    with session_scope() as db:
        rows = {r.id: (r.status, r.decided_via) for r in db.scalars(select(AgentPendingControl))}
    assert rows[first["pending_id"]] == ("declined", "replaced") and rows[second["pending_id"]][0] == "pending"
    run_id = confirm(second)["id"]
    assert "ONE question per turn" in commands(run_id, "spawn")[0].payload["prompt"]
    with session_scope() as db:
        assert run_brainstorm.is_open(db.get(AgentRun, run_id))
    # A task someone already shaped gets no offer.
    shaped = task("Rename a helper", success_criteria=[{"text": "The helper is renamed"}])
    default_target(host, shaped["id"])
    assert "offer" not in say("control.start", task_id=shaped["id"])


def test_the_conversation_is_one_thread_for_voice_chat_and_the_run_page(host):
    made = task("Make the greeting friendlier")
    default_target(host, made["id"])
    run_id = confirm(say("control.start", task_id=made["id"], brainstorm=True))["id"]
    attached(host, run_id)
    assert status(run_id)["conversation"]["waiting_for_owner"] is False  # The agent is still reading.
    agent_says(run_id, 1, "I read the code. Do you want it (A) short or (B) warm?")
    spoken = status(run_id)
    talk = spoken["conversation"]
    assert talk["waiting_for_owner"] and talk["agent_said"].endswith("(B) warm?") and "control_plan_it" in talk["next"]
    assert "review_packet" not in spoken  # Nothing to approve or review yet.

    # The owner answers by typing on the run page; Dani then knows what they said and hears the agent's reply.
    with session_scope() as db:
        control.send_message(db, OWNER, run_id, control.MessageInput(text="B, but one line."), actor=HUMAN)
    assert status(run_id)["conversation"]["owner_last_said"] == "B, but one line."

    async def reply():
        waiting = asyncio.create_task(run_brainstorm.reply_after(run_id, 1, timeout=5, step=0.05))
        await asyncio.sleep(0.2)
        await asyncio.to_thread(agent_says, run_id, 2, "What we're building: one warm line. Shall I plan it?")
        return await waiting
    heard = asyncio.run(reply())
    assert heard["waiting_for_owner"] and heard["agent_said"].startswith("What we're building") and heard["turns"] == 2

    # "Plan it", by voice: the conversation closes and the agent is asked for the plan.
    done = say("control.plan_it", run_id=run_id)
    assert done["status"] == "planning" and "plan_approval" in done["next"]
    assert "ready for the plan" in commands(run_id, "input")[-1].payload["text"]
    assert "conversation" not in status(run_id)
    over = asyncio.run(run_brainstorm.reply_after(run_id, 2, timeout=1, step=0.05))
    assert over["over"] is True


def test_a_slow_agent_is_reported_as_still_thinking(host):
    made = task("Make the greeting friendlier")
    default_target(host, made["id"])
    run_id = confirm(say("control.start", task_id=made["id"], brainstorm=True))["id"]
    attached(host, run_id)
    agent_says(run_id, 1, "First question?")
    with session_scope() as db:
        control.send_message(db, OWNER, run_id, control.MessageInput(text="Answer."), actor=HUMAN)
    late = asyncio.run(run_brainstorm.reply_after(run_id, 1, timeout=0.2, step=0.05))
    assert late["waiting_for_owner"] is False and late["agent_said"] is None and "still thinking" in late["next"]


def test_ideas_are_numbered_for_dani_and_the_owner_picks_by_number(host, monkeypatch):
    monkeypatch.setattr(run_ideas, "enabled", lambda: False)
    with session_scope() as db:
        run_id = run_ideas.start(db, OWNER, host.account_id, run_ideas.IdeasInput(
            topic="Uploads", execution_target_id=host.target_id), actor=HUMAN)["id"]
    attached(host, run_id)
    agent_says(run_id, 1, "1. Retry uploads 2. Show progress. Which?")
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        run_ideas.save(run, state="ready", items=run_ideas.merge([], [
            run_ideas.Idea(title="Retry failed uploads", summary="s", why="w", size="small"),
            run_ideas.Idea(title="Show upload progress", summary="s", why="w", size="medium")], 1))
    talk = status(run_id)["conversation"]
    assert talk["kind"] == "ideate" and "control_ideas_tasks" in talk["next"]
    assert [(i["number"], i["title"], i["made_a_task"]) for i in talk["ideas"]] == [
        (1, "Retry failed uploads", False), (2, "Show upload progress", False)]
    made = say("control.ideas_tasks", run_id=run_id, numbers=[2])
    assert [c["title"] for c in made["created"]] == ["Show upload progress"]
    assert status(run_id)["conversation"]["ideas"][1]["made_a_task"] is True
    import pytest
    from jarvis.domain import DomainError
    with pytest.raises(DomainError):
        say("control.ideas_tasks", run_id=run_id, numbers=[5])
    with pytest.raises(DomainError):
        say("control.plan_it", run_id=run_id)  # An ideas session ends in tasks, not a plan.


def test_the_new_tools_are_registered_described_grouped_and_gated():
    for name in ("control_plan_it", "control_ideas_tasks"):
        assert name in CONTROL_TOOLS and name in DESCRIPTIONS and name in GROUPS["agent_talks"][1]
        assert name in {d["name"] for d in registry()}
    start = next(d for d in registry() if d["name"] == "control_start")
    assert "brainstorm" in start["parameters"]["properties"] and "brainstorm true" in DESCRIPTIONS["control_start"]


def test_a_reply_sent_through_dani_comes_back_with_the_agents_answer(host, monkeypatch):
    """The whole tool call, as chat or voice makes it: an owner-origin request with the run named sends at once, and
    the result carries the agent's reply for Dani to read."""
    made = task("Make the greeting friendlier")
    default_target(host, made["id"])
    run_id = confirm(say("control.start", task_id=made["id"], brainstorm=True))["id"]
    attached(host, run_id)
    agent_says(run_id, 1, "Short or warm?")
    from types import SimpleNamespace

    monkeypatch.setattr(control, "current_work", lambda db: SimpleNamespace(id="w1", credential_id=None, account_id=OWNER))
    monkeypatch.setattr(control, "work_message", lambda row: "Warm.")

    async def talk():
        calling = asyncio.create_task(call_tool(OWNER, "turn-r", 0, "control_message", {"run_id": run_id, "text": "Warm."}))
        await asyncio.sleep(0.4)
        await asyncio.to_thread(agent_says, run_id, 2, "Then one warm line. Plan it?")
        return await calling
    out = asyncio.run(talk())
    assert commands(run_id, "input")[-1].payload["text"] == "Warm."
    assert out["data"]["conversation"]["agent_said"] == "Then one warm line. Plan it?", out["data"].get("conversation")


def test_a_start_proposal_names_the_planning_model_and_another_can_be_asked_for(host):
    from test_planning_depth import offers

    offers(host, managed=True)
    made = task("Rework uploads", success_criteria=[{"text": "Done"}])
    default_target(host, made["id"])
    first = say("control.start", task_id=made["id"])
    assert "claude-fable-5-2 planning" in first["summary"]
    assert first["planner"]["model"] == "claude-fable-5-2" and first["planner"]["chosen_by"] == "default"
    assert "claude-opus-5-5" in [m["model"] for m in first["planner"]["others"]] and "another" in first["planner"]["say"]
    # The owner names another: the new proposal replaces the first, and their yes starts it on that model.
    second = say("control.start", task_id=made["id"], model="claude-opus-5-5")
    assert "claude-opus-5-5 planning" in second["summary"] and second["planner"]["say"] is None
    run_id = confirm(second)["id"]
    with session_scope() as db:
        assert db.get(AgentRun, run_id).model == "claude-opus-5-5"
