"""Planning depth: a planner runs on the strongest model the host offers, and its prompts point at the host's
Compound Engineering skills when they are installed (agent_control.planning_default, agent_prompts.skill_note)."""

from jarvis import agent_control as control
from jarvis import agent_prompts as prompts
from jarvis import run_ideas
from jarvis.db import session_scope
from jarvis.session_models import AgentHost, AgentRun
from test_agent_plan import start
from test_agent_runs import HUMAN, OWNER, commands, quiet, task  # noqa: F401 - pytest fixtures
from test_agent_runs import host as host  # noqa: F401 - pytest fixture

CATALOG = [{"harness": "claude", "model": "claude-opus-5-5", "default": True}, {"harness": "claude", "model": "claude-fable-5-1"},
           {"harness": "claude", "model": "claude-fable-5-2"}, {"harness": "claude", "model": "claude-fable-5"},
           {"harness": "claude", "model": "sonnet"}, {"harness": "codex", "model": "gpt-6.1-sol", "default": True}]


def offers(host, *, managed):
    with session_scope() as db:
        row = db.get(AgentHost, host.id)
        caps = [*row.caps["caps"], "role.options", "spawn.roles", *(["managed.sessions"] if managed else [])]
        row.caps = {**row.caps, "caps": caps, "model_catalog": CATALOG,
                    "harnesses": {**row.caps["harnesses"], "claude": {**row.caps["harnesses"]["claude"], "managed": managed}}}


def models(run_id):
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        return run.model, ((run.roles or {}).get("worker") or {}).get("model")


def test_the_planning_default_is_the_newest_of_the_strongest_family_the_host_offers():
    assert control.planning_default(CATALOG, "claude") == "claude-fable-5-2"
    assert control.planning_default(CATALOG, "codex") is None
    assert control.planning_default([m for m in CATALOG if "fable" not in m["model"]], "claude") is None
    assert control.planning_default([], "claude") is None and control.planning_default(None, "claude") is None
    aliases = [{"harness": "claude", "model": "claude-sonnet-5-5", "default": True}, {"harness": "claude", "model": "fable"}]
    assert control.planning_default(aliases, "claude") == "fable"


def test_a_managed_run_plans_on_the_strongest_model_and_works_on_the_hosts_default(host):
    offers(host, managed=True)
    assert models(start(host, task("Plan well")["id"])["id"]) == ("claude-fable-5-2", "claude-opus-5-5")
    # A model the owner chose, for the planner or the worker, is never replaced.
    assert models(start(host, task("Chosen planner")["id"], model="sonnet")["id"]) == ("sonnet", "sonnet")
    chosen = start(host, task("Chosen worker")["id"], worker={"harness": "claude", "model": "sonnet"})["id"]
    assert models(chosen) == ("claude-fable-5-2", "sonnet")


def test_a_single_session_run_keeps_the_hosts_default_because_that_session_also_does_the_work(host):
    offers(host, managed=False)
    assert models(start(host, task("One session")["id"])["id"])[0] == "claude-opus-5-5"


def test_an_ideas_session_uses_the_strongest_model_unless_one_is_chosen(host, monkeypatch):
    offers(host, managed=True)
    with session_scope() as db:
        default = run_ideas.start(db, OWNER, host.account_id, run_ideas.IdeasInput(
            topic="Uploads", execution_target_id=host.target_id), actor=HUMAN)["id"]
        picked = run_ideas.start(db, OWNER, host.account_id, run_ideas.IdeasInput(
            topic="Onboarding", execution_target_id=host.target_id, model="sonnet"), actor=HUMAN)["id"]
    assert models(default)[0] == "claude-fable-5-2" and models(picked)[0] == "sonnet"


def test_the_catalogue_marks_what_a_planner_would_run_on(host, client):
    offers(host, managed=True)
    listed = client.get("/api/v1/remotea/model-catalog").json()["models"]
    assert [m["model"] for m in listed if m["planning_default"]] == ["claude-fable-5-2"]


def test_planning_prompts_point_at_the_installed_skill_with_the_three_adaptations(host):
    offers(host, managed=True)
    made = task("Make the greeting friendlier")
    talk = commands(start(host, made["id"], brainstorm=True)["id"], "spawn")[0].payload["prompt"]
    assert "ce-brainstorm" in talk and "compound-engineering:ce-brainstorm" in talk
    for needed in ("no blocking question tool", "cannot write or edit files", "Eridani is the handoff",
                   "YOUR FIRST ACTION", "WITHOUT THE SKILL (use this section", "sub-agents (the Agent tool) work", "ONE question per turn"):
        assert needed in talk, needed
    assert talk.index("ce-brainstorm") < talk.index("ONE question per turn")  # The skill first, the built-in method after.
    plan = commands(start(host, task("Rename a helper", success_criteria=[{"text": "Renamed"}],
                                     verify={"target_id": host.target_id, "verify_id": "quick"})["id"])["id"],
                    "spawn")[0].payload["prompt"]
    assert "ce-plan" in plan and "submit_plan, not as a file" in plan and "WITHOUT THE SKILL" not in plan
    assert "ce-plan" in prompts.brainstorm_plan() and "ce-work, lfg" in prompts.brainstorm_plan()
    ideas = prompts.ideate(type("T", (), {"title": "Uploads"})(), "Uploads")
    for needed in ("ce-ideate", "six different angles", "Search the web", "basis the operator can check"):
        assert needed in ideas, needed


def test_the_owner_chooses_what_plans_when_no_model_is_named(host, client):
    offers(host, managed=True)
    assert control.planning_default(CATALOG, "claude", "host") is None
    assert control.planning_default(CATALOG, "claude", "sonnet") == "sonnet"
    assert control.planning_default(CATALOG, "claude", "not-offered") == "claude-fable-5-2"  # Falls back to the strongest.
    assert client.get("/api/v1/remotea/status").json()["planner_model"] == "strongest"
    assert client.post("/api/v1/remotea/planner-model", json={"value": "sonnet"}).json()["planner_model"] == "sonnet"
    assert models(start(host, task("Plan on my pick")["id"])["id"]) == ("sonnet", "claude-opus-5-5")
    assert [m["model"] for m in client.get("/api/v1/remotea/model-catalog").json()["models"] if m["planning_default"]] == ["sonnet"]
    client.post("/api/v1/remotea/planner-model", json={"value": "host"})
    assert models(start(host, task("Plan on the usual")["id"])["id"]) == ("claude-opus-5-5", "claude-opus-5-5")
    assert client.post("/api/v1/remotea/planner-model", json={"value": "two words"}).status_code == 422
