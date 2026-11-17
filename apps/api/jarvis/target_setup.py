"""Add a repository as an execution target from the app (docs/AGENT_CONTROL.md "Adding a repository from the app").

remotea's guided setup (`remotea eridani targets setup <repo>`) reads a repository with a coding agent and proposes
a target: base branch, dependency install, a quick check, and whether pull requests have CI. This runs the same
setup on the owner's host through the link (`target.setup`, cap `target.setup`), in two steps:

1. **Propose** (`confirm: false`): the host reads the repository and answers with the proposal. Nothing proposed
   runs and nothing is saved.
2. **Confirm** (`confirm: true`): the owner saw that proposal and said yes. Eridani sends the proposal's `target`
   back exactly as it was shown (the host does not read the repository again, so what runs is what was seen). The
   host tries each check in its sandbox with no network, keeps the ones that pass, saves the target and says hello
   again, so the new target is offered wherever a task's repository is chosen.

One setup at a time per host. Both steps are run-less commands; the page polls `status` for the outcome.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .domain import DomainError
from .models import now
from .session_models import AgentCommand, AgentHost

KIND = "target.setup"
OPEN = ("queued", "sent", "acked")


class SetupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    host_id: str = Field(max_length=36)
    # The repository's folder on the host, as the host sees it.
    repo: str = Field(min_length=2, max_length=1000, pattern=r"^/")
    # The target's id; None lets the host derive it. `target_id` on the wire: `id` is every frame's own id.
    target_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")
    harness: Literal["claude", "codex"] | None = None
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,99}$")


def host_for(db, owner, host_id):
    host = db.get(AgentHost, host_id)
    if host is None or host.owner_id != owner:
        raise DomainError("NOT_FOUND", "No such remotea server.", 404)
    if KIND not in ((host.caps or {}).get("caps") or []):
        raise DomainError("HOST_TOO_OLD", "This remotea server cannot set up a repository from the app. Update "
                                          "remotea, or run `remotea eridani targets setup <folder>` on it.", 409)
    return host


def running(db, host_id):
    return db.scalar(select(AgentCommand).where(
        AgentCommand.host_id == host_id, AgentCommand.kind == KIND, AgentCommand.status.in_(OPEN),
        AgentCommand.expires_at > now()).order_by(AgentCommand.created_at.desc()).limit(1))


def send(db, owner, host, body):
    from . import agent_link
    from . import run_coordinator as coordinator

    row = coordinator.command(db, None, KIND, {"owner_id": owner, **body}, host_id=host.id, source="app")
    row.payload = {k: v for k, v in row.payload.items() if k != "owner_id"}
    row.digest = agent_link.digest(row.payload)
    return {**public(row), "connected": agent_link.connected(host)}


def propose(db, owner, body: SetupInput) -> dict:
    host = host_for(db, owner, body.host_id)
    busy = running(db, host.id)
    if busy is not None:
        if not (busy.payload or {}).get("confirm") and (busy.payload or {}).get("repo") == body.repo:
            return public(busy)  # The same request again: the one already on its way.
        raise DomainError("BUSY", "This server is already setting up a repository. Wait for it to finish.", 409)
    return send(db, owner, host, {"repo": body.repo, "target_id": body.target_id, "harness": body.harness,
                                  "model": body.model, "confirm": False})


def confirm(db, owner, op_id) -> dict:
    """Save the proposal `op_id` answered with: the host tries its checks and saves the target."""
    proposal = load(db, owner, op_id)
    payload, result = proposal.payload or {}, ((proposal.outcome or {}).get("result") or {})
    if payload.get("confirm") or proposal.status != "executed" or not isinstance(result.get("target"), dict):
        raise DomainError("NOT_A_PROPOSAL", "There is no finished proposal to save. Ask for one first.", 409)
    host = host_for(db, owner, proposal.host_id)
    if running(db, host.id) is not None:
        raise DomainError("BUSY", "This server is already setting up a repository. Wait for it to finish.", 409)
    later = db.scalar(select(AgentCommand.id).where(
        AgentCommand.host_id == host.id, AgentCommand.kind == KIND, AgentCommand.created_at > proposal.created_at,
        AgentCommand.payload["confirm"].as_boolean().is_(True), AgentCommand.payload["proposal"].astext == op_id,
        AgentCommand.status == "executed").limit(1))
    if later is not None:
        raise DomainError("ALREADY_SAVED", "This proposal was already saved.", 409)
    return send(db, owner, host, {"repo": payload.get("repo"), "target_id": payload.get("target_id"), "harness": payload.get("harness"),
                                  "model": payload.get("model"), "confirm": True, "target": result["target"],
                                  "proposal": op_id})


def load(db, owner, op_id):
    row = db.scalar(select(AgentCommand).where(AgentCommand.op_id == op_id, AgentCommand.kind == KIND,
                                               AgentCommand.owner_id == owner))
    if row is None:
        raise DomainError("NOT_FOUND", "No such repository setup.", 404)
    return row


def status(db, owner, op_id) -> dict:
    from . import agent_link

    row = load(db, owner, op_id)
    return {**public(row), "connected": agent_link.connected(db.get(AgentHost, row.host_id))}


def public(row) -> dict:
    """What the page shows: where it is, and when done the host's own report (the `--json` shape of the setup)."""
    payload, outcome = row.payload or {}, row.outcome or {}
    done = row.status not in OPEN and row.status != "deferred"
    expired = row.status in OPEN and row.expires_at is not None and row.expires_at <= now()
    return {"op_id": row.op_id, "host_id": row.host_id, "repo": payload.get("repo"), "confirm": bool(payload.get("confirm")),
            "status": "expired" if expired else row.status, "done": done or expired,
            "detail": outcome.get("detail") or "", "result": outcome.get("result") if done else None,
            "created_at": row.created_at}
