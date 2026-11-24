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
    playback.caption = "Tell it to forward the report."
    playback.audio(b"\xff\x7f" * 160, 100, 110)
    assert not playback.could_echo(phrase, 120, 300, 350)
    playback.caption = ""
    playback.audio(bytes(range(160)) * 5, 550, 800)
    assert not playback.during_navigation(500, 780)  # Speaker started after these words.
    assert playback.during_navigation(800, 860)
    assert playback.during_navigation(1390, 1500)  # Actual echo tail.
    assert playback.could_echo(phrase, 450, 2000, 4500)  # Delayed caption for overlapping mic.
    assert playback.could_echo(phrase, 5800, 6500, 1600)  # Uncertain relative clocks.
    assert not playback.could_echo(phrase, 4000, 4300, 4600)
    playback.caption = "The terminal says: tell it to forward the report. Send that."
    assert playback.could_echo(phrase, 4000, 4300, 4600)
    assert not playback.could_echo(phrase, 8000, 8300, 8600)


def test_interruption_requires_speech_and_keeps_partial_words_and_screen_binding():
    from jarvis.glassface_media_stream import SpokenInterruption, ViewHistory

    barge = SpokenInterruption()
    assert not barge.recognizes("[cough]", (0, 200), "")
    assert not barge.recognizes(" ahem ", (210, 470), "")
    assert not barge.recognizes(" actually ", (2000, 2140), "")
    assert barge.recognizes("can we", (2150, 2490), "")
    assert barge.recognizes("stop", (3600, 3710), "")
    assert not barge.recognizes("the build passed", (4800, 5250), "And the build passed.")
    a, b = {"screen": "home"}, {"screen": "terminal", "session": "desktop:surf-abc"}
    views = ViewHistory(a)
    views.change(1000, b)
    assert views.during(100, 200, 80) == a
    assert views.during(890, 1100, 80) is None
    assert views.during(1030, 1170, 80) is None
    assert views.during(1200, 1330, 80) == b


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
        ]:
            ws.send(json.dumps(event))
        # The second mic packet is the fixture headset's signal that both speaker frames arrived.
        msg = json.loads(ws.recv(timeout=8))
        assert base64.b64decode(msg["audio"], validate=True) == blob
        ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
        ws.send(json.dumps(timed("[cough]", 0, 24, "cough")))
        ws.send(json.dumps(timed("Tell it to forge a request. Send that.", 25, 95, "echo")))
        ws.send(json.dumps({"type": "session.output_audio.clear"}))
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
            native.send_bytes(blob)
            assert native.receive_json()["text"] == "[cough]"
            echo = native.receive_json()
            assert echo["role"] == "user" and echo["text"] == "Tell it to forge a request. Send that."
            assert native.receive_json() == {"type": "clear"}
            for _ in range(25):
                native.send_bytes(blob * 5)
                time.sleep(0.093)
            first, last = native.receive_json(), native.receive_json()
            assert first["text"] == "Tell it to retry once." and last["text"] == " Send that."
            assertion = native.receive_json()
            assert assertion["type"] == "utterance" and assertion["action"] == "tell"
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


@pytest.mark.parametrize(
    "phrase,continuation,role,action,focused",
    [
        ("Show me that terminal.", "", "input", "open", True),
        ("What finished?", "", "input", "finished", False),
        ("Please, open this terminal.", "", "input", "open", True),
        ("What is done?", "", "input", "finished", True),
        ("Which terminals have finished?", "", "input", "finished", False),
        ("Hey Dani, take me home.", "", "input", "home", False),
        ("Please, start a new terminal.", "", "input", "launcher", False),
        ("Switch to the terminal working on launcher.", "", "input", "find", False),
        ("What finished?", " Then tell it to retry. Send that.", "input", None, False),
        ("What finished?", "after-read", "input", "finished", False),
        ("What finished?", "", "output", None, True),
    ],
)
def test_read_only_voice_controls_preserve_the_live_session_handle(
    client, monkeypatch, phrase, continuation, role, action, focused
):
    import asyncio
    import json
    from contextlib import asynccontextmanager

    from jarvis import glassface_media_stream as stream

    class Provider:
        def __init__(self):
            self.events = asyncio.Queue()

        async def send(self, frame):
            command = json.loads(frame)["type"]
            if command == "session.start":
                self.events.put_nowait({"type": "session.started"})
            elif command == "session.input_audio.append":
                first, other = phrase.split(" ", 1)
                self.events.put_nowait(timed(first + " ", 30, 80, "first", role))
                self.events.put_nowait(timed(other, 81, 160, "last", role))
                if phrase == "What is done?":
                    import base64

                    self.events.put_nowait(
                        {"type": "session.output_audio.delta", "delta": base64.b64encode(b"v" * 160).decode()}
                    )
                if continuation == "after-read":
                    asyncio.get_running_loop().call_later(
                        0.64, self.events.put_nowait, timed("Tell it to retry. Send that.", 165, 225, "more")
                    )
                elif continuation:
                    self.events.put_nowait(timed(continuation, 165, 225, "more", role))
                asyncio.get_running_loop().call_later(
                    0.75, self.events.put_nowait, timed("fixture boundary", 600, 700, "sentinel", "output")
                )
            elif command == "session.close":
                self.events.put_nowait({"type": "session.closed", "usage": {"seconds": 15}})

        async def recv(self):
            return json.dumps(await self.events.get())

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield Provider()

    monkeypatch.setattr(stream, "connect", connection)
    _, headers = key(client, [routes.SCOPE])
    context = (
        BODY
        if focused
        else {"focus": "private-session-handle", "terminal": dict.fromkeys(BODY["terminal"], "")}
    )
    token = client.post(ROOT + "/tickets", headers=headers, json=context).json()["ticket"]
    claims = []
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": token})
        assert native.receive_json()["type"] == "ready"
        native.send_bytes(bytes(800))
        while True:
            raw = native.receive()
            if raw.get("bytes"):
                assert phrase == "What is done?" and len(claims) == 1
                continue
            event = json.loads(raw["text"])
            if event.get("text") == "fixture boundary":
                break
            if event["type"] == "utterance":
                claims.append(event)
        native.send_json({"type": "stop"})
        closing = native.receive_json()
        if closing["type"] == "clear":
            closing = native.receive_json()
        assert closing["reason"] == "ended"
    if not action:
        assert not claims
        return
    assert len(claims) == 1 and claims[0]["action"] == action
    checked = client.post(ROOT + "/verify", headers=headers, json={"proof": claims[0]["proof"]}).json()
    assert checked == {
        "operation": claims[0]["operation"],
        "focus": context["focus"],
        "text": {
            "finished": "What finished?",
            "open": "Show me that terminal",
            "home": "Take me home",
            "launcher": "Start a new terminal",
            "find": phrase.lower().rstrip("."),
        }[action],
    }


@pytest.mark.asyncio
async def test_native_playback_paces_bursts_and_clears_old_frames_before_resuming():
    import asyncio

    from jarvis.glassface_media_stream import HeadsetPlayback

    loop = asyncio.get_running_loop()
    queue = HeadsetPlayback()
    writes = []

    class Peer:
        async def send_bytes(self, raw):
            writes.append((loop.time(), raw))

        async def send_json(self, control):
            writes.append((loop.time(), control))

    peer = Peer()
    old, new = b"a" * 800, b"b" * 800
    queue.add(b"\xff" * 32000)
    assert queue.queued == 0 and not queue.audible
    queue.add(old * 40)  # One four-second upstream message.
    worker = asyncio.create_task(queue.play(peer, lambda raw: None))
    try:
        async with asyncio.timeout(1):
            while len(writes) < 6:
                await asyncio.sleep(0.005)
        assert writes[5][0] - writes[0][0] >= 0.18
        assert len(writes) < 10
        await queue.clear(peer)
        cleared = len(writes)
        assert writes[-1][1] == {"type": "clear"}
        queue.add(new)
        async with asyncio.timeout(0.4):
            while writes[-1][1] != new:
                await asyncio.sleep(0.005)
        assert [value for _, value in writes[cleared:]] == [new]
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def test_live_screen_changes_bind_actions_and_decisions_wait_for_a_break(client, monkeypatch):
    import asyncio
    import json
    import threading
    import time
    from contextlib import asynccontextmanager

    from jarvis import glassface_media_stream as stream

    focus = {"screen": "terminal", "session": "desktop:surf-B", "identity": "id-B", "binding": "bind-B"}
    pending = threading.Event()
    spoken = []

    class Provider:
        def __init__(self):
            self.events = asyncio.Queue()
            self.mic = 0

        async def send(self, message):
            event = json.loads(message)
            kind = event["type"]
            if kind == "session.start":
                self.events.put_nowait({"type": "session.started"})
            elif kind == "session.thinking.append":
                assert "Launcher work" in event["content"]
                self.events.put_nowait({"type": "error", "client_event_id": event["event_id"]})
                self.events.put_nowait({"type": "input_audio_buffer.speech_started"})
                self.events.put_nowait(timed("fixture open", 0, 1, "started", "output"))
            elif kind == "session.input_audio.append":
                self.mic += 1
                if self.mic == 7:
                    self.events.put_nowait(timed("Take me home.", 240, 480, "home"))
                elif self.mic == 9:
                    self.events.put_nowait({"type": "input_audio_buffer.speech_stopped"})
            elif kind == "session.commentary.append":
                spoken.append(event["content"])
                pending.set()
            elif kind == "session.close":
                self.events.put_nowait({"type": "session.closed", "usage": {"seconds": 15}})

        async def recv(self):
            return json.dumps(await self.events.get())

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield Provider()

    monkeypatch.setattr(stream, "connect", connection)
    _, headers = key(client, [routes.SCOPE])
    ticket = client.post(ROOT + "/tickets", headers=headers, json={**BODY, "view": {"screen": "home"}}).json()
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": ticket["ticket"]})
        assert native.receive_json() == {"type": "ready", "screenContext": True}
        native.send_json(
            {"type": "view", **focus, "label": "Launcher work", "summary": "Scope the launcher."}
        )
        assert native.receive_json()["text"] == "fixture open"
        native.send_json({"type": "decision", "label": "Tests"})
        native.send_json({"type": "decision", "label": "Tests"})
        for _ in range(9):
            native.send_bytes(b"\xff" * 800)
            time.sleep(0.085)
        assert not pending.is_set()
        assert native.receive_json()["text"] == "Take me home."
        action = native.receive_json()
        proof = client.post(ROOT + "/verify", headers=headers, json={"proof": action["proof"]}).json()
        assert proof["view"] == focus and proof["text"] == "Take me home"
        for _ in range(20):
            native.send_bytes(b"\xff" * 800)
            if pending.wait(0.085):
                break
        assert pending.is_set() and len(spoken) == 1 and "Tests" in spoken[0]
        pending.clear()
        native.send_json({"type": "receipt", "text": "Two terminals match."})
        for _ in range(20):
            native.send_bytes(b"\xff" * 800)
            if pending.wait(0.085):
                break
        assert pending.is_set() and len(spoken) == 2 and "Two terminals match." in spoken[1]
        native.send_json({"type": "stop"})
        assert native.receive_json()["reason"] == "ended"


@pytest.mark.parametrize("interrupt", ["hangup", "speak", "revoke"])
def test_a_full_provider_burst_does_not_block_interruption_or_grant_checks(client, monkeypatch, interrupt):
    import asyncio
    import base64
    import json
    from contextlib import asynccontextmanager

    from jarvis import glassface_media_stream as stream

    class Provider:
        def __init__(self):
            self.events = asyncio.Queue()
            self.mic = 0

        async def send(self, raw):
            kind = json.loads(raw)["type"]
            if kind == "session.start":
                self.events.put_nowait({"type": "session.started"})
            elif kind == "session.input_audio.append":
                self.mic += 1
                if self.mic == 1:
                    self.events.put_nowait(
                        {
                            "type": "session.output_audio.delta",
                            "delta": base64.b64encode(b"x" * 32_000).decode(),
                        }
                    )
                else:
                    self.events.put_nowait(timed("Hello.", 25, 75, "interrupt"))
            elif kind == "session.close":
                self.events.put_nowait({"type": "session.closed", "usage": {"seconds": 15}})

        async def recv(self):
            return json.dumps(await self.events.get())

    @asynccontextmanager
    async def connection(*args, **kw):
        yield Provider()

    monkeypatch.setattr(stream, "connect", connection)
    identity, headers = key(client, [routes.SCOPE])
    token = client.post(ROOT + "/tickets", headers=headers, json=BODY).json()["ticket"]
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": token})
        assert native.receive_json()["type"] == "ready"
        native.send_bytes(b"i" * 160)
        delivered = len(native.receive_bytes())
        if interrupt == "hangup":
            native.send_json({"type": "stop"})
        elif interrupt == "speak":
            native.send_bytes(b"i" * 160)
        else:
            with session_scope() as db:
                db.get(BotCredential, identity).revoked_at = now()
        cleared = False
        while True:
            event = native.receive()
            if event.get("bytes"):
                assert not cleared
                delivered += len(event["bytes"])
                continue
            control = json.loads(event["text"])
            if control["type"] == "clear":
                cleared = True
            elif control["type"] == "caption":
                assert interrupt == "speak" and control["text"] == "Hello."
                native.send_json({"type": "stop"})
            elif control["type"] == "ended":
                assert cleared and control["reason"] == ("unauthorized" if interrupt == "revoke" else "ended")
                break
        # Local hangup/barge-in can race at most a small jitter burst; grant polling adds 2 s.
        assert delivered <= (22_000 if interrupt == "revoke" else 6400)


@pytest.mark.parametrize(
    ("words", "action"),
    [
        ("Tell it to retry. Send that.", None),
        ("Open this terminal.", None),
        ("Take me home.", "home"),
        ("Start a new terminal.", "launcher"),
        ("Switch to the docs terminal.", "find"),
    ],
)
def test_uncertain_provider_clock_only_permits_screen_navigation(client, monkeypatch, words, action):
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
                await self.frames.put(timed(words, 580, 640, "uncertain"))
                await self.frames.put(timed("Okay.", 500, 600, "next", role="output"))
                if action:
                    asyncio.get_running_loop().call_later(
                        1.2,
                        self.frames.put_nowait,
                        timed("Test deadline.", 1200, 1300, "deadline", role="output"),
                    )
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
        if action:
            assert native.receive_json()["action"] == action
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
