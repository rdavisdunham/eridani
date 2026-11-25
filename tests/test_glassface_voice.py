"""Tests for the minimal Layer-1 direct Glass voice WebSocket (/api/glassface/voice)."""

import asyncio
import base64
import json
from contextlib import asynccontextmanager

from jarvis import glassface_live as live
from jarvis import glassface_voice as gv


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

        # Wait for ready
        for _ in range(50):
            if any(m.get("type") == "ready" for m in peer.sent_json):
                break
            await asyncio.sleep(0.01)
        assert any(m.get("type") == "ready" for m in peer.sent_json)

        # Stream two turns of audio + an explicit tap-to-interrupt + stop
        await peer.incoming.put({"type": "websocket.receive", "bytes": b"\x20" * 320})
        await asyncio.sleep(0.12)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "interrupt"})})
        await asyncio.sleep(0.05)
        await peer.incoming.put({"type": "websocket.receive", "bytes": b"\x20" * 320})
        await asyncio.sleep(0.05)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        # Verify ZERO clientContent messages were ever sent mid-call (only setup + realtimeInput)
        assert provider.sent[0].get("setup", {}).get("tools") is None
        assert all("clientContent" not in msg for msg in provider.sent)
        assert sum(1 for msg in provider.sent if "realtimeInput" in msg) == 2
        # Captions from both turns and clear from interrupt reached Glass
        captions = [(m["role"], m["text"]) for m in peer.sent_json if m.get("type") == "caption"]
        assert ("user", "Hey Dani.") in captions
        assert ("assistant", "Hey Davin!") in captions
        assert ("user", "Tell me a story.") in captions
        assert any(m.get("type") == "clear" for m in peer.sent_json)
        assert len(peer.sent_bytes) > 0

    asyncio.run(run())


def test_bridge_gpt_multi_turn_and_interrupt():
    async def run():
        pcmu_audio = base64.b64encode(b"\x10" * 320).decode("ascii")
        provider = FakeProviderWS(
            [
                {"type": "session.started"},
                {"type": "session.input_transcript.delta", "delta": "Hello Marin."},
                {"type": "session.output_transcript.delta", "delta": "Hi Davin!"},
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
                connector=fake_connect,
            )
        )

        for _ in range(50):
            if any(m.get("type") == "ready" for m in peer.sent_json):
                break
            await asyncio.sleep(0.01)
        assert any(m.get("type") == "ready" for m in peer.sent_json)

        await peer.incoming.put({"type": "websocket.receive", "bytes": b"\x20" * 320})
        await asyncio.sleep(0.14)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "interrupt"})})
        await asyncio.sleep(0.05)
        await peer.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "stop"})})
        await task

        # Clean session.start uses OpenAI v1/live/sessions event names (NO delegation field)
        assert provider.sent[0]["type"] == "session.start"
        assert "delegation" not in provider.sent[0]["session"]
        assert any(m.get("type") == "session.input_audio.append" for m in provider.sent)
        assert not any(m.get("type") == "response.cancel" for m in provider.sent)
        captions = [(m["role"], m["text"]) for m in peer.sent_json if m.get("type") == "caption"]
        assert ("user", "Hello Marin.") in captions
        assert ("assistant", "Hi Davin!") in captions
        assert any(m.get("type") == "clear" for m in peer.sent_json)
        assert len(peer.sent_bytes) > 0

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

        async def fake_bridge(ws, model, *_args, **_kw):
            bridged.append((ws, model))

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
        assert ws.sent_json == []

    asyncio.run(run())
