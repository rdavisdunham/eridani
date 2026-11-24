"""Exercise owner enrollment and managed Glass sends against a disposable linked run."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from jarvis import agent_receipts
from jarvis.db import session_scope
from jarvis.session_models import AgentCommand, AgentHost, AgentRun, AgentSession
from test_agent_runs import attached, host, quiet, start, task  # noqa: F401 - fixtures
from test_glassface_dani import key

STATUS = "/api/glassface/managed-messages/status"


@pytest.fixture
def fixture(host, client):
    run_id = start(host, task()["id"])["id"]
    attached(host, run_id)
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        run.sync_state = {**run.sync_state, "execution_mode": "managed"}
        server = db.get(AgentHost, run.host_id)
        server.caps = {**server.caps, "caps": [*server.caps["caps"], "commands.durable", "input.direct"]}
        session = db.get(AgentSession, run.session_pk)
        session.incarnation, session.surf, session.state = run.incarnation, run.surf, "idle"
        body = {"server_id": server.server_id, "surf": run.surf, "incarnation": run.incarnation,
                "generation": run.generation, "action_id": str(uuid4()), "text": "What is left on this fixture?"}
    _, headers = key(client, ["glassface:message"])
    return run_id, f"/api/glassface/runs/{run_id}/messages", body, headers


def test_dedicated_opt_in(client, host):
    for scope in ("glassface:dani", "agents:control", "agents:read"):
        _, headers = key(client, [scope])
        assert client.get(STATUS, headers=headers).status_code == 403
        assert client.post("/api/v1/bot-keys", json={"name": "mixed", "scopes": ["glassface:message", scope]}).status_code == 400
    credential, headers = key(client, ["glassface:message"])
    assert client.get(STATUS, headers=headers).json() == {"ready": True}
    assert client.get("/api/glassface/dani/status", headers=headers).status_code == 403
    client.post(f"/api/v1/bot-keys/{credential}/revoke")
    assert client.get(STATUS, headers=headers).status_code == 401


def test_managed_replay_and_provenance(client, fixture):
    run_id, url, body, headers = fixture
    first = client.post(url, json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json() == {"run_id": run_id, "action_id": body["action_id"], "status": "queued"}
    with session_scope() as db:
        row = db.get(AgentRun, run_id)
        assert row.history[-1]["actor"]["kind"] == "bot"
        assert row.history[-1]["text"] == body["text"]
        row.paused = True
    assert client.post(url, json=body, headers=headers).json() == first.json()
    assert client.post(url, json={**body, "text": "a changed request"}, headers=headers).status_code == 409
    with session_scope() as db:
        cmd, = db.scalars(select(AgentCommand).where(AgentCommand.action_id == body["action_id"]))
        assert (cmd.host_id, cmd.generation, cmd.run_id) == (row.host_id, body["generation"], run_id)
        assert cmd.status == "queued"
        assert {k: cmd.payload[k] for k in ("text", "mode", "origin", "surf", "incarnation")} == {
            "text": body["text"], "mode": "queue", "origin": "automation", "surf": body["surf"], "incarnation": body["incarnation"]}
        assert agent_receipts.lookup(db, row.owner_id, body["action_id"])["status"] == "queued"


def test_refuses_changed_target_controls_and_takeover(client, fixture):
    run_id, url, body, headers = fixture
    for patch, status in (({"generation": 12}, 409), ({"incarnation": 7}, 409), ({"surf": "other"}, 409),
                          ({"server_id": "other"}, 404), ({"mode": "direct"}, 422), ({"text": "\x1bexit"}, 422)):
        assert client.post(url, headers=headers, json={**body, **patch}).status_code == status
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        run.sync_state = {**run.sync_state, "controller": "terminal"}
    assert client.post(url, json=body, headers=headers).status_code == 409
    with session_scope() as db:
        run = db.get(AgentRun, run_id)
        run.sync_state = {"execution_mode": "managed"}
        run.state = "awaiting_approval"
    assert client.post(url, json={**body, "text": "approved"}, headers=headers).status_code == 409
    with session_scope() as db:
        assert not db.scalar(select(AgentCommand).where(AgentCommand.action_id == body["action_id"]))


def test_paired_host_gets_one_input_and_records_outcome(client, host, fixture):
    from jarvis.agent_link import digest
    from test_agent_link import bearer, connect, frame, hello, put, signed
    from test_agent_runs import CAPS, HARNESSES

    run_id, url, body, headers = fixture
    with session_scope() as db:
        # The fixture's setup models a host that has already handled the spawn and initial task.
        for command in db.scalars(select(AgentCommand).where(AgentCommand.run_id == run_id)):
            command.status = "executed"
    with connect(bearer(host.token)) as ws:
        hello(ws, caps=[*CAPS, "commands.durable", "input.direct"], harnesses=HARNESSES)
        snapshot = signed("sessions.snapshot", surfaces=[{
            "run_id": run_id, "generation": body["generation"], "surf": body["surf"],
            "incarnation": body["incarnation"], "state": "idle", "provider": "claude", "provider_session_id": "sess-1",
            "execution": "managed", "controller": "eridani"}], journal={"pending": [], "uncertain": []})
        ws.send_json(snapshot)
        assert ws.receive_json()["t"] == "runs.snapshot"
        assert ws.receive_json()["acked_id"] == snapshot["id"]
        result = client.post(url, headers=headers, json=body)
        assert result.status_code == 200, result.text
        cmd = ws.receive_json()
        assert cmd["t"] == "input" and cmd["digest"] == digest(cmd)
        assert (cmd["run_id"], cmd["generation"], cmd["surf"], cmd["incarnation"], cmd["text"]) == (
            run_id, body["generation"], body["surf"], body["incarnation"], body["text"])
        ws.send_json(frame("ack", acked_id=cmd["id"], op_id=cmd["op_id"], ok=True, outcome={"state": "accepted"}))
        put(ws, "command.outcome", command_id=cmd["op_id"], state="executed", kind="input", result={"mode": "queue"})
        assert client.post(url, headers=headers, json=body).json() == result.json()
    with session_scope() as db:
        saved = agent_receipts.lookup(db, "davin", body["action_id"])
        assert saved["status"] == "delivered"
        assert [c["op_id"] for c in saved["commands"]] == [cmd["op_id"]]
