"""Gemini 3.8 Live & Extended Thinking bridge, resamplers, structured tools, and completion notices."""

import asyncio
import base64
import cmath
import json
import math
import struct
import threading
import time
from array import array
from contextlib import contextmanager

import pytest
from cryptography.fernet import Fernet
from jarvis import glassface_dani as routes
from jarvis import glassface_gemini_stream as gemini
from jarvis.config import get_settings
from test_glassface_dani import TURN, key
from websockets.asyncio.client import connect
from websockets.sync.server import serve

ROOT = "/api/glassface/dani/live"
DESTINATIONS = [
    {"id": "home", "label": "Home", "parent": ""},
    {"id": "terminals", "label": "Terminals", "parent": "home"},
    {"id": "dani", "label": "Dani", "parent": "home"},
    {"id": "settings", "label": "Settings", "parent": "home"},
    {"id": "volume", "label": "Volume", "parent": "settings"},
    {"id": "voice_model", "label": "Voice model", "parent": "settings"},
]
HOME_VIEW = {
    "screen": "home",
    "page": "home",
    "selection": "Terminals",
    "choices": ["Terminals", "Dani", "Settings"],
    "actions": ["open", "set_volume", "set_voice_model", "start", "previous", "next", "select"],
    "destinations": DESTINATIONS,
}
TERMINAL_VIEW = {
    "screen": "terminal",
    "session": "davis:surf-123",
    "identity": "a" * 64,
    "binding": "b" * 64,
    "page": "watch",
    "selection": "",
    "choices": [],
    "actions": ["open", "set_volume", "set_voice_model", "start", "back", "previous", "next", "select"],
    "destinations": DESTINATIONS,
}


@pytest.fixture(autouse=True)
def gemini_settings(monkeypatch):
    monkeypatch.setenv("JARVIS_OPENAI_API_KEY", "synthetic-openai-key")
    monkeypatch.setenv("JARVIS_GEMINI_API_KEY", "synthetic-gemini-key")
    monkeypatch.setenv("JARVIS_EXTERNAL_SERVICES_ENABLED", "true")
    monkeypatch.setenv("JARVIS_INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@contextmanager
def fake_gemini_server(monkeypatch, handler):
    with serve(handler, "127.0.0.1", 0) as upstream:
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        port = upstream.socket.getsockname()[1]

        def connection(url, **kw):
            assert url == gemini.GEMINI_LIVE_URL
            return connect(f"ws://127.0.0.1:{port}", proxy=None, **kw)

        monkeypatch.setattr(gemini, "connect", connection)
        try:
            yield
        finally:
            upstream.shutdown()


def test_resamplers_preserve_speech_band_and_suppress_aliasing_across_arbitrary_chunks():
    pcmu_1k = bytes(
        gemini._mulaw_encode(round(8000 * math.sin(math.tau * 1000 * n / 8000)))
        for n in range(320)
    )
    up = gemini.UplinkResampler()
    pcm16k = b"".join(up.transcode(pcmu_1k[i : i + 37]) for i in range(0, len(pcmu_1k), 37))
    assert len(pcm16k) == 320 * 2 * 2
    up_samples = array("h")
    up_samples.frombytes(pcm16k)
    body = up_samples[32:]
    amp_1k = (
        2
        * abs(sum(s * cmath.exp(-1j * math.tau * 1000 * i / 16000) for i, s in enumerate(body)))
        / len(body)
    )
    amp_7k = (
        2
        * abs(sum(s * cmath.exp(-1j * math.tau * 7000 * i / 16000) for i, s in enumerate(body)))
        / len(body)
    )
    assert amp_1k > 6000
    assert amp_7k / amp_1k < 0.05

    def decimated_rms(freq_hz: float) -> float:
        raw24 = struct.pack(
            f"<{2400}h",
            *(round(10000 * math.sin(math.tau * freq_hz * i / 24000)) for i in range(2400)),
        )
        down = gemini.DownlinkResampler()
        out_pcmu = b"".join(down.transcode(raw24[i : i + 113]) for i in range(0, len(raw24), 113))
        assert len(out_pcmu) == 800
        decoded = [gemini._mulaw_decode(b) for b in out_pcmu[20:]]
        return math.sqrt(sum(x * x for x in decoded) / len(decoded))

    passband = decimated_rms(1000)
    aliased = decimated_rms(7000)
    assert passband > 5500
    assert aliased / passband < 0.03


def test_setup_message_enforces_non_blocking_tools_and_thinking_level():
    ext = gemini.setup_message("gemini-3.8-live-extended-thinking", True, thinking_level="high")["setup"]
    assert ext["model"] == "models/gemini-3.8-live-extended-thinking"
    assert ext["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "HIGH"}
    default_ext = gemini.setup_message("gemini-3.8-live-extended-thinking", True)["setup"]
    assert default_ext["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
    assert ext["inputAudioTranscription"] == {}
    assert ext["outputAudioTranscription"] == {}
    decls = ext["tools"][0]["functionDeclarations"]
    assert {d["name"] for d in decls} == {
        "adjust_setting",
        "navigate_glass",
        "open_terminal",
        "list_terminals",
        "read_terminal",
        "start_terminal",
        "send_terminal_message",
    }
    assert all(d["behavior"] == "NON_BLOCKING" for d in decls)

    # Verify flexible tool normalization across settings, singular/plural screens, and terminal routing
    assert gemini.normalize_tool_call("adjust_setting", {"setting": "volume", "value": "Medium"}) == (
        "navigate",
        {"name": "navigate", "command": "set_volume", "value": "Medium"},
    )
    assert gemini.normalize_tool_call("adjust_setting", {"setting": "earphone_amp", "value": "10"}) == (
        "navigate",
        {"name": "navigate", "command": "set_earphone_amp", "value": "10"},
    )
    assert gemini.normalize_tool_call("open_terminal", {"query": "the terminal"}, current_view={"screen": "home"}) == (
        "navigate",
        {"name": "navigate", "command": "open", "value": "terminals"},
    )
    assert gemini.normalize_tool_call(
        "navigate_glass",
        {"command": "open", "value": "Glassface"},
        current_view={"screen": "home", "destinations": [{"id": "home", "label": "Home", "parent": ""}]},
    ) == ("find", {"name": "find", "query": "Glassface"})
    assert gemini.normalize_tool_call("start_terminal", {"folder": "glassface repo"}) == (
        "start",
        {"name": "start", "folder": "glassface", "harness": "claude"},
    )

    std = gemini.setup_message("gemini-3.8-live", True, thinking_level="medium")["setup"]
    assert std["model"] == "models/gemini-3.8-live"
    assert "thinkingConfig" not in std["generationConfig"]


def test_status_advertises_gemini_live_and_ticket_routes_to_gemini_bridge(client, monkeypatch):
    _, headers = key(client, [routes.SCOPE])
    status = client.get("/api/glassface/dani/status", headers=headers).json()
    assert status["live"] is True and status["geminiLive"] is True

    seen_setup = []
    seen_tool_responses = []

    def provider(ws):
        assert ws.request.headers["x-goog-api-key"] == "synthetic-gemini-key"
        seen_setup.append(json.loads(ws.recv(timeout=8)))
        ws.send(json.dumps({"setupComplete": {}}))
        init_ctx = json.loads(ws.recv(timeout=8))
        assert init_ctx["clientContent"]["turnComplete"] is False

        while True:
            msg = json.loads(ws.recv(timeout=8))
            if "realtimeInput" in msg:
                assert msg["realtimeInput"]["audio"]["mimeType"] == "audio/pcm;rate=16000"
                break

        ws.send(
            json.dumps(
                {
                    "serverContent": {
                        "interactionStatus": "IN_PROGRESS",
                        "inputTranscription": {"text": "Take me to the terminal screen"},
                    }
                }
            )
        )
        ws.send(
            json.dumps(
                {
                    "toolCall": {
                        "functionCalls": [
                            {
                                "id": "call-nav-1",
                                "name": "navigate_glass",
                                "args": {"command": "open", "value": "terminals"},
                            }
                        ]
                    }
                }
            )
        )

        while True:
            msg = json.loads(ws.recv(timeout=8))
            if "toolResponse" in msg:
                seen_tool_responses.append(msg["toolResponse"])
                break

        pcm24 = struct.pack(f"<{960}h", *(4000 if (i // 12) % 2 == 0 else -4000 for i in range(960)))
        ws.send(
            json.dumps(
                {
                    "serverContent": {
                        "interactionStatus": "IDLE",
                        "turnComplete": True,
                        "outputTranscription": {"text": "Terminals is open."},
                        "modelTurn": {
                            "parts": [
                                {"text": "internal reasoning", "thought": True},
                                {
                                    "inlineData": {
                                        "mimeType": "audio/pcm;rate=24000",
                                        "data": base64.b64encode(pcm24).decode("ascii"),
                                    }
                                },
                            ]
                        },
                    }
                }
            )
        )
        try:
            while ws.recv(timeout=2):
                pass
        except Exception:
            pass

    with fake_gemini_server(monkeypatch, provider):
        ticket_resp = client.post(
            ROOT + "/tickets",
            headers=headers,
            json={
                "terminal": TURN["terminal"],
                "focus": "session-focus-1",
                "view": HOME_VIEW,
                "voice": {"model": "gemini-3.8-live-extended-thinking", "thinking": "medium"},
            },
        )
        assert ticket_resp.status_code == 200, ticket_resp.text
        ticket = ticket_resp.json()["ticket"]

        with client.websocket_connect(ROOT) as ws_client:
            ws_client.send_json({"type": "start", "ticket": ticket})
            ready_msg = ws_client.receive_json()
            assert ready_msg == {"type": "ready", "screenContext": True, "completions": True}

            voiced_frame = bytes([0xCE] * 320)
            for _ in range(4):
                ws_client.send_bytes(voiced_frame)

            user_cap = ws_client.receive_json()
            assert user_cap["type"] == "caption" and user_cap["role"] == "user"
            assert 0 <= user_cap["start_ms"] < user_cap["end_ms"] <= 160

            utterance = ws_client.receive_json()
            assert utterance["type"] == "utterance"
            assert utterance["action"] == "navigate" and utterance["command"] == "open"
            assert (utterance["start_ms"], utterance["end_ms"]) == (
                user_cap["start_ms"],
                user_cap["end_ms"],
            )

            verified = client.post(
                ROOT + "/verify", headers=headers, json={"proof": utterance["proof"]}
            )
            assert verified.status_code == 200
            assert verified.json()["tool"] == {
                "name": "navigate",
                "command": "open",
                "value": "terminals",
            }

            ws_client.send_json(
                {
                    "type": "receipt",
                    "operation": utterance["operation"],
                    "text": "Glass shows roster, Terminal 1.",
                }
            )

            assistant_cap = None
            audio_bytes = bytearray()
            for _ in range(10):
                frame = ws_client.receive()
                if frame.get("bytes"):
                    audio_bytes.extend(frame["bytes"])
                elif frame.get("text"):
                    data = json.loads(frame["text"])
                    if data.get("type") == "caption" and data.get("role") == "assistant":
                        assistant_cap = data["text"]
                if assistant_cap and audio_bytes:
                    break

            assert assistant_cap == "Terminals is open."
            assert len(audio_bytes) > 0
            ws_client.send_json({"type": "stop"})

    assert seen_setup[0]["setup"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MEDIUM"}
    resp = seen_tool_responses[0]["functionResponses"][0]
    assert resp == {
        "id": "call-nav-1",
        "name": "navigate_glass",
        "response": {"result": "Glass shows roster, Terminal 1."},
    }
    assert "scheduling" not in resp


def test_direct_in_terminal_send_and_completion_notice_delivery(client, monkeypatch):
    _, headers = key(client, [routes.SCOPE])
    received_notices = []
    notice_ready = threading.Event()

    def provider(ws):
        ws.recv(timeout=8)  # setup
        ws.send(json.dumps({"setupComplete": {}}))
        ws.recv(timeout=8)  # initial context

        while True:
            msg = json.loads(ws.recv(timeout=8))
            if "realtimeInput" in msg:
                break

        ws.send(
            json.dumps(
                {
                    "serverContent": {
                        "interactionStatus": "IN_PROGRESS",
                        "inputTranscription": {"text": "Run pytest on the migration suite"},
                    }
                }
            )
        )
        ws.send(
            json.dumps(
                {
                    "toolCall": {
                        "functionCalls": [
                            {
                                "id": "call-send-1",
                                "name": "send_terminal_message",
                                "args": {"message": "Run pytest on the migration suite"},
                            }
                        ]
                    }
                }
            )
        )

        while True:
            msg = json.loads(ws.recv(timeout=8))
            if "toolResponse" in msg:
                assert msg["toolResponse"]["functionResponses"][0]["response"] == {
                    "result": "Queued in Jarvis."
                }
                break

        ws.send(json.dumps({"serverContent": {"interactionStatus": "IDLE", "turnComplete": True}}))

        while True:
            msg = json.loads(ws.recv(timeout=8))
            if "clientContent" in msg and msg["clientContent"].get("turnComplete") is True:
                received_notices.append(msg["clientContent"]["turns"][0]["parts"][0]["text"])
                notice_ready.set()
                break

        ws.send(
            json.dumps(
                {
                    "serverContent": {
                        "interactionStatus": "IDLE",
                        "turnComplete": True,
                        "outputTranscription": {"text": "Worker suite finished and all 12 tests passed."},
                    }
                }
            )
        )
        try:
            while ws.recv(timeout=2):
                pass
        except Exception:
            pass

    with fake_gemini_server(monkeypatch, provider):
        ticket = client.post(
            ROOT + "/tickets",
            headers=headers,
            json={
                "terminal": TURN["terminal"],
                "focus": "session-focus-2",
                "view": TERMINAL_VIEW,
                "voice": {"model": "gemini-3.8-live-extended-thinking", "thinking": "high"},
            },
        ).json()["ticket"]

        with client.websocket_connect(ROOT) as ws_client:
            ws_client.send_json({"type": "start", "ticket": ticket})
            assert ws_client.receive_json()["completions"] is True

            ws_client.send_bytes(bytes([0xCE] * 320))
            ws_client.send_bytes(bytes([0xCE] * 320))

            _ = ws_client.receive_json()
            utterance = ws_client.receive_json()
            assert utterance["action"] == "send"
            verified = client.post(
                ROOT + "/verify", headers=headers, json={"proof": utterance["proof"]}
            ).json()
            assert verified["tool"] == {
                "name": "send",
                "message": "Run pytest on the migration suite",
            }
            assert verified["view"]["session"] == "davis:surf-123"

            ws_client.send_json(
                {
                    "type": "receipt",
                    "operation": utterance["operation"],
                    "text": "Queued in Jarvis.",
                }
            )
            ws_client.send_json(
                {
                    "type": "completion",
                    "label": "Worker suite",
                    "summary": "All 12 tests passed.",
                }
            )
            silence = bytes([0xFF] * 320)
            for _ in range(48):
                ws_client.send_bytes(silence)
                time.sleep(0.032)
                if notice_ready.is_set():
                    break
            assert notice_ready.wait(timeout=2)
            msg = ws_client.receive_json()
            assert msg["role"] == "assistant" and "12 tests passed" in msg["text"]
            ws_client.send_json({"type": "stop"})

    assert any("Worker suite" in n and "All 12 tests passed." in n for n in received_notices)


def test_mic_timeline_resets_across_turns_and_downlink_handles_long_gemini_burst():
    tl = gemini.MicTimeline()
    voiced = bytes([0xCE] * 320)
    silence = bytes([0xFF] * 320)
    # Turn 1 user speech: 0..160 ms
    for _ in range(4):
        tl.observe_frame(voiced, speaker_busy=False)
    tl.add_transcription("Hey Dani")
    # Dani replies for 10 frames (160..560 ms), then turnComplete fires
    for _ in range(10):
        tl.observe_frame(voiced, speaker_busy=True)
    tl.mark_turn_complete()
    for _ in range(5):
        tl.observe_frame(silence, speaker_busy=False)
    # Turn 2 speech at 760 ms (test loud 0xA0 and quiet 0xCE frames):
    for _ in range(4):
        tl.observe_frame(bytes([0xA0] * 320), speaker_busy=False)
    s2, e2 = tl.add_transcription("Open terminals")
    assert s2 >= 760 and e2 > s2
    claim = tl.current_claim_span()
    assert claim == (s2, e2, "Open terminals")
    # Multi-tool batch in same turn reuses verified span cleanly
    tl.consume_turn(s2, e2, "Open terminals")
    assert tl.current_claim_span() == (s2, e2, "Open terminals")

    # Quiet speech below ACTIVE_SAMPLES still respects turn_floor_ms:
    tl.mark_turn_complete()
    for _ in range(6):
        tl.observe_frame(voiced, speaker_busy=False)
    sq, eq = tl.add_transcription("Run all integration tests now")
    assert sq >= 920 and eq > sq

    # Delayed toolCall arriving AFTER intermediate filler + turnComplete still reuses real user span!
    tl.mark_turn_complete()
    for _ in range(8):
        tl.observe_frame(voiced, speaker_busy=True)
    # Stray room noise after filler must NOT erase last_verified_span (sq..eq)
    tl.observe_frame(bytes([0xA0] * 320), speaker_busy=False)
    tl.reset_turn()
    delayed_claim = tl.current_claim_info()
    assert delayed_claim == (sq, eq, "Run all integration tests now", True)

    async def check_burst():
        dl = gemini.GeminiDownlink()
        # 25 seconds of faster-than-realtime audio must buffer without LiveFailure
        dl.add(bytes([0xCE] * (25 * gemini.RATE)))
        assert dl.queued == 25 * gemini.RATE
        dl.discard()

    asyncio.run(check_burst())


def test_unified_gpt_live_mirrors_gemini_tools_direct_sends_and_completions(client, monkeypatch):
    from contextlib import asynccontextmanager
    from jarvis import glassface_media_stream as gpt_stream
    from jarvis import glassface_tools, memory_learning

    # Fast deterministic matcher handles settings, singular/plural screens, and explicit sends in 0 ms
    unified_home = {
        **HOME_VIEW,
        "actions": ["open", "set_volume", "set_voice_model", "set_earphone_amp", "set_keep_awake", "set_spoken_replies"],
    }
    assert glassface_tools.parse_unified_fast("Can you turn the volume up to medium?", unified_home) == (
        "navigate",
        {"name": "navigate", "command": "set_volume", "value": "medium"},
    )
    assert glassface_tools.parse_unified_fast("Set earphone amp to 12", unified_home) == (
        "navigate",
        {"name": "navigate", "command": "set_earphone_amp", "value": "12"},
    )
    assert glassface_tools.parse_unified_fast("Can you open the terminal?", unified_home) == (
        "navigate",
        {"name": "navigate", "command": "open", "value": "terminals"},
    )

    _, headers = key(client, [routes.SCOPE])
    unified_term = {
        **TERMINAL_VIEW,
        "actions": ["open", "back", "set_volume", "set_voice_model", "set_earphone_amp", "set_keep_awake", "set_spoken_replies"],
    }
    commentaries = []
    commentary_event = threading.Event()

    def infer(owner, path, body, *args, **kwargs):
        payload = json.loads(body["input"])
        assert payload["screen"] == "terminal"
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "tool": "send_terminal_message",
                                "setting": "",
                                "command": "",
                                "value": "",
                                "query": "",
                                "detail": "",
                                "folder": "",
                                "harness": "",
                                "model": "",
                                "effort": "",
                                "message": "Run pytest on auth",
                                "target": "",
                            }
                        )
                    }
                }
            ]
        }

    class FakeGptLive:
        def __init__(self):
            self.events = asyncio.Queue()
            self.mic_count = 0

        async def send(self, raw):
            msg = json.loads(raw)
            kind = msg["type"]
            if kind == "session.start":
                assert msg["session"]["audio"]["output"]["voice"] == "marin"
                self.events.put_nowait({"type": "session.started"})
            elif kind == "session.input_audio.append":
                self.mic_count += 1
                if self.mic_count == 2:
                    self.events.put_nowait(
                        {
                            "type": "session.input_transcript.delta",
                            "event_id": "u-1",
                            "delta": "Run pytest on auth",
                        }
                    )
                    self.events.put_nowait({"type": "input_audio_buffer.speech_stopped"})
            elif kind == "session.commentary.append":
                commentaries.append(msg["content"])
                self.events.put_nowait({"type": "session.commentary.appended", "client_event_id": msg["event_id"]})
                if len(commentaries) >= 2:
                    commentary_event.set()
            elif kind == "session.close":
                self.events.put_nowait({"type": "session.closed", "usage": {"seconds": 15}})

        async def recv(self):
            return json.dumps(await self.events.get())

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        yield FakeGptLive()

    monkeypatch.setattr(gpt_stream, "connect", fake_connect)
    monkeypatch.setattr(memory_learning, "provider_request", infer)

    ticket = client.post(
        ROOT + "/tickets",
        headers=headers,
        json={
            "terminal": TURN["terminal"],
            "focus": "gpt-live-focus-1",
            "view": unified_term,
            "voice": {"model": "gpt-live-1"},
        },
    ).json()["ticket"]

    with client.websocket_connect(ROOT) as ws_client:
        ws_client.send_json({"type": "start", "ticket": ticket})
        ready_msg = ws_client.receive_json()
        assert ready_msg == {"type": "ready", "screenContext": True, "completions": True}

        for _ in range(3):
            ws_client.send_bytes(bytes([0xA0] * 320))

        cap = ws_client.receive_json()
        assert cap["type"] == "caption" and cap["role"] == "user"
        assert 0 <= cap["start_ms"] < cap["end_ms"] <= 120

        utt = ws_client.receive_json()
        assert utt["type"] == "utterance" and utt["action"] == "send" and utt["structured"] is True
        verified = client.post(ROOT + "/verify", headers=headers, json={"proof": utt["proof"]}).json()
        assert verified["tool"] == {"name": "send", "message": "Run pytest on auth"}

        ws_client.send_json({"type": "receipt", "operation": utt["operation"], "text": "Queued in Jarvis."})
        ws_client.send_json({"type": "completion", "label": "Worker suite", "summary": "Auth tests green."})
        for _ in range(40):
            ws_client.send_bytes(bytes([0xFF] * 320))
            if commentary_event.wait(0.035):
                break
        assert commentary_event.is_set()
        ws_client.send_json({"type": "stop"})
        assert ws_client.receive_json()["reason"] == "ended"

    assert any("Queued in Jarvis." in c for c in commentaries)
    assert any("Worker suite" in c and "Auth tests green." in c for c in commentaries)
