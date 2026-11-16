"""A run whose stop the host never confirmed can be closed by the owner once the computer is offline.

Found on the sandbox: smoke-test runs sat in `stopping` for good after their throwaway host went away, holding their
tasks. Stop settles only on the host's confirmation; a retired or re-paired computer never gives it."""

from jarvis import agent_control as control
from jarvis.db import session_scope
from jarvis.session_models import AgentRun
from test_agent_plan import start
from test_agent_runs import HUMAN, OWNER, attached, quiet, task  # noqa: F401 - pytest fixtures
from test_agent_runs import host as host  # noqa: F401 - pytest fixture


def stopping(host):
    made = task("Fix the upload retry")
    run_id = start(host, made["id"], interview=False)["id"]
    attached(host, run_id)
    with session_scope() as db:
        control.stop_run(db, OWNER, run_id, control.StopInput(mode="kill"), actor=HUMAN)
        assert db.get(AgentRun, run_id).state == "stopping"
    return made["id"], run_id


def test_closing_is_refused_while_the_computer_can_still_answer(host, client):
    _, run_id = stopping(host)
    refused = client.post(f"/api/v1/remotea/runs/{run_id}/stop/close", json={})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "HOST_ONLINE"
    with session_scope() as db:
        assert db.get(AgentRun, run_id).state == "stopping"


def test_the_owner_closes_a_run_whose_computer_is_gone_and_the_task_is_free_again(host, client, monkeypatch):
    task_id, run_id = stopping(host)
    monkeypatch.setattr("jarvis.agent_link.connected", lambda host, clock=None: False)
    done = client.post(f"/api/v1/remotea/runs/{run_id}/stop/close", json={})
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["state"], body["state_reason"]) == ("stopped", "stop_unconfirmed_closed")
    assert "without the computer confirming" in body["reason_text"]
    assert [h["actor"]["kind"] for h in body["history"] if h.get("event") == "stop_unconfirmed_closed"] == ["human"]
    # Only a stopping run; a second call finds it settled.
    assert client.post(f"/api/v1/remotea/runs/{run_id}/stop/close", json={}).status_code == 409
    # The task is no longer held by the dead run.
    with session_scope() as db:
        assert control.coordinator_active(db, task_id) is None
