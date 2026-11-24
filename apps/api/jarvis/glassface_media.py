"""Hands-free Glass audio admission and same-credential verification of spoken instructions."""

import asyncio
import hashlib
import hmac
import json
import re
from contextlib import suppress
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from websockets.exceptions import WebSocketException

from . import glassface_live, glassface_media_stream, glassface_tools, work_crypto
from .db import session_scope
from .domain import DomainError
from .external_routes import Bot
from .glassface_dani import Input, Terminal, active, authorized_settings, granted, leased_slot, read_body
from .models import BotCredential

router = APIRouter()
TICKET_SECONDS = 45
PROOF_SECONDS = 90
LIVE_SECONDS = 300
HANDSHAKE_LIMIT = 32
handshakes = set()
NO_STORE = {"Cache-Control": "no-store"}


class TicketRequest(Input):
    terminal: Terminal
    focus: str = Field(max_length=160)
    view: glassface_media_stream.View | None = None


class ProofRequest(Input):
    proof: str = Field(min_length=1, max_length=24_000)


def invalid():
    return DomainError("NOT_AUTHORIZED", "The Glass voice credential is invalid or has expired.", 401)


def issue(identity, body):
    authorized_settings(identity)
    work_crypto.cipher()  # Can issue the corresponding terminal proof.
    secret = Fernet.generate_key()
    digest = hashlib.sha256(secret).hexdigest()
    with session_scope() as db:
        granted(db, identity)  # Serializes issuance, redemption and revocation across replicas.
        db.get(BotCredential, identity).glass_live_ticket = {
            "digest": digest,
            "context": Fernet(secret).encrypt(body.model_dump_json(exclude_none=True).encode()).decode(),
        }
    # Only the client holds the per-ticket key that opens the temporary terminal context.
    return identity + "." + secret.decode().rstrip("=")


def consume(ticket):
    match = re.fullmatch(r"([0-9a-f-]{36})\.([A-Za-z0-9_-]{43})", ticket)
    if not match:
        raise invalid()
    identity, supplied = match.groups()
    secret = (supplied + "=").encode()
    digest = hashlib.sha256(secret).hexdigest()

    def matches(row):
        return (
            row is not None
            and row.glass_live_ticket
            and hmac.compare_digest(row.glass_live_ticket["digest"], digest)
        )

    with session_scope() as db:
        row = db.get(BotCredential, identity)
        if not matches(row):
            raise invalid()
        granted(db, identity)
        db.refresh(row)
        if not matches(row):
            raise invalid()
        try:
            body = json.loads(
                Fernet(secret).decrypt(row.glass_live_ticket["context"].encode(), ttl=TICKET_SECONDS)
            )
        except (ValueError, InvalidToken):
            raise invalid() from None
        row.glass_live_ticket = None
    return identity, body


def attest(identity, focus, action, text, view=None, *, resolved_tool=None):
    operation = str(uuid4())
    assertion = {
        "purpose": "glass-live-utterance-v1",
        "action": action,
        "credential": identity,
        "focus": focus,
        "text": text,
        "operation": operation,
    }
    if resolved_tool is not None and action not in {"list", "read", "navigate"}:
        return None
    if action in {"list", "read", "navigate", "start"}:
        tool = glassface_tools.parse(text, view)
        if resolved_tool:
            if action in {"list", "read"} or (
                action == "navigate"
                and resolved_tool.get("command") == "open"
                and set(resolved_tool) == {"name", "command", "value"}
                and view
                and "open" in view.get("actions", [])
                and any(node["id"] == resolved_tool["value"] for node in view.get("destinations", []))
            ):
                tool = resolved_tool
            else:
                return None
        if not tool or tool["name"] != action or not view or "actions" not in view:
            return None
        if (
            tool.get("command") in {"select", "enter_folder"}
            and tool.get("value")
            and not view.get("choices")
        ):
            return None
        assertion["tool"] = tool
    if view is not None:
        assertion["view"] = view
    proof = work_crypto.seal(assertion)
    if len(proof) > 8192:  # Shared limit on the device and the DavisPC verifier.
        return None
    return {
        "type": "utterance",
        "action": action,
        "operation": operation,
        "proof": proof,
        **({"command": assertion["tool"]["command"]} if action == "navigate" else {}),
    }


def verify(identity, proof):
    with session_scope() as db:
        granted(db, identity)
    try:
        obj = json.loads(work_crypto.cipher().decrypt(proof.encode(), ttl=PROOF_SECONDS))
    except (ValueError, InvalidToken):
        raise invalid() from None
    if (
        not isinstance(obj, dict)
        or obj.get("purpose") != "glass-live-utterance-v1"
        or obj.get("credential") != identity
    ):
        raise invalid()
    result = {key: obj[key] for key in ("focus", "text", "operation", "view") if key in obj}
    if "tool" in obj:
        result.update(tool=obj["tool"], action=obj["action"])
    return result


@router.post("/api/glassface/dani/live/tickets")
async def tickets(request: Request, identity: Bot):
    body = await read_body(request, TicketRequest)
    return JSONResponse({"ticket": await run_in_threadpool(issue, identity, body)}, headers=NO_STORE)


@router.post("/api/glassface/dani/live/verify")
async def verify_proof(request: Request, identity: Bot):
    body = await read_body(request, ProofRequest)
    return JSONResponse(await run_in_threadpool(verify, identity, body.proof), headers=NO_STORE)


@router.websocket("/api/glassface/dani/live")
async def native_voice(peer: WebSocket):
    # Credentials never appear in the URL, a cookie or the websocket subprotocol.
    if peer.query_params or len(handshakes) >= HANDSHAKE_LIMIT:
        await peer.close(code=1008)
        return
    handshake = object()
    handshakes.add(handshake)
    admitted = None
    reason, code = "ended", 1000
    try:
        await peer.accept()
        async with asyncio.timeout(6):
            frame = await peer.receive()
            if frame["type"] == "websocket.disconnect":
                return
            raw = frame.get("text")
            if not raw or len(raw) > 256:
                raise invalid()
            start = json.loads(raw)
            if (
                not isinstance(start, dict)
                or start.keys() != {"type", "ticket"}
                or start["type"] != "start"
                or not isinstance(start["ticket"], str)
            ):
                raise invalid()
            identity, body = await run_in_threadpool(consume, start["ticket"])
        handshakes.discard(handshake)
        if identity in active or len(active) >= 4:
            reason, code = "busy", 1013
            return
        admitted = identity
        active.add(identity)
        settings = await run_in_threadpool(authorized_settings, identity)
        usage = glassface_live.Usage()
        # Allow for setup, the media deadline, graceful close and billing rounding.
        async with leased_slot(identity, settings.live_model, usage, LIVE_SECONDS + 20) as recheck:

            async def proof(action, words, view=None, *, resolved_tool=None):
                if not body["focus"]:
                    return None
                await recheck()
                return attest(identity, body["focus"], action, words, view, resolved_tool=resolved_tool)

            await glassface_media_stream.bridge(
                peer,
                settings.live_model,
                settings.openai_api_key,
                body["terminal"],
                usage,
                recheck,
                proof,
                LIVE_SECONDS,
                view=body.get("view"),
                resolve_intent=lambda words, scene: run_in_threadpool(
                    glassface_tools.resolve_view_intent, identity, words, scene
                ),
            )
    except DomainError as exc:
        reason, code = ("unavailable", 1013) if exc.status >= 429 else ("unauthorized", 1008)
    except TimeoutError:
        reason, code = "timeout", 1000
    except (WebSocketDisconnect, OSError, WebSocketException):
        reason, code = "disconnected", 1001
    except (ValueError, glassface_live.LiveFailure):
        reason, code = "invalid_stream", 1008
    finally:
        handshakes.discard(handshake)
        if admitted is not None:
            active.discard(admitted)
        with suppress(RuntimeError, OSError, WebSocketDisconnect):
            async with asyncio.timeout(2):
                await peer.send_json({"type": "ended", "reason": reason})
                await peer.close(code=code)
