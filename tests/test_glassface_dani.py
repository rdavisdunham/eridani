"""Scoped Glass turns, including provider events on an actual loopback WebSocket."""

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from jarvis import glassface_dani as endpoint
from jarvis import glassface_live as live
from jarvis.config import get_settings
from jarvis.db import session_scope
from jarvis.domain import DomainError
from jarvis.models import AgentWork, BotCredential, BudgetReservation, Source, Usage, now
from sqlalchemy import func, select
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

PATH = "/api/glassface/dani/turn"
TURN = {
    "kind": "brief",
    "question": "",
    "terminal": {
        "label": "Claude 13",
        "task": "Reconnect",
        "reply": "Tests pass.",
        "question": "Retry after 10 seconds?",
    },
    "history": [],
}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENAI_API_KEY", "synthetic-project-key")
    monkeypatch.setenv("JARVIS_EXTERNAL_SERVICES_ENABLED", "true")
    monkeypatch.setenv("JARVIS_INTEGRATION_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def key(client, scopes):
    response = client.post("/api/v1/bot-keys", json={"name": "Google Glass", "scopes": scopes})
    assert response.status_code == 201, response.text
    return response.json()["credential"]["id"], {"Authorization": "Bearer " + response.json()["token"]}


async def nothing():
    pass


@asynccontextmanager
async def provider(events, *, final=True):
    received = []

    async def handle(ws):
        assert ws.request.headers["Authorization"] == "Bearer synthetic-project-key"
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "session.started"}))
        # The model must have an active input clock to speak a text-seeded turn.
        silence = json.loads(await ws.recv())
        assert silence["type"] == "session.input_audio.append"
        assert base64.b64decode(silence["audio"]) == bytes(4800)
        for event in events:
            await ws.send(json.dumps(event))
        async for raw in ws:
            if json.loads(raw)["type"] == "session.close":
                received.append("close")
                if final:
                    await ws.send(json.dumps({"type": "session.closed", "usage": {"seconds": 18}}))
                break

    async with serve(handle, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        def connector(address, **kw):
            assert address == "wss://api.openai.com/v1/live/sessions"
            return connect(f"ws://127.0.0.1:{port}", proxy=None, **kw)

        yield connector, received


@pytest.mark.asyncio
async def test_live_socket_preserves_transcript_releases_media_and_disables_tools():
    part = {"type": "session.output_transcript.delta", "event_id": "part1", "delta": "Retry once. "}
    usage = live.Usage()
    async with provider(
        [
            part,
            part,
            {"type": "session.output_transcript.delta", "delta": "End of Glass "},
            {"type": "session.output_transcript.delta", "delta": "Briefing."},
        ]
    ) as (conn, seen):
        answer = await live.respond(
            "selected-live", "synthetic-project-key", TURN, usage, nothing, connector=conn
        )
    assert answer == "Retry once."
    session = seen[0]["session"]
    assert seen[0]["type"] == "session.start" and seen[-1] == "close"
    assert session["model"] == "selected-live" and session["store"] is False
    assert session["delegation"] == {"type": "client"}
    assert "tools" not in session and "responses" not in session
    assert json.loads(session["input"][0]["content"][0]["text"]) == TURN
    assert "Claude 13" not in session["instructions"]
    assert usage.closed and usage.seconds == 18


@pytest.mark.asyncio
async def test_delegation_or_unfinished_transcript_cannot_create_work_or_pass_as_complete(monkeypatch):
    monkeypatch.setattr(live, "TURN_SECONDS", 0.5)
    for events, error in [
        ([{"type": "session.delegation.created"}], live.LiveFailure),
        ([{"type": "session.output_transcript.delta", "delta": "Half of a sentence."}], TimeoutError),
    ]:
        usage = live.Usage()
        async with provider(events, final=False) as (conn, seen):
            with pytest.raises(error):
                await live.respond(
                    "selected-live", "synthetic-project-key", TURN, usage, nothing, connector=conn
                )
        assert seen[-1] == "close" and usage.attempted and not usage.closed


def test_authentication_scope_and_bounded_inputs(client, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("request started a provider call")

    monkeypatch.setattr(live, "respond", forbidden)
    assert client.post(PATH, json=TURN).status_code == 401
    assert client.post(PATH, headers={"Authorization": "Bearer invalid"}, json=TURN).status_code == 401
    _, other = key(client, ["sessions:read"])
    assert client.post(PATH, headers=other, json=TURN).status_code == 403
    assert (
        client.post(
            "/api/v1/bot-keys",
            json={"name": "mixed", "scopes": [endpoint.SCOPE, "work:run", "sessions:read"]},
        ).status_code
        == 400
    )
    _, glass = key(client, [endpoint.SCOPE])
    assert client.get("/api/glassface/dani/status", headers=other).status_code == 403
    readiness = client.get("/api/glassface/dani/status", headers=glass)
    assert readiness.status_code == 200 and readiness.json() == {
        "ready": True,
        "glassDiagnostics": True,
        "live": False,
        "model": get_settings().live_model,
    }
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(BudgetReservation)) == 0
    assert (
        client.post(
            "/api/v1/external/requests",
            headers=glass,
            json={"request_id": str(uuid4()), "message": "create work"},
        ).status_code
        == 403
    )
    assert client.post(PATH, headers=glass, json={**TURN, "question": "x" * 1801}).status_code == 422
    assert client.post(PATH, headers=glass, json={**TURN, "newTool": "run"}).status_code == 422
    assert (
        client.post(
            PATH, headers=glass, json={**TURN, "history": [{"user": "u", "assistant": "a"}] * 5}
        ).status_code
        == 422
    )


def test_glass_enrollment_rejects_shared_workspace_and_viewer(client):
    from test_accounts import client_for, shared

    viewer = client_for("guest")
    shared(client, viewer, role="viewer")
    for issuer, reason in ((client, "PERSONAL_WORKSPACE"), (viewer, "READ_ONLY")):
        response = issuer.post(
            "/api/v1/bot-keys", json={"name": "Google Glass", "scopes": [endpoint.SCOPE]}
        )
        assert response.status_code == 403
        assert reason in response.text
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(BotCredential)) == 0


def test_spoken_reply_uses_only_supplied_context_and_rechecks_grant(client, monkeypatch):
    identity, headers = key(client, [endpoint.SCOPE])
    revoke = False

    async def fake_model(model, project_key, supplied, usage, check):
        assert model == get_settings().live_model and project_key == "synthetic-project-key"
        assert supplied == TURN
        await check()
        usage.attempted = usage.started = usage.closed = True
        usage.seconds = 17
        if revoke:
            with session_scope() as db:
                db.get(BotCredential, identity).revoked_at = now()
        return "Claude finished. Retry in ten seconds?"

    monkeypatch.setattr(live, "respond", fake_model)
    response = client.post(PATH, headers=headers, json=TURN)
    assert response.status_code == 200, response.text
    assert response.json() == {"text": "Claude finished. Retry in ten seconds?"}
    assert "no-store" in response.headers["cache-control"]
    revoke = True
    response = client.post(PATH, headers=headers, json=TURN)
    assert response.status_code == 401 and "Claude finished." not in response.text
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(AgentWork)) == 0
        assert db.scalar(select(func.count()).select_from(Source)) == 0
        assert db.scalar(select(func.count()).select_from(Usage)) == 2
        assert {r.state for r in db.scalars(select(BudgetReservation))} == {"closed"}


def test_lost_close_keeps_hold_and_second_worker_cannot_take_same_slot(client):
    identity, _ = key(client, [endpoint.SCOPE])
    usage = live.Usage(attempted=True, started=True, seconds=15)
    with endpoint.slot(identity, "gpt-live-1", usage):
        with pytest.raises(DomainError) as exc, endpoint.slot(identity, "gpt-live-1", live.Usage()):
            pass
        assert exc.value.status == 429
    with session_scope() as db:
        saved = db.scalar(select(BudgetReservation))
        assert saved.state == "uncertain" and saved.actual > 0
    with endpoint.slot(identity, "gpt-live-1", live.Usage()):
        pass


@pytest.mark.asyncio
async def test_cancelled_await_releases_cross_process_lock_and_hold(client):
    identity, _ = key(client, [endpoint.SCOPE])
    entered = asyncio.Event()

    async def run():
        async with endpoint.leased_slot(identity, "gpt-live-1", live.Usage()):
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with endpoint.slot(identity, "gpt-live-1", live.Usage()):
        pass
    with session_scope() as db:
        assert {r.state for r in db.scalars(select(BudgetReservation))} == {"closed"}


def test_unconfigured_request_has_no_provider_effect(client, monkeypatch):
    _, headers = key(client, [endpoint.SCOPE])
    monkeypatch.setenv("JARVIS_EXTERNAL_SERVICES_ENABLED", "false")
    get_settings.cache_clear()
    assert client.get("/api/glassface/dani/status", headers=headers).status_code == 503
    assert client.post(PATH, headers=headers, json=TURN).status_code == 503
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(BudgetReservation)) == 0
