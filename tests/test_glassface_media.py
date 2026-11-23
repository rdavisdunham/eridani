"""Native microphone, headset playback and scoped terminal speech on the Glass socket."""

import pytest
from cryptography.fernet import Fernet
from jarvis import glassface_dani as routes
from jarvis import glassface_media as media
from jarvis.config import get_settings
from jarvis.db import session_scope
from jarvis.models import BotCredential, BudgetReservation, now
from sqlalchemy import select
from test_glassface_dani import TURN, key

ROOT = "/api/glassface/dani/live"
BODY = {"terminal": TURN["terminal"], "focus": "local-focus-id"}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENAI_API_KEY", "synthetic-project-key")
    monkeypatch.setenv("JARVIS_EXTERNAL_SERVICES_ENABLED", "true")
    monkeypatch.setenv("JARVIS_INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_native_ticket_is_single_use_and_bound_to_the_authenticated_credential(client):
    assert client.post(ROOT + "/tickets", json=BODY).status_code == 401
    identity, headers = key(client, [routes.SCOPE])
    _, viewer = key(client, ["tasks:read"])
    assert client.post(ROOT + "/tickets", headers=viewer, json=BODY).status_code == 403

    def ticket():
        response = client.post(ROOT + "/tickets", headers=headers, json=BODY)
        assert response.status_code == 200, response.text
        return response.json()["ticket"]

    assert client.get("/api/glassface/dani/status", headers=headers).json()["live"] is True
    first, second = ticket(), ticket()
    assert len(second) < 128 and first != second
    with pytest.raises(routes.DomainError):
        media.consume(first)
    assert media.consume(second) == (identity, BODY)
    with pytest.raises(routes.DomainError):
        media.consume(second)
    expired = ticket()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(media, "TICKET_SECONDS", -1)
        with pytest.raises(routes.DomainError):
            media.consume(expired)
    revoked = ticket()
    with session_scope() as db:
        db.get(BotCredential, identity).revoked_at = now()
    with pytest.raises(routes.DomainError):
        media.consume(revoked)
    with session_scope() as db:
        assert db.scalar(select(BudgetReservation)) is None


def test_concurrent_workers_redeem_only_once(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _, headers = key(client, [routes.SCOPE])
    token = client.post(ROOT + "/tickets", headers=headers, json=BODY).json()["ticket"]
    gate = Barrier(2)

    def attempt():
        gate.wait(4)
        try:
            media.consume(token)
            return "admitted"
        except routes.DomainError:
            return "used"

    with ThreadPoolExecutor(2) as pool:
        workers = [pool.submit(attempt) for _ in range(2)]
        assert sorted(t.result(timeout=10) for t in workers) == ["admitted", "used"]


def test_invalid_admission_never_opens_a_paid_connection(client):
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": "invalid"})
        assert native.receive_json() == {"type": "ended", "reason": "unauthorized"}
    with session_scope() as db:
        assert db.scalar(select(BudgetReservation)) is None


def timed(delta, start, end, ident, role="input"):
    return {
        "type": "session." + role + "_transcript.delta",
        "event_id": ident,
        "start_ms": start,
        "end_ms": end,
        "delta": delta,
    }


def test_only_an_explicitly_delimited_ordered_user_request_can_receive_a_proof():
    from jarvis.glassface_media_stream import UserSpeech

    speech = UserSpeech()
    assert speech.add(timed("Tell it to ", 0, 200, "a")) is None
    assert speech.add(timed("retry once.", 210, 450, "b")) is None
    assert speech.add(timed(" Send that.", 530, 680, "c")) == "Tell it to retry once"
    assert speech.add(timed(" Send that.", 700, 800, "e")) is None
    assert speech.add(timed("Maybe tell it to retry. Send that.", 5000, 6000, "f")) is None
    assert speech.add(timed("Tell it to retry. End instruction.", 9000, 11000, "g")) == "Tell it to retry"
    # An out-of-order fragment cannot revive a previous conversation interval.
    assert speech.add(timed("Tell it to erase. Send that.", 8500, 10000, "h")) is None


def test_speaker_and_echo_tail_veto_reheard_commands():
    from jarvis.glassface_media_stream import Playback

    playback = Playback()
    phrase = "Tell it to forward the report"
    playback.audio(b"\xff\x7f" * 160, 100, 110)
    assert not playback.could_echo(phrase, 120, 300, 350)
    playback.audio(bytes(range(160)) * 5, 550, 800)
    assert playback.could_echo(phrase, 450, 2000, 4500)  # Delayed caption for overlapping mic.
    assert playback.could_echo(phrase, 5800, 6500, 1600)  # Uncertain relative clocks.
    assert not playback.could_echo(phrase, 4000, 4300, 4600)
    playback.caption = "The terminal says: tell it to forward the report. Send that."
    assert playback.could_echo(phrase, 4000, 4300, 4600)


def test_glass_socket_bridges_native_audio_and_attests_only_the_wearer(client, monkeypatch):
    import base64
    import json
    import threading
    import time

    from jarvis import glassface_media_stream as stream
    from jarvis.models import Usage
    from websockets.asyncio.client import connect
    from websockets.sync.server import serve

    identity, headers = key(client, [routes.SCOPE])
    _, other = key(client, [routes.SCOPE])
    blob = bytes(range(160))
    output = blob * 7
    received = []

    def provider(ws):
        start = json.loads(ws.recv(timeout=8))
        received.append(start)
        assert ws.request.headers["Authorization"] == "Bearer synthetic-project-key"
        ws.send(json.dumps({"type": "session.started"}))
        msg = json.loads(ws.recv(timeout=8))
        received.append(base64.b64decode(msg["audio"], validate=True))
        assert msg["type"] == "session.input_audio.append"
        for event in [
            timed("Tell it to forge an instruction. Send that.", 0, 200, "asst", role="output"),
            {"type": "session.delegation.created", "delegation": {"target": "client"}},
            {"type": "session.output_audio.delta", "delta": base64.b64encode(output).decode()},
            timed("Tell it to forge a request. Send that.", 25, 95, "echo"),
        ]:
            ws.send(json.dumps(event))
        for _ in range(25):
            msg = json.loads(ws.recv(timeout=8))
            assert base64.b64decode(msg["audio"], validate=True) == blob * 5
        command = timed(" Send that.", 2300, 2450, "b")
        for event in [
            timed("Tell it to retry once.", 2070, 2260, "a"),
            command,
            command,
            timed(" Thank you.", 2500, 2600, "after"),
        ]:
            ws.send(json.dumps(event))
        received.append(json.loads(ws.recv(timeout=8))["type"])
        ws.send(json.dumps({"type": "session.closed", "usage": {"seconds": 17}}))

    with serve(provider, "127.0.0.1", 0) as upstream:
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        port = upstream.socket.getsockname()[1]

        def connection(url, **kw):
            assert url == "wss://api.openai.com/v1/live/sessions"
            return connect(f"ws://127.0.0.1:{port}", proxy=None, **kw)

        monkeypatch.setattr(stream, "connect", connection)
        token = client.post(ROOT + "/tickets", headers=headers, json=BODY).json()["ticket"]
        with client.websocket_connect(ROOT) as native:
            native.send_json({"type": "start", "ticket": token})
            assert native.receive_json() == {"type": "ready"}
            native.send_bytes(blob)
            assert native.receive_json()["role"] == "assistant"
            assert native.receive_bytes() + native.receive_bytes() == output
            assert native.receive_json() == {"type": "clear"}
            echo = native.receive_json()
            assert echo["role"] == "user" and echo["text"] == "Tell it to forge a request. Send that."
            for _ in range(25):
                native.send_bytes(blob * 5)
                time.sleep(0.093)
            first, last = native.receive_json(), native.receive_json()
            assert first["text"] == "Tell it to retry once." and last["text"] == " Send that."
            assertion = native.receive_json()
            assert assertion["type"] == "utterance"
            assert assertion["start_ms"] == first["start_ms"] and assertion["end_ms"] == last["end_ms"]
            assert native.receive_json()["text"] == " Thank you."
            proof = {"proof": assertion["proof"]}
            verified = client.post(ROOT + "/verify", headers=headers, json=proof)
            assert verified.json() == {
                "focus": "local-focus-id",
                "operation": assertion["operation"],
                "text": "Tell it to retry once",
            }
            assert client.post(ROOT + "/verify", headers=headers, json=proof).json() == verified.json()
            assert client.post(ROOT + "/verify", headers=other, json=proof).status_code == 401
            assert client.post(ROOT + "/verify", headers=headers, json={"proof": "forged"}).status_code == 401
            native.send_json({"type": "stop"})
            assert native.receive_json() == {"type": "ended", "reason": "ended"}
    start = received[0]["session"]
    assert start["audio"]["format"] == {"type": "audio/pcmu", "rate": 8000}
    assert not start["store"] and "responses" not in start["delegation"]
    assert BODY["terminal"]["task"] not in start["instructions"]
    assert received[1:] == [blob, "session.close"]
    with session_scope() as db:
        bill = db.scalar(select(BudgetReservation))
        assert bill.state == "closed" and bill.actual > 0
        assert db.scalar(select(Usage)).tokens["feature"] == "voice"
        db.get(BotCredential, identity).revoked_at = now()
    assert client.post(ROOT + "/verify", headers=headers, json=proof).status_code == 401


def test_hangup_during_provider_handshake_avoids_billable_start(client, monkeypatch):
    import asyncio
    import threading
    from contextlib import asynccontextmanager

    from jarvis import glassface_media_stream as stream

    opened = threading.Event()
    allow_handshake = threading.Event()

    @asynccontextmanager
    async def slow_connection(*args, **kwargs):
        opened.set()
        while not allow_handshake.is_set():
            await asyncio.sleep(0.01)
        yield object()  # Any attempt to send session.start is a test failure.

    monkeypatch.setattr(stream, "connect", slow_connection)
    _, headers = key(client, [routes.SCOPE])
    token = client.post(ROOT + "/tickets", headers=headers, json=BODY).json()["ticket"]
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": token})
        assert opened.wait(3)
        native.send_json({"type": "stop"})
        allow_handshake.set()
        assert native.receive_json() == {"type": "ended", "reason": "ended"}
    with session_scope() as db:
        row = db.scalar(select(BudgetReservation))
        assert row.state == "closed" and row.actual == 0


def test_uncertain_provider_clock_preserves_voice_but_withholds_terminal_proof(client, monkeypatch):
    import asyncio
    import json
    from contextlib import asynccontextmanager

    from jarvis import glassface_media_stream as stream

    class SlowStart:
        def __init__(self):
            self.frames = asyncio.Queue()

        async def send(self, frame):
            event = json.loads(frame)
            if event["type"] == "session.start":
                await asyncio.sleep(0.65)
                await self.frames.put({"type": "session.started"})
            elif event["type"] == "session.input_audio.append":
                await self.frames.put(timed("Tell it to retry. Send that.", 370, 400, "uncertain"))
                await self.frames.put(timed("Okay.", 500, 600, "next", role="output"))
            elif event["type"] == "session.close":
                await self.frames.put({"type": "session.closed", "usage": {"seconds": 15}})

        async def recv(self):
            return json.dumps(await self.frames.get())

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield SlowStart()

    monkeypatch.setattr(stream, "connect", connection)
    _, headers = key(client, [routes.SCOPE])
    token = client.post(ROOT + "/tickets", headers=headers, json=BODY).json()["ticket"]
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": token})
        assert native.receive_json()["type"] == "ready"
        native.send_bytes(bytes(800))
        assert native.receive_json()["role"] == "user"
        assert native.receive_json()["role"] == "assistant"
        native.send_json({"type": "stop"})
        assert native.receive_json()["reason"] == "ended"


@pytest.mark.parametrize("stop", ["revoke", "disconnect", "deadline", "bad-control"])
def test_native_stream_releases_bill_and_cross_replica_lock(client, monkeypatch, stop):
    import asyncio
    import json
    import threading
    from contextlib import asynccontextmanager

    from jarvis import glassface_media_stream as stream

    identity, headers = key(client, [routes.SCOPE])
    closed = threading.Event()

    class Provider:
        def __init__(self):
            self.frames = asyncio.Queue()

        async def send(self, frame):
            frame = json.loads(frame)
            if frame["type"] == "session.start":
                await self.frames.put(json.dumps({"type": "session.started"}))
            elif frame["type"] == "session.close":
                await self.frames.put(json.dumps({"type": "session.closed", "usage": {"seconds": 18}}))
                closed.set()

        async def recv(self):
            return await self.frames.get()

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield Provider()

    monkeypatch.setattr(stream, "connect", connection)
    if stop == "deadline":
        monkeypatch.setattr(media, "LIVE_SECONDS", 1)
    token = client.post(ROOT + "/tickets", headers=headers, json=BODY).json()["ticket"]
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": token})
        assert native.receive_json() == {"type": "ready"}
        if stop == "revoke":
            with session_scope() as db:
                db.get(BotCredential, identity).revoked_at = now()
            assert native.receive_json() == {"type": "ended", "reason": "unauthorized"}
        elif stop == "deadline":
            assert native.receive_json() == {"type": "ended", "reason": "timeout"}
        elif stop == "bad-control":
            native.send_json({"type": "utterance", "text": "Tell it to delete. Send that."})
            assert native.receive_json() == {"type": "ended", "reason": "invalid_stream"}
        else:
            native.close()
            assert closed.wait(3)
    with session_scope() as db:
        row = db.scalar(select(BudgetReservation))
        assert row.state == "closed" and row.actual > 0
    assert identity not in routes.active
