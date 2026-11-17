"""Ideate: ideas for a repository before any task exists, and tasks from the ones the owner picks (run_ideas.py)."""

import pytest
from jarvis import agent_control as control
from jarvis import run_brainstorm, run_ideas
from jarvis.db import session_scope
from jarvis.domain import DomainError
from jarvis.models import Job, Task
from jarvis.session_models import AgentRun, AgentTurn
from sqlalchemy import select
from test_agent_plan import turn
from test_agent_runs import HUMAN, OWNER, attached, commands, quiet  # noqa: F401 - pytest fixtures
from test_agent_runs import host as host  # noqa: F401 - pytest fixture

FOUND = run_ideas.Answer(ideas=[
    run_ideas.Idea(title="Retry failed uploads", summary="Uploads give up on the first error.", why="Most support tickets.", size="small"),
    run_ideas.Idea(title="Show upload progress", summary="A bar in the uploader.", why="People cancel long uploads.", size="medium"),
])


def session(host, monkeypatch, topic="Ways to make uploads less painful"):
    monkeypatch.setattr(run_ideas, "enabled", lambda: True)
    with session_scope() as db:
        run = run_ideas.start(db, OWNER, host.account_id, run_ideas.IdeasInput(topic=topic, execution_target_id=host.target_id),
                              actor=HUMAN)
    attached(host, run["id"])
    return run["id"]


def says(run_id, seq, text):
    """The agent's turn ends with this message."""
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        db.add(AgentTurn(owner_id=OWNER, run_id=run_id, session_pk=run.session_pk, host_id=run.host_id, provider_session_id="s",
                         provider_turn_id=f"t{seq}", generation=run.generation, seq=seq, role="assistant", text=text))
    turn(run_id, seq)


def read(run_id, answer):
    with session_scope() as db:
        job = db.scalar(select(Job.id).where(Job.kind == run_ideas.KIND, Job.status == "queued",
                                             Job.payload["run_id"].astext == run_id))
    assert job, "no ideas job was queued"
    seen = []
    run_ideas.process(job, model=lambda body: (seen.append(body), answer)[1])
    return seen


def ideas(run_id):
    with session_scope() as db:
        return control.public_run(db, db.get(AgentRun, run_id), detail=True)["ideas"]


def test_an_ideas_session_is_a_conversation_about_a_repository_with_a_holding_task(host, monkeypatch):
    run_id = session(host, monkeypatch)
    prompt = commands(run_id, "spawn")[0].payload["prompt"]
    assert "ideas session" in prompt and "Ways to make uploads less painful" in prompt and "reject most" in prompt
    assert "submit_plan (expected_plan_revision" not in prompt
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        task = db.get(Task, run.task_id)
        assert task.title == "Ideas: Ways to make uploads less painful" and task.run_route == "human"
        assert run_brainstorm.public(run) == {**run_brainstorm.public(run), "open": True, "kind": "ideate"}
        with pytest.raises(DomainError):
            run_brainstorm.plan_it(db, run, actor=HUMAN)  # Nothing to plan: ideas become tasks.
    assert ideas(run_id) == {"state": None, "items": [], "read_seq": None}


def test_the_agents_ideas_become_a_checklist_and_chosen_ones_become_tasks(host, monkeypatch, client):
    run_id = session(host, monkeypatch)
    says(run_id, 1, "1. **Retry failed uploads** ...\n2. **Show upload progress** ...\nWhich should I take further?")
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        assert (run.state, run.state_reason) == ("needs_you", "brainstorm")
    assert ideas(run_id)["state"] == "reading"
    seen = read(run_id, FOUND)
    assert "Retry failed uploads" in seen[0]["messages"][1]["content"]
    listed = ideas(run_id)
    assert listed["state"] == "ready" and [i["title"] for i in listed["items"]] == ["Retry failed uploads", "Show upload progress"]
    first = listed["items"][0]

    made = client.post(f"/api/v1/remotea/runs/{run_id}/ideas/tasks", json={"idea_ids": [first["id"]]})
    assert made.status_code == 200, made.text
    created = made.json()["created"]
    assert [c["title"] for c in created] == ["Retry failed uploads"]
    with session_scope() as db:
        task = db.get(Task, created[0]["task_id"])
        assert task.execution_target_id == host.target_id
        assert "Uploads give up on the first error." in task.notes and "Why: Most support tickets." in task.notes
        assert "Rough size: small" in task.notes and "From an ideas session (Ways to make uploads less painful)" in task.notes
    # Choosing it again makes nothing new; an idea that is not on the list is refused.
    again = client.post(f"/api/v1/remotea/runs/{run_id}/ideas/tasks", json={"idea_ids": [first["id"]]})
    assert again.json()["created"] == [] and again.json()["ideas"]["items"][0]["task_id"] == created[0]["task_id"]
    assert client.post(f"/api/v1/remotea/runs/{run_id}/ideas/tasks", json={"idea_ids": ["i_nope"]}).status_code == 404


def test_steering_replaces_the_list_but_keeps_what_was_made_into_a_task(host, monkeypatch):
    run_id = session(host, monkeypatch)
    says(run_id, 1, "two ideas")
    read(run_id, FOUND)
    kept = ideas(run_id)["items"][0]["id"]
    with session_scope() as db:
        run_ideas.make_tasks(db, OWNER, run_id, run_ideas.MakeTasksInput(idea_ids=[kept]), actor=HUMAN)
        control.send_message(db, OWNER, run_id, control.MessageInput(text="Smaller ones please."), actor=HUMAN)
    says(run_id, 2, "1. **Clearer error text** ...")
    read(run_id, run_ideas.Answer(ideas=[run_ideas.Idea(title="Clearer error text", summary="Say what failed.", size="small")]))
    items = ideas(run_id)["items"]
    assert [(i["title"], bool(i.get("task_id"))) for i in items] == [("Clearer error text", False), ("Retry failed uploads", True)]
    # A message that proposes nothing (a question) leaves the list as it was.
    with session_scope() as db:
        control.send_message(db, OWNER, run_id, control.MessageInput(text="Tell me more about the first."), actor=HUMAN)
    says(run_id, 3, "It would change the error banner. Want me to go on?")
    read(run_id, run_ideas.Answer(ideas=[]))
    assert [i["title"] for i in ideas(run_id)["items"]] == ["Clearer error text", "Retry failed uploads"]


def test_starting_from_the_route_needs_a_topic_and_a_repository(host, client):
    assert client.post("/api/v1/remotea/ideas", json={"topic": ""}).status_code == 400
    assert client.post("/api/v1/remotea/ideas", json={"topic": "Uploads"}).status_code == 400
    started = client.post("/api/v1/remotea/ideas", json={"topic": "Uploads", "execution_target_id": host.target_id})
    assert started.status_code == 200, started.text
    assert started.json()["brainstorm"]["kind"] == "ideate"
