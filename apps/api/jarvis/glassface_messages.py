"""Owner-enrolled Glass messages to managed runs through the paired Remotea host."""
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import agent_automation, agent_control, agent_decisions, agent_link, agent_receipts, bot_access
from . import run_coordinator as coordinator
from .agent_actor import Actor
from .db import session_scope
from .domain import DomainError
from .external_routes import Bot
from .models import now
from .session_models import AgentHost, AgentSession

router = APIRouter(prefix="/api/glassface")
SCOPE = "glassface:message"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: UUID
    server_id: str = Field(min_length=1, max_length=100)
    surf: str = Field(min_length=1, max_length=120)
    incarnation: int = Field(ge=1, strict=True)
    generation: int = Field(ge=1, strict=True)
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def plain_text(cls, value):
        if not value.strip() or any((ord(c) < 32 and c not in "\n\t") or 127 <= ord(c) <= 159 for c in value):
            raise ValueError("Write a plain text message.")
        return value


def grant(db, identity):
    bot = bot_access.authorize(db, required=SCOPE, credential_id=identity)
    if set(bot.scopes) != {SCOPE}:
        raise DomainError("INSUFFICIENT_SCOPE", "Use a dedicated Glass managed messages key.", 403)
    agent_link.gate(db, bot.owner_id)
    return bot


@router.get("/managed-messages/status")
def status(identity: Bot):
    with session_scope() as db:
        grant(db, identity)
    return JSONResponse({"ready": True}, headers={"Cache-Control": "no-store"})


def queue(db, bot, identity, body):
    run = coordinator.load(db, bot.owner_id, identity)
    host = db.get(AgentHost, run.host_id)
    if not host or host.owner_id != bot.owner_id or host.server_id != body.server_id or not host.credential_id:
        raise DomainError("NOT_FOUND", "This run is unavailable on the selected host.", 404)
    if (run.surf, run.incarnation, run.generation) != (body.surf, body.incarnation, body.generation):
        raise DomainError("TARGET_CHANGED", "This terminal changed. Open it again.", 409)
    coordinator.ensure_eridani_control(run)
    capabilities = set((host.caps or {}).get("caps") or [])
    if not agent_link.connected(host) or not {"commands.durable", "input.direct", "input"} <= capabilities:
        raise DomainError("INPUT_UNAVAILABLE", "Reconnect the managed Remotea host.", 409)
    session = db.get(AgentSession, run.session_pk) if run.session_pk else None
    if not session or (session.owner_id, session.host_id, session.run_id, session.surf, session.incarnation) != (
            bot.owner_id, host.id, identity, body.surf, body.incarnation):
        raise DomainError("TARGET_CHANGED", "This managed session changed. Open it again.", 409)
    if ((run.sync_state or {}).get("execution_mode") != "managed" or session.state not in {"idle", "working"}
            or run.state not in {"planning", "executing"} or run.paused or agent_automation.held(run)
            or run.plan_pending or agent_decisions.for_run(db, run)):
        raise DomainError("INPUT_UNAVAILABLE", "Open this run in Eridani to see its current controls.", 409)
    actor = Actor("bot", credential_id=bot.id)
    # A retry carries action_context so the outbox tracks the receipt. Set origin explicitly:
    # browser action receipts otherwise imply human authority on modern hosts.
    coordinator.command(db, run, "input", {"surf": run.surf, "incarnation": run.incarnation, "mode": "queue",
                                            "text": body.text, "origin": "automation"}, source="glassface")
    agent_control.sent(run, actor, body.text, mode="queue", action_id=str(body.action_id))
    run.last_progress_at = now()
    return {"status": "queued", "action_id": str(body.action_id), "run_id": identity}


@router.post("/runs/{identity}/messages")
def message(identity: UUID, body: Message, credential: Bot):
    with session_scope() as db:
        bot = grant(db, credential)
        return agent_receipts.once(db, bot.owner_id, str(identity), "glassface:message", body,
                                   lambda: queue(db, bot, str(identity), body))
