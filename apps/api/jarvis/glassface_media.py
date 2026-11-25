"""Hands-free Glass audio admission and same-credential verification of spoken instructions."""

import asyncio
import base64
import hashlib
import hmac
import json
import re
from contextlib import suppress
from typing import Literal
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from websockets.exceptions import WebSocketException

from . import (
    glassface_gemini_stream,
    glassface_live,
    glassface_media_stream,
    glassface_tools,
    glassface_trace,
    work_crypto,
)
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


class Diagnostics(Input):
    project: glassface_trace.Project
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class VoiceSelection(Input):
    model: Literal["gpt-live-1", "gemini-3.8-live-extended-thinking", "gemini-3.8-live"]
    thinking: Literal["low", "medium", "high"] | None = None


class TicketRequest(Input):
    diagnostics: Diagnostics | None = None
    terminal: Terminal
    focus: str = Field(max_length=160)
    view: glassface_media_stream.View | None = None
    voice: VoiceSelection | None = None


class ProofRequest(Input):
    proof: str = Field(min_length=1, max_length=24_000)


def invalid():
    return DomainError("NOT_AUTHORIZED", "The Glass voice credential is invalid or has expired.", 401)


def _provider_for_model(model: str | None) -> Literal["openai", "gemini"]:
    return "gemini" if isinstance(model, str) and model.startswith("gemini-") else "openai"


def issue(identity, body):
    requested_model = body.voice.model if body.voice else None
    authorized_settings(identity, provider=_provider_for_model(requested_model) if requested_model else "any")
    work_crypto.cipher()  # Can issue the corresponding terminal proof.
    payload = body.model_dump(exclude_none=True, exclude={"diagnostics"})
    if body.diagnostics:
        profile = body.diagnostics
        payload["diagnostics"] = {
            "trace_id": profile.trace_id,
            "project": {
                **profile.project.model_dump(exclude={"secret"}),
                "secret": profile.project.secret.get_secret_value(),
            },
        }
    secret = Fernet.generate_key()
    digest = hashlib.sha256(secret).hexdigest()
    with session_scope() as db:
        granted(db, identity)  # Serializes issuance, redemption and revocation across replicas.
        db.get(BotCredential, identity).glass_live_ticket = {
            "digest": digest,
            "context": Fernet(secret).encrypt(json.dumps(payload).encode()).decode(),
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


def _validate_structured_tool(action: str, tool: dict, view: dict | None) -> bool:
    if not isinstance(tool, dict) or tool.get("name") != action or not view or "actions" not in view:
        return False
    actions = view.get("actions") or []
    if action == "list":
        return set(tool) <= {"name", "detail"} and tool.get("detail") in {None, "brief"}
    if action == "read":
        q = tool.get("query")
        return set(tool) <= {"name", "query"} and (q is None or (isinstance(q, str) and len(q) <= 160))
    if action == "find":
        q = tool.get("query")
        return set(tool) == {"name", "query"} and isinstance(q, str) and 0 < len(q) <= 160
    if action == "start":
        if "start" not in actions or tool.get("harness") not in {"claude", "codex"}:
            return False
        folder = tool.get("folder")
        if not isinstance(folder, str) or not 0 < len(folder) <= 512:
            return False
        return set(tool) <= {"name", "folder", "harness", "model", "effort"} and all(
            isinstance(tool[k], str) and len(tool[k]) <= 160
            for k in ("model", "effort")
            if k in tool
        )
    if action == "navigate":
        cmd = tool.get("command")
        val = tool.get("value", "")
        if (
            cmd
            not in {
                "open",
                "back",
                "next",
                "previous",
                "select",
                "enter_folder",
                "set_volume",
                "set_voice_model",
                "set_earphone_amp",
                "set_keep_awake",
                "set_spoken_replies",
            }
            or cmd not in actions
            or not set(tool) <= {"name", "command", "value"}
            or not isinstance(val, str)
            or len(val) > 160
        ):
            return False
        if cmd == "open" and "destinations" in view:
            return any(node["id"] == val for node in view["destinations"])
        if cmd in {"select", "enter_folder"} and val and not view.get("choices"):
            return False
        return True
    if action == "send":
        msg = tool.get("message")
        target = tool.get("target", "")
        if (
            not set(tool) <= {"name", "message", "target"}
            or not isinstance(msg, str)
            or not 0 < len(msg) <= 2400
            or not isinstance(target, str)
            or len(target) > 160
        ):
            return False
        return view.get("screen") == "terminal" or bool(target.strip())
    return False


def attest(identity, focus, action, text, view=None, *, resolved_tool=None, structured_tool=None):
    operation = str(uuid4())
    assertion = {
        "purpose": "glass-live-utterance-v1",
        "action": action,
        "credential": identity,
        "focus": focus,
        "text": text,
        "operation": operation,
    }
    if structured_tool is not None:
        if not _validate_structured_tool(action, structured_tool, view):
            return None
        assertion["tool"] = structured_tool
    else:
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
        **({"structured": True} if structured_tool is not None else {}),
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
    trace = None
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
        voice_choice = body.pop("voice", None) or {}
        base_settings = await run_in_threadpool(authorized_settings, identity, "any")
        selected_model = voice_choice.get("model") or base_settings.live_model
        provider = _provider_for_model(selected_model)
        settings = await run_in_threadpool(authorized_settings, identity, provider)
        usage = glassface_live.Usage()
        # Allow for setup, the media deadline, graceful close and billing rounding.
        async with leased_slot(identity, selected_model, usage, LIVE_SECONDS + 20) as recheck:

            async def proof(action, words, view=None, *, resolved_tool=None, structured_tool=None):
                if not body["focus"]:
                    return None
                await recheck()
                return attest(
                    identity,
                    body["focus"],
                    action,
                    words,
                    view,
                    resolved_tool=resolved_tool,
                    structured_tool=structured_tool,
                )

            diagnostics = body.pop("diagnostics", None)
            if diagnostics:
                profile = Diagnostics.model_validate(diagnostics)
                trace = glassface_trace.Session(profile.project, profile.trace_id)
            if provider == "gemini":
                await glassface_gemini_stream.bridge(
                    peer,
                    selected_model,
                    settings.gemini_api_key,
                    body["terminal"],
                    usage,
                    recheck,
                    proof,
                    LIVE_SECONDS,
                    view=body.get("view"),
                    thinking_level=voice_choice.get("thinking"),
                    **({"trace": trace} if trace else {}),
                )
            else:
                await glassface_media_stream.bridge(
                    peer,
                    selected_model,
                    settings.openai_api_key,
                    body["terminal"],
                    usage,
                    recheck,
                    proof,
                    LIVE_SECONDS,
                    view=body.get("view"),
                    **({"trace": trace} if trace else {}),
                    **({"worker_identity": identity} if (body.get("view") or {}).get("destinations") else {}),
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
        if trace:
            trace.event("session-end", reason=reason, close_code=code)
            trace.flush()
        if admitted is not None:
            active.discard(admitted)
        with suppress(RuntimeError, OSError, WebSocketDisconnect):
            async with asyncio.timeout(2):
                await peer.send_json({"type": "ended", "reason": reason})
                await peer.close(code=code)


class GatewayTrace(Diagnostics):
    name: str = Field(pattern=r"^[a-z][a-z0-9.-]{0,63}$")
    inputs: dict
    outputs: dict
    wav: str | None = Field(default=None, max_length=12000000)


@router.post("/api/glassface/dani/diagnostics")
async def gateway_trace(request: Request, identity: Bot):
    await run_in_threadpool(authorized_settings, identity, "any")
    data = await read_body(request, GatewayTrace, limit=12100000)
    tracks = {}
    if data.wav:
        try:
            raw = base64.b64decode(data.wav, validate=True)
        except ValueError:
            raise DomainError("INVALID_ARGUMENT", "Invalid diagnostic audio.", 422) from None
        if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
            raise DomainError("INVALID_ARGUMENT", "Expected diagnostic WAV audio.", 422)
        tracks["dictation"] = raw
    try:
        await run_in_threadpool(
            glassface_trace.upload,
            data.project,
            data.trace_id,
            "Glass · " + data.name,
            data.inputs,
            data.outputs,
            tracks,
        )
    except (httpx.HTTPError, ValueError, KeyError):
        raise DomainError("DIAGNOSTICS_UNAVAILABLE", "Dedicated project did not acknowledge export.", 502) from None
    return JSONResponse({"accepted": True}, headers=NO_STORE)
