"""Adding a repository from the app: propose over the link, then confirm what was shown (target_setup.py)."""

from test_agent_link import C_CAPS, bearer, connect, enable, frame, hello, signed
from test_agent_link import quiet  # noqa: F401 - pytest fixture

PROPOSAL = {"saved": False, "source": "harness", "target": {"id": "budget", "repo": "/home/davin/budget",
                                                          "base": "main", "verify": [{"id": "unit", "argv": ["python3", "-m", "unittest"]}]},
            "checks": [{"id": "unit", "status": "not_run", "needs_confirmation": True}], "ci": {"pull_request": False},
            "gate": "local"}


def ready(ws, caps):
    """Hello, then the snapshot both sides agree on: commands go out only after it."""
    host_id = hello(ws, caps=caps)["host_id"]
    snap = signed("sessions.snapshot", surfaces=[], journal={"pending": [], "uncertain": []})
    ws.send_json(snap)
    assert ws.receive_json()["t"] == "runs.snapshot"
    assert ws.receive_json()["acked_id"] == snap["id"]
    return host_id


def settle(ws, command, state="executed", result=None, detail=""):
    ws.send_json(frame("ack", acked_id=command["id"], op_id=command["op_id"], ok=True, outcome={"state": "accepted"}))
    message = frame("command.outcome", op_id=f"out-{command['op_id']}", command_id=command["command_id"], state=state,
                    detail=detail, kind="target.setup", **({"result": result} if result else {}))
    from jarvis import agent_link

    ws.send_json({**message, "digest": agent_link.digest(message)})
    assert ws.receive_json()["t"] == "ack"


def test_a_repository_is_proposed_then_saved_as_it_was_shown(client):
    token = enable(client)["token"]
    with connect(bearer(token)) as ws:
        host_id = hello(ws, caps=C_CAPS)["host_id"]
        old = client.post("/api/v1/remotea/target-setup", json={"host_id": host_id, "repo": "/home/davin/budget"})
        assert old.status_code == 409 and old.json()["error"]["code"] == "HOST_TOO_OLD"
    with connect(bearer(token)) as ws:
        host_id = ready(ws, C_CAPS + ["target.setup"])
        assert client.post("/api/v1/remotea/target-setup", json={"host_id": host_id, "repo": "budget"}).status_code == 422
        asked = client.post("/api/v1/remotea/target-setup", json={"host_id": host_id, "repo": "/home/davin/budget"})
        assert asked.status_code == 200, asked.text
        op_id = asked.json()["op_id"]
        assert not asked.json()["done"] and asked.json()["confirm"] is False
        # The same request again is the one already on its way; another repository waits.
        assert client.post("/api/v1/remotea/target-setup", json={"host_id": host_id, "repo": "/home/davin/budget"}).json()["op_id"] == op_id
        busy = client.post("/api/v1/remotea/target-setup", json={"host_id": host_id, "repo": "/home/davin/other"})
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "BUSY"
        command = ws.receive_json()
        assert command["t"] == "target.setup" and command["repo"] == "/home/davin/budget" and command["confirm"] is False
        assert "owner_id" not in command and "run_id" not in command
        early = client.post(f"/api/v1/remotea/target-setup/{op_id}/confirm")
        assert early.status_code == 409 and early.json()["error"]["code"] == "NOT_A_PROPOSAL"
        settle(ws, command, result=PROPOSAL)
        shown = client.get(f"/api/v1/remotea/target-setup/{op_id}").json()
        assert shown["done"] and shown["status"] == "executed" and shown["result"]["target"]["id"] == "budget"

        saved = client.post(f"/api/v1/remotea/target-setup/{op_id}/confirm")
        assert saved.status_code == 200, saved.text
        confirm = ws.receive_json()
        # What was shown goes back as it was: the host does not read the repository again.
        assert confirm["t"] == "target.setup" and confirm["confirm"] is True and confirm["proposal"] == op_id
        assert confirm["target"] == PROPOSAL["target"] and confirm["repo"] == "/home/davin/budget"
        settle(ws, confirm, result={**PROPOSAL, "saved": True})
        assert client.get(f"/api/v1/remotea/target-setup/{saved.json()['op_id']}").json()["result"]["saved"] is True
        again = client.post(f"/api/v1/remotea/target-setup/{op_id}/confirm")
        assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_SAVED"


def test_a_failed_setup_says_why(client):
    token = enable(client)["token"]
    with connect(bearer(token)) as ws:
        host_id = ready(ws, C_CAPS + ["target.setup"])
        op_id = client.post("/api/v1/remotea/target-setup", json={"host_id": host_id, "repo": "/nowhere"}).json()["op_id"]
        settle(ws, ws.receive_json(), state="failed", detail="/nowhere is not a git repository")
        out = client.get(f"/api/v1/remotea/target-setup/{op_id}").json()
        assert out["done"] and out["status"] == "failed" and "not a git repository" in out["detail"]
        assert client.post(f"/api/v1/remotea/target-setup/{op_id}/confirm").status_code == 409
    assert client.get("/api/v1/remotea/target-setup/nope").status_code == 404
