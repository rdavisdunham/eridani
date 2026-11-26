"""Tests for the direct Glass voice WebSocket (/api/glassface/voice, Layers 1 & 2)."""

import asyncio
import base64
import json
from contextlib import asynccontextmanager

from jarvis import glassface_live as live
from jarvis import glassface_voice as gv
from jarvis.glassface_gemini_stream import _mulaw_decode, _mulaw_encode


class FakeGlassPeer:
    def __init__(self, incoming: list[dict]):
        self.incoming = asyncio.Queue()
        for item in incoming:
            self.incoming.put_nowait(item)
        self.sent_json: list[dict] = []
        self.sent_bytes: list[bytes] = []

    async def receive(self) -> dict:
        return await self.incoming.get()

    async def send_json(self, payload: dict) -> None:
        self.sent_json.append(payload)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)


class FakeProviderWS:
    def __init__(self, events: list[dict]):
        self.events = asyncio.Queue()
        for ev in events:
            self.events.put_nowait(ev)
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        ev = await self.events.get()
        if ev is None:
            from websockets.exceptions import ConnectionClosedOK
            from websockets.frames import Close

            raise ConnectionClosedOK(Close(1000, "done"), Close(1000, "done"))
        return json.dumps(ev)


def test_gpt_gain_lut_lifts_quiet_speech_without_hard_clipping():
    # Silence stays pure digital silence
    assert gv.GPT_GAIN_LUT[0xFF] == 0xFF
    assert gv.GPT_GAIN_LUT[0x7F] == 0xFF
    # Quiet speech (~2000 linear) gets lifted ~1.85x (~+5.4 dB)
    quiet_code = _mulaw_encode(2000)
    lifted = _mulaw_decode(gv.GPT_GAIN_LUT[quiet_code])
    assert 3400 <= lifted <= 4000
    # Negative speech preserves sign symmetrically
    neg_code = _mulaw_encode(-2000)
    assert _mulaw_decode(gv.GPT_GAIN_LUT[neg_code]) == -lifted
    # Loud peak stays smoothly below full scale (zero flat-top clipping)
    peak_code = _mulaw_encode(28000)
    peak_lifted = _mulaw_decode(gv.GPT_GAIN_LUT[peak_code])
    assert 28000 <= peak_lifted <= 32635


def test_parse_local_tool_fast_matches_settings_navigation_and_screen():
    assert gv.parse_local_tool_fast("Hey Dani, set volume to 9") == (
        "adjust_setting",
        {"setting": "volume", "value": "9"},
    )
    assert gv.parse_local_tool_fast("turn it up") == ("adjust_setting", {"setting": "volume", "value": "up"})
    assert gv.parse_local_tool_fast("switch to gpt-live") == (
        "adjust_setting",
        {"setting": "voice_model", "value": "gpt-live"},
    )
    assert gv.parse_local_tool_fast("keep screen on") == (
        "adjust_setting",
        {"setting": "keep_awake", "value": "on"},
    )
    assert gv.parse_local_tool_fast("open terminals") == (
        "navigate_glass",
        {"command": "open", "value": "terminals"},
    )
    assert gv.parse_local_tool_fast("go home") == ("navigate_glass", {"command": "open", "value": "home"})
    assert gv.parse_local_tool_fast("what screen am I on?") == ("get_screen", {})
    assert gv.parse_local_tool_fast("tell me a joke about penguins") is None


def test_parse_glass_tool_fast_matches_layer3_remotea_commands():
    assert gv.parse_glass_tool_fast("what terminals are open?") == ("list_terminals", {"detail": "brief"})
    assert gv.parse_glass_tool_fast("Hey Dani, what did it last say?") == ("read_terminal", {"query": ""})
    assert gv.parse_glass_tool_fast("tell glassface to run the tests") == (
        "send_terminal_message",
        {"message": "run the tests", "target": "glassface"},
    )
    assert gv.parse_glass_tool_fast("start a new claude terminal in glassface") == (
        "start_terminal",
        {"folder": "glassface", "harness": "claude"},
    )
    assert gv.parse_glass_tool_fast("what terminals are open?", remotea_tools=False) is None


def test_bridge_gemini_multi_turn_and_interrupt_without_client_content():
    async def run():
        pcm24k = b"\x00\x04\x00\x04\x00\x04" * 400
        b64_audio = base64.b64encode(pcm24k).decode("ascii")
        provider = FakeProviderWS(
            [
                {"setupComplete": {}},
                {"serverContent": {"inputTranscription": {"text": "Hey Dani."}}},
                {
                    "serverContent": {
                        "outputTranscription": {"text": "Hey Davin!"},
                        "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": b64_audio}}]},
                        "turnComplete": True,
                    }
                },
                {"serverContent": {"inputTranscription": {"text": "Tell me a story."}}},
                {
                    "serverContent": {
                        "outputTranscription": {"text": "Once upon a time..."},
                        "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": b64_audio}}]},
                    }
                },
            ]
        )

        @asynccontextmanager
        async def fake_connect(_url, **_kw):
            yield provider

        peer = FakeGlassPeer([])
        usage = live.Usage()

        async def recheck():
            return None

        task = asyncio.create_task(
            gv.bridge_gemini(
                peer,
                "gemini-3.8-live-extended-thinking",
                "test-key",
                usage,
                recheck,
                300,
                thinking="low",
                connector=fake_connect,
            )
        )

        for _ in range(50):
            if any(m.get("type") == "ready" for m in peer.sent_json):
                break
            await asyncio.sleep(0.01)
        assert any(m.get("type") == "ready" for m in peer.sent_json)

        await peer.incoming.put({"type": "websocket.receive", "bytes": b"\x20" * 320})
        await asyncio.sleep(0.12)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "interrupt"})})
        await asyncio.sleep(0.05)
        await peer.incoming.put({"type": "websocket.receive", "bytes": b"\x20" * 320})
        await asyncio.sleep(0.05)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        assert provider.sent[0].get("setup", {}).get("tools") is None
        assert all("clientContent" not in msg for msg in provider.sent)
        assert sum(1 for msg in provider.sent if "realtimeInput" in msg) == 2
        captions = [(m["role"], m["text"]) for m in peer.sent_json if m.get("type") == "caption"]
        assert ("user", "Hey Dani.") in captions
        assert ("assistant", "Hey Davin!") in captions
        assert ("user", "Tell me a story.") in captions
        assert any(m.get("type") == "clear" for m in peer.sent_json)
        assert len(peer.sent_bytes) > 0

    asyncio.run(run())


def test_bridge_gemini_layer2_local_tools_dispatches_to_glass_without_client_content():
    async def run():
        provider = FakeProviderWS(
            [
                {"setupComplete": {}},
                {
                    "toolCall": {
                        "functionCalls": [
                            {"id": "fc-1", "name": "adjust_setting", "args": {"setting": "volume", "value": "9"}}
                        ]
                    }
                },
            ]
        )

        @asynccontextmanager
        async def fake_connect(_url, **_kw):
            yield provider

        peer = FakeGlassPeer([])
        usage = live.Usage()

        async def recheck():
            return None

        task = asyncio.create_task(
            gv.bridge_gemini(
                peer,
                "gemini-3.8-live-extended-thinking",
                "test-key",
                usage,
                recheck,
                300,
                thinking="low",
                tools=["local"],
                screen={"screen": "home", "volume": "7/10"},
                connector=fake_connect,
            )
        )

        # Wait for tool dispatch to Glass
        tool_msg = None
        for _ in range(80):
            tool_msg = next((m for m in peer.sent_json if m.get("type") == "tool"), None)
            if tool_msg:
                break
            await asyncio.sleep(0.01)
        assert tool_msg == {
            "type": "tool",
            "id": "fc-1",
            "name": "adjust_setting",
            "args": {"setting": "volume", "value": "9"},
        }

        # Glass replies immediately with tool_result + fresh screen
        await peer.incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "tool_result",
                        "id": "fc-1",
                        "ok": True,
                        "result": "Volume set to 9/10.",
                        "screen": {"screen": "home", "volume": "9/10"},
                    }
                ),
            }
        )
        for _ in range(80):
            if any("toolResponse" in msg for msg in provider.sent):
                break
            await asyncio.sleep(0.01)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        # Setup included local tool declarations + initial screen, and ZERO clientContent frames were sent
        setup = provider.sent[0]["setup"]
        decl_names = [d["name"] for d in setup["tools"][0]["functionDeclarations"]]
        assert decl_names == ["adjust_setting", "navigate_glass", "get_screen"]
        assert '"volume": "7/10"' in setup["systemInstruction"]["parts"][0]["text"]
        assert all("clientContent" not in msg for msg in provider.sent)
        resp = next(msg["toolResponse"]["functionResponses"][0] for msg in provider.sent if "toolResponse" in msg)
        assert resp["id"] == "fc-1"
        assert resp["response"]["ok"] is True
        assert resp["response"]["result"] == "Volume set to 9/10."
        assert resp["response"]["screen"]["volume"] == "9/10"

    asyncio.run(run())


def test_bridge_gpt_multi_turn_and_layer2_local_delegation():
    async def run():
        pcmu_audio = base64.b64encode(bytes([_mulaw_encode(2000)]) * 320).decode("ascii")
        provider = FakeProviderWS(
            [
                {"type": "session.started"},
                {"type": "session.input_transcript.delta", "delta": "Open terminals"},
                {"type": "session.delegation.created", "delegation": {"id": "del-1", "target": "client"}},
                {"type": "session.output_transcript.delta", "delta": "Opened Terminals."},
                {"type": "session.output_audio.delta", "delta": pcmu_audio},
            ]
        )

        @asynccontextmanager
        async def fake_connect(_url, **_kw):
            yield provider

        peer = FakeGlassPeer([])
        usage = live.Usage()

        async def recheck():
            return None

        task = asyncio.create_task(
            gv.bridge_gpt(
                peer,
                "gpt-live-1",
                "test-openai-key",
                usage,
                recheck,
                300,
                identity="glass-1",
                tools=["local"],
                screen={"screen": "home"},
                connector=fake_connect,
            )
        )

        # Wait for Glass tool message triggered by GPT-Live delegation
        tool_msg = None
        for _ in range(100):
            tool_msg = next((m for m in peer.sent_json if m.get("type") == "tool"), None)
            if tool_msg:
                break
            await asyncio.sleep(0.01)
        assert tool_msg is not None
        assert tool_msg["name"] == "navigate_glass"
        assert tool_msg["args"] == {"command": "open", "value": "terminals"}

        await peer.incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "tool_result",
                        "id": tool_msg["id"],
                        "ok": True,
                        "result": "Opened Terminals.",
                        "screen": {"screen": "roster", "title": "Terminals"},
                    }
                ),
            }
        )
        await peer.incoming.put({"type": "websocket.receive", "bytes": b"\x20" * 320})
        for _ in range(100):
            if any(m.get("type") == "session.commentary.append" for m in provider.sent):
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.14)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "interrupt"})})
        await asyncio.sleep(0.04)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        assert provider.sent[0]["type"] == "session.start"
        assert provider.sent[0]["session"]["delegation"] == {"type": "client"}
        assert any(m.get("type") == "session.input_audio.append" for m in provider.sent)
        commentary = next(m for m in provider.sent if m.get("type") == "session.commentary.append")
        assert commentary["delegation_id"] == "del-1"
        assert "Opened Terminals." in commentary["content"]
        assert any(m.get("type") == "clear" for m in peer.sent_json)
        assert len(peer.sent_bytes) > 0
        # Verify GPT_GAIN_LUT boosted downlink audio above original 2000 linear amplitude
        assert _mulaw_decode(peer.sent_bytes[0][0]) > 3400

    asyncio.run(run())


def test_voice_socket_preempts_stale_session_for_same_identity(monkeypatch):
    async def run():
        closed_stale = []

        class StaleWS:
            async def close(self, code=1000):
                closed_stale.append(code)
                gv.active.discard("glass-1")
                gv.active_peers.pop("glass-1", None)

        class NewWS:
            def __init__(self):
                self.accepted = False
                self.sent_json = []
                self.closed = []

            async def accept(self):
                self.accepted = True

            async def receive_text(self):
                return json.dumps(
                    {
                        "type": "start",
                        "token": "eri_bot_" + "x" * 24,
                        "model": "gemini-3.8-live-extended-thinking",
                        "thinking": "low",
                        "tools": ["local"],
                        "screen": {"screen": "home"},
                    }
                )

            async def send_json(self, payload):
                self.sent_json.append(payload)

            async def close(self, code=1000):
                self.closed.append(code)

        bridged = []

        @asynccontextmanager
        async def fake_slot(_identity, _model, _usage, _seconds):
            async def recheck():
                return None

            yield recheck

        async def fake_bridge(ws, model, *_args, **kw):
            bridged.append((ws, model, kw.get("tools"), kw.get("screen")))

        class DummySettings:
            gemini_api_key = "k"
            openai_api_key = "k"

        monkeypatch.setattr(gv, "authenticate_glass_token", lambda _t: "glass-1")
        monkeypatch.setattr(gv, "authorized_settings", lambda _i, _p: DummySettings())
        monkeypatch.setattr(gv, "leased_slot", fake_slot)
        monkeypatch.setattr(gv, "bridge_gemini", fake_bridge)

        gv.active.add("glass-1")
        gv.active_peers["glass-1"] = StaleWS()
        ws = NewWS()
        try:
            await gv.voice_socket(ws)
        finally:
            gv.active.discard("glass-1")
            gv.active_peers.pop("glass-1", None)

        assert closed_stale == [1000]
        assert len(bridged) == 1
        assert bridged[0][2] == ["local"]
        assert bridged[0][3] == {"screen": "home"}
        assert ws.sent_json == []

    asyncio.run(run())


def test_bridge_gemini_layer3_remotea_tools_dispatches_without_client_content():
    async def run():
        provider = FakeProviderWS(
            [
                {"setupComplete": {}},
                {"toolCall": {"functionCalls": [{"id": "r-1", "name": "list_terminals", "args": {"detail": "brief"}}]}},
                {
                    "toolCall": {
                        "functionCalls": [
                            {
                                "id": "r-2",
                                "name": "send_terminal_message",
                                "args": {"message": "run pytest", "target": "scratch"},
                            }
                        ]
                    }
                },
            ]
        )

        @asynccontextmanager
        async def fake_connect(_url, **_kw):
            yield provider

        peer = FakeGlassPeer([])
        usage = live.Usage()

        async def recheck():
            return None

        task = asyncio.create_task(
            gv.bridge_gemini(
                peer,
                "gemini-3.8-live-extended-thinking",
                "test-key",
                usage,
                recheck,
                300,
                thinking="low",
                tools=["local", "remotea"],
                screen={"screen": "watch", "terminal_id": "t-1", "terminal_label": "scratch"},
                connector=fake_connect,
            )
        )

        seen_ids = set()
        for _ in range(100):
            for m in list(peer.sent_json):
                if m.get("type") == "tool" and m["id"] not in seen_ids:
                    seen_ids.add(m["id"])
                    await peer.incoming.put(
                        {
                            "type": "websocket.receive",
                            "text": json.dumps(
                                {
                                    "type": "tool_result",
                                    "id": m["id"],
                                    "ok": True,
                                    "result": f"Ran {m['name']}",
                                    "screen": {"screen": "watch", "terminal_label": "scratch"},
                                }
                            ),
                        }
                    )
            if len(seen_ids) == 2 and sum(1 for msg in provider.sent if "toolResponse" in msg) == 2:
                break
            await asyncio.sleep(0.01)

        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        decls = [d["name"] for d in provider.sent[0]["setup"]["tools"][0]["functionDeclarations"]]
        assert "list_terminals" in decls
        assert "send_terminal_message" in decls
        assert "start_terminal" in decls
        assert all("clientContent" not in msg for msg in provider.sent)
        resps = [msg["toolResponse"]["functionResponses"][0] for msg in provider.sent if "toolResponse" in msg]
        assert [r["id"] for r in resps] == ["r-1", "r-2"]
        assert all(r["response"]["ok"] is True for r in resps)

    asyncio.run(run())


def test_bridge_gpt_layer3_remotea_delegation():
    async def run():
        provider = FakeProviderWS(
            [
                {"type": "session.started"},
                {"type": "session.input_transcript.delta", "delta": "tell scratch to run pytest"},
                {"type": "session.delegation.created", "delegation": {"id": "del-r1", "target": "client"}},
            ]
        )

        @asynccontextmanager
        async def fake_connect(_url, **_kw):
            yield provider

        peer = FakeGlassPeer([])
        usage = live.Usage()

        async def recheck():
            return None

        task = asyncio.create_task(
            gv.bridge_gpt(
                peer,
                "gpt-live-1",
                "test-openai-key",
                usage,
                recheck,
                300,
                identity="glass-1",
                tools=["local", "remotea"],
                screen={"screen": "home"},
                connector=fake_connect,
            )
        )

        tool_msg = None
        for _ in range(100):
            tool_msg = next((m for m in peer.sent_json if m.get("type") == "tool"), None)
            if tool_msg:
                break
            await asyncio.sleep(0.01)
        assert tool_msg is not None
        assert tool_msg["name"] == "send_terminal_message"
        assert tool_msg["args"] == {"message": "run pytest", "target": "scratch"}

        await peer.incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "tool_result",
                        "id": tool_msg["id"],
                        "ok": True,
                        "result": "Sent to scratch (submitted).",
                        "screen": {"screen": "home"},
                    }
                ),
            }
        )
        for _ in range(100):
            if any(m.get("type") == "session.commentary.append" for m in provider.sent):
                break
            await asyncio.sleep(0.01)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        commentary = next(m for m in provider.sent if m.get("type") == "session.commentary.append")
        assert commentary["delegation_id"] == "del-r1"
        assert "Sent to scratch (submitted)." in commentary["content"]

    asyncio.run(run())


def test_parse_glass_tool_fast_layer4_triage_and_open_it():
    assert gv.parse_glass_tool_fast("skip for now") == ("triage_terminal", {"action": "skip"})
    assert gv.parse_glass_tool_fast("nothing for now") == ("triage_terminal", {"action": "skip"})
    assert gv.parse_glass_tool_fast("Hey Dani, next terminal please") == ("triage_terminal", {"action": "next"})
    assert gv.parse_glass_tool_fast("what's waiting?") == ("triage_terminal", {"action": "queue"})
    assert gv.parse_glass_tool_fast("let me see it") == ("open_terminal", {"query": "it"})
    assert gv.parse_glass_tool_fast("pull it up") == ("open_terminal", {"query": "it"})


def test_bridge_gemini_layer4_terminal_event_uses_turn_complete_true_and_triage():
    async def run():
        provider = FakeProviderWS(
            [
                {"setupComplete": {}},
                {"toolCall": {"functionCalls": [{"id": "t-1", "name": "triage_terminal", "args": {"action": "skip"}}]}},
            ]
        )

        @asynccontextmanager
        async def fake_connect(_url, **_kw):
            yield provider

        peer = FakeGlassPeer([])
        usage = live.Usage()

        async def recheck():
            return None

        task = asyncio.create_task(
            gv.bridge_gemini(
                peer,
                "gemini-3.8-live-extended-thinking",
                "test-key",
                usage,
                recheck,
                300,
                thinking="low",
                tools=["local", "remotea"],
                screen={"screen": "home"},
                connector=fake_connect,
            )
        )

        for _ in range(100):
            if any(m.get("type") == "ready" for m in peer.sent_json):
                break
            await asyncio.sleep(0.01)

        await peer.incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "terminal_event",
                        "event_id": "comp:1",
                        "terminal_id": "davis:surf-1",
                        "label": "Scratch 1",
                        "kind": "finished",
                        "summary": "All unit tests passed.",
                        "question": "",
                        "remaining": 1,
                    }
                ),
            }
        )
        # Subsequent spoken audio uplink must continue cleanly after terminal_event
        await peer.incoming.put({"type": "websocket.receive", "bytes": b"\x22" * 320})

        seen_tool = False
        for _ in range(100):
            tool_msg = next((m for m in peer.sent_json if m.get("type") == "tool" and m.get("id") == "t-1"), None)
            if tool_msg and not seen_tool:
                seen_tool = True
                await peer.incoming.put(
                    {
                        "type": "websocket.receive",
                        "text": json.dumps(
                            {
                                "type": "tool_result",
                                "id": "t-1",
                                "ok": True,
                                "result": "Skipped Scratch 1. 1 more waiting.",
                                "screen": {"screen": "home"},
                            }
                        ),
                    }
                )
            if seen_tool and any("toolResponse" in m for m in provider.sent) and any("clientContent" in m for m in provider.sent):
                break
            await asyncio.sleep(0.01)

        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        decls = [d["name"] for d in provider.sent[0]["setup"]["tools"][0]["functionDeclarations"]]
        assert "triage_terminal" in decls
        cc_frames = [m["clientContent"] for m in provider.sent if "clientContent" in m]
        assert len(cc_frames) == 1
        assert cc_frames[0]["turnComplete"] is True
        assert all(cc.get("turnComplete") is True for cc in cc_frames)
        prompt_text = cc_frames[0]["turns"][0]["parts"][0]["text"]
        assert "Scratch 1" in prompt_text
        assert "1 more waiting" in prompt_text
        assert any("realtimeInput" in m for m in provider.sent)
        resp = next(m["toolResponse"]["functionResponses"][0] for m in provider.sent if "toolResponse" in m)
        assert resp["name"] == "triage_terminal"
        assert resp["response"]["ok"] is True

    asyncio.run(run())


def test_bridge_gpt_layer4_terminal_event_and_triage_delegation():
    async def run():
        provider = FakeProviderWS(
            [
                {"type": "session.started"},
                {"type": "session.input_transcript.delta", "delta": "let me see it"},
                {"type": "session.delegation.created", "delegation": {"id": "del-l4", "target": "client"}},
            ]
        )

        @asynccontextmanager
        async def fake_connect(_url, **_kw):
            yield provider

        peer = FakeGlassPeer([])
        usage = live.Usage()

        async def recheck():
            return None

        task = asyncio.create_task(
            gv.bridge_gpt(
                peer,
                "gpt-live-1",
                "test-openai-key",
                usage,
                recheck,
                300,
                identity="glass-1",
                tools=["local", "remotea"],
                screen={"screen": "home"},
                connector=fake_connect,
            )
        )

        for _ in range(100):
            if any(m.get("type") == "ready" for m in peer.sent_json):
                break
            await asyncio.sleep(0.01)

        await peer.incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "terminal_event",
                        "event_id": "dec:2",
                        "terminal_id": "davis:surf-2",
                        "label": "Schema Design",
                        "kind": "needs_you",
                        "summary": "Waiting for DB choice.",
                        "question": "Use SQLite or Postgres?",
                        "remaining": 0,
                    }
                ),
            }
        )

        tool_msg = None
        for _ in range(100):
            tool_msg = next((m for m in peer.sent_json if m.get("type") == "tool"), None)
            if tool_msg:
                break
            await asyncio.sleep(0.01)
        assert tool_msg is not None
        assert tool_msg["name"] == "open_terminal"
        assert tool_msg["args"] == {"query": "it"}

        await peer.incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "tool_result",
                        "id": tool_msg["id"],
                        "ok": True,
                        "result": "Opened Schema Design.",
                        "screen": {"screen": "watch", "terminal_id": "davis:surf-2", "terminal_label": "Schema Design"},
                    }
                ),
            }
        )
        for _ in range(100):
            commentaries = [m for m in provider.sent if m.get("type") == "session.commentary.append"]
            if len(commentaries) >= 2:
                break
            await asyncio.sleep(0.01)

        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        commentaries = [m for m in provider.sent if m.get("type") == "session.commentary.append"]
        unsolicited = [m for m in commentaries if "delegation_id" in m and m["delegation_id"] is None]
        delegated = [m for m in commentaries if m.get("delegation_id") == "del-l4"]
        assert len(unsolicited) == 1
        unsolicited_all = "".join(
            m["content"]
            for m in provider.sent
            if m.get("type") in {"session.thinking.append", "session.commentary.append"} and m.get("delegation_id") is None
        )
        assert "Schema Design" in unsolicited_all
        assert "Use SQLite or Postgres?" in unsolicited_all
        assert len(delegated) == 1
        delegated_all = "".join(
            m["content"]
            for m in provider.sent
            if m.get("type") in {"session.thinking.append", "session.commentary.append"}
            and m.get("delegation_id") == "del-l4"
        )
        assert "Opened Schema Design." in delegated_all

    asyncio.run(run())
