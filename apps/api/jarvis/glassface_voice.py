"""Minimal direct conversational voice bridge for Google Glass (Layer 1: audio + captions only)."""

import asyncio
import base64
import json
import logging
from contextlib import AsyncExitStack, suppress
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedOK, WebSocketException

from . import bot_access
from . import glassface_live as live
from .auth import digest
from .db import session_scope
from .domain import DomainError
from .glassface_dani import active, authorized_settings, leased_slot
from .glassface_gemini_stream import (
    DOWNLINK_RATE,
    GEMINI_LIVE_URL,
    GEMINI_MODELS,
    THINKING_LEVELS,
    UPLINK_RATE,
    VOICE_NAME,
    DownlinkResampler,
    GeminiDownlink,
    UplinkResampler,
)
from .glassface_media_stream import MAX_FRAME, RATE
from .models import BotCredential, now

log = logging.getLogger("uvicorn.error")

router = APIRouter()
VOICE_SECONDS = 1800  # 30-minute session lease; Glass can reconnect seamlessly afterward.
HANDSHAKE_LIMIT = 32
handshakes: set[object] = set()
active_peers: dict[str, WebSocket] = {}

VOICE_INSTRUCTIONS = (
    "You are Dani, Davin's warm, helpful voice assistant on Google Glass. "
    "Keep spoken replies natural, conversational, and concise — usually 1 to 2 short sentences "
    "unless Davin asks for more detail. Wait for Davin to speak before replying."
)


class StartFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["start"]
    token: str = Field(min_length=16, max_length=150)
    model: Literal["gemini-3.8-live-extended-thinking", "gemini-3.8-live", "gpt-live-1"] = (
        "gemini-3.8-live-extended-thinking"
    )
    thinking: Literal["low", "medium", "high"] | None = None


def authenticate_glass_token(token: str) -> str:
    """Validate a direct Google Glass bot key (`eri_bot_...`) and return its credential ID."""
    if not isinstance(token, str) or not token.startswith("eri_bot_") or len(token) > 150:
        raise DomainError("NOT_AUTHORIZED", "A valid Google Glass voice key is required.", 401)
    with session_scope() as db:
        row = db.scalar(select(BotCredential).where(BotCredential.token_hash == digest(token)))
        if not row:
            raise DomainError("NOT_AUTHORIZED", "Invalid Google Glass voice key.", 401)
        bot = bot_access.google_glass(db, row.id)
        bot.last_used_at = now()
        return bot.id


def _gemini_setup_payload(model: str, thinking: Literal["low", "medium", "high"] | None) -> dict:
    gen_config: dict = {
        "responseModalities": ["AUDIO"],
        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE_NAME}}},
    }
    if "extended-thinking" in model:
        gen_config["thinkingConfig"] = {
            "thinkingLevel": THINKING_LEVELS.get(thinking or "low", "LOW"),
            "includeThoughts": False,
        }
    return {
        "setup": {
            "model": f"models/{model}",
            "generationConfig": gen_config,
            "systemInstruction": {"parts": [{"text": VOICE_INSTRUCTIONS}]},
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "disabled": False,
                    "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
                    "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH",
                    "prefixPaddingMs": 120,
                    "silenceDurationMs": 450,
                },
                "activityHandling": "START_OF_ACTIVITY_INTERRUPTS",
            },
            "contextWindowCompression": {"slidingWindow": {}},
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
    }


def _gpt_session_start(model: str) -> dict:
    return {
        "type": "session.start",
        "event_id": str(uuid4()),
        "session": {
            "model": model,
            "store": False,
            "instructions": VOICE_INSTRUCTIONS,
            "audio": {"format": {"type": "audio/pcmu", "rate": RATE}, "output": {"voice": "marin"}},
        },
    }


async def bridge_gemini(
    peer,
    model: str,
    api_key: str,
    usage: live.Usage,
    recheck,
    seconds: int,
    *,
    thinking: Literal["low", "medium", "high"] | None = None,
    connector=None,
) -> None:
    """Minimal audio + caption bridge between Glass and Gemini 3.8 Live."""
    if model not in GEMINI_MODELS:
        raise ValueError(f"Unsupported Gemini Live model: {model}")

    async with AsyncExitStack() as resources:
        ws_connect = connector or connect
        ws = await resources.enter_async_context(
            ws_connect(
                GEMINI_LIVE_URL,
                additional_headers={"x-goog-api-key": api_key},
                open_timeout=8,
                close_timeout=2,
                max_size=2_000_000,
                max_queue=256,
            )
        )

        ready = asyncio.Event()
        clock = asyncio.get_running_loop().time
        session_started_at: float | None = None
        provider_ended = False
        drained = False

        uplink_dsp = UplinkResampler()
        downlink_dsp = DownlinkResampler()
        downlink = GeminiDownlink()
        ws_write = asyncio.Lock()

        async def send_ws(payload: dict) -> None:
            async with ws_write:
                await ws.send(json.dumps(payload, ensure_ascii=False))

        async def send_peer_json(payload: dict) -> None:
            async with downlink.write:
                await peer.send_json(payload)

        async def from_glass() -> None:
            audio_cursor = 0.0
            while True:
                message = await peer.receive()
                if message["type"] == "websocket.disconnect":
                    return
                raw = message.get("bytes")
                if raw is None:
                    text = message.get("text", "")
                    if len(text) > 4096:
                        raise live.LiveFailure("Oversized Glass control message")
                    update = json.loads(text)
                    if not isinstance(update, dict):
                        raise live.LiveFailure("Invalid Glass control message")
                    kind = update.get("type")
                    if kind == "stop":
                        return
                    if kind == "interrupt":
                        await downlink.clear(peer)
                        continue
                    continue

                if not ready.is_set() or not 80 <= len(raw) <= MAX_FRAME:
                    raise live.LiveFailure("Unexpected Glass audio frame")
                if provider_ended:
                    continue
                now_t = clock()
                audio_cursor = max(now_t - 4.5, audio_cursor) + len(raw) / RATE
                if audio_cursor > now_t + 2.5:
                    raise live.LiveFailure("Glass audio exceeds realtime rate")

                pcm16k = uplink_dsp.transcode(raw)
                await send_ws(
                    {
                        "realtimeInput": {
                            "audio": {
                                "mimeType": f"audio/pcm;rate={UPLINK_RATE}",
                                "data": base64.b64encode(pcm16k).decode("ascii"),
                            }
                        }
                    }
                )

        async def from_provider() -> None:
            nonlocal session_started_at, provider_ended, drained
            while True:
                try:
                    raw_event = await ws.recv()
                except ConnectionClosedOK:
                    log.info("Glass voice upstream closed cleanly (%s)", model)
                    provider_ended = True
                    await downlink.frames.join()
                    drained = True
                    return
                event = json.loads(raw_event)
                if not isinstance(event, dict):
                    raise live.LiveFailure("Unexpected Gemini Live message")

                if "setupComplete" in event and not ready.is_set():
                    session_started_at = clock()
                    usage.started = True
                    usage.seconds = max(15.0, usage.seconds)
                    await recheck()
                    ready.set()
                    await send_peer_json({"type": "ready", "model": model})
                    continue

                if "usageMetadata" in event and session_started_at is not None:
                    usage.seconds = max(usage.seconds, 15.0, clock() - session_started_at)

                content = event.get("serverContent")
                if not isinstance(content, dict) or not ready.is_set():
                    continue

                if content.get("interrupted") is True:
                    if downlink.audible:
                        await downlink.clear(peer)
                    else:
                        downlink.discard()

                in_tr = content.get("inputTranscription") or content.get("input_transcription")
                if isinstance(in_tr, dict) and isinstance(in_tr.get("text"), str) and in_tr["text"]:
                    await send_peer_json({"type": "caption", "role": "user", "text": in_tr["text"][:4096]})

                out_tr = content.get("outputTranscription") or content.get("output_transcription")
                if isinstance(out_tr, dict) and isinstance(out_tr.get("text"), str) and out_tr["text"]:
                    await send_peer_json({"type": "caption", "role": "assistant", "text": out_tr["text"][:4096]})

                model_turn = content.get("modelTurn") or content.get("model_turn")
                if isinstance(model_turn, dict):
                    for part in model_turn.get("parts") or ():
                        if not isinstance(part, dict) or part.get("thought") is True:
                            continue
                        inline = part.get("inlineData") or part.get("inline_data")
                        if isinstance(inline, dict) and isinstance(inline.get("data"), str) and inline["data"]:
                            pcm24k = base64.b64decode(inline["data"], validate=True)
                            if len(pcm24k) > 8 * DOWNLINK_RATE * 2:
                                raise live.LiveFailure("Unbounded Gemini audio")
                            pcmu = downlink_dsp.transcode(pcm24k)
                            if pcmu:
                                downlink.add(pcmu)

        async def to_glass() -> None:
            await downlink.play(peer, lambda _frame: None)

        async def watchdog() -> None:
            await asyncio.wait_for(ready.wait(), 12)
            deadline = clock() + seconds
            last_auth = clock()
            while clock() < deadline:
                await asyncio.sleep(min(2.0, max(0.05, deadline - clock())))
                if session_started_at is not None:
                    usage.seconds = max(usage.seconds, 15.0, clock() - session_started_at)
                if clock() - last_auth >= 30:
                    await recheck()
                    last_auth = clock()
            raise live.LiveFailure("Voice session time limit reached")

        await send_ws(_gemini_setup_payload(model, thinking))

        tasks = [
            asyncio.create_task(from_glass()),
            asyncio.create_task(from_provider()),
            asyncio.create_task(to_glass()),
            asyncio.create_task(watchdog()),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
            if drained:
                await asyncio.wait_for(downlink.drain(), 4)
        finally:
            if session_started_at is not None:
                usage.seconds = max(usage.seconds, 15.0, clock() - session_started_at)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def bridge_gpt(
    peer,
    model: str,
    api_key: str,
    usage: live.Usage,
    recheck,
    seconds: int,
    *,
    connector=None,
) -> None:
    """Minimal audio + caption bridge between Glass and OpenAI GPT-Live (marin)."""
    async with AsyncExitStack() as resources:
        ws_connect = connector or connect
        ws = await resources.enter_async_context(
            ws_connect(
                live.LIVE_URL,
                additional_headers={"Authorization": "Bearer " + api_key},
                open_timeout=8,
                close_timeout=2,
                max_size=2_000_000,
                max_queue=64,
            )
        )

        ready = asyncio.Event()
        clock = asyncio.get_running_loop().time
        session_started_at: float | None = None
        provider_ended = False
        drained = False
        responding = False

        downlink = GeminiDownlink()
        ws_write = asyncio.Lock()

        async def send_ws(payload: dict) -> None:
            async with ws_write:
                await ws.send(json.dumps(payload, ensure_ascii=False))

        async def send_peer_json(payload: dict) -> None:
            async with downlink.write:
                await peer.send_json(payload)

        async def from_glass() -> None:
            nonlocal responding
            audio_cursor = 0.0
            while True:
                message = await peer.receive()
                if message["type"] == "websocket.disconnect":
                    return
                raw = message.get("bytes")
                if raw is None:
                    text = message.get("text", "")
                    if len(text) > 4096:
                        raise live.LiveFailure("Oversized Glass control message")
                    update = json.loads(text)
                    if not isinstance(update, dict):
                        raise live.LiveFailure("Invalid Glass control message")
                    kind = update.get("type")
                    if kind == "stop":
                        return
                    if kind == "interrupt":
                        await downlink.clear(peer)
                        if responding:
                            responding = False
                            with suppress(OSError, WebSocketException):
                                await send_ws({"type": "response.cancel", "event_id": str(uuid4())})
                        continue
                    continue

                if not ready.is_set() or not 80 <= len(raw) <= MAX_FRAME:
                    raise live.LiveFailure("Unexpected Glass audio frame")
                if provider_ended:
                    continue
                now_t = clock()
                audio_cursor = max(now_t - 4.5, audio_cursor) + len(raw) / RATE
                if audio_cursor > now_t + 2.5:
                    raise live.LiveFailure("Glass audio exceeds realtime rate")

                await send_ws(
                    {
                        "type": "input_audio_buffer.append",
                        "event_id": str(uuid4()),
                        "audio": base64.b64encode(raw).decode("ascii"),
                    }
                )

        async def from_provider() -> None:
            nonlocal session_started_at, provider_ended, drained, responding
            while True:
                try:
                    raw_event = await ws.recv()
                except ConnectionClosedOK:
                    log.info("Glass voice upstream closed cleanly (%s)", model)
                    provider_ended = True
                    await downlink.frames.join()
                    drained = True
                    return
                event = json.loads(raw_event)
                if not isinstance(event, dict):
                    raise live.LiveFailure("Unexpected GPT-Live message")
                kind = event.get("type")

                if kind == "session.started" and not ready.is_set():
                    session_started_at = clock()
                    usage.started = True
                    usage.seconds = max(15.0, usage.seconds)
                    await recheck()
                    ready.set()
                    await send_peer_json({"type": "ready", "model": model})
                    continue

                if kind == "error":
                    err = event.get("error") or {}
                    msg = err.get("message") if isinstance(err, dict) else None
                    raise live.LiveFailure(str(msg or "Voice provider error")[:200])

                if not ready.is_set():
                    continue

                if kind == "response.created":
                    responding = True
                elif kind in {"response.done", "response.cancelled"}:
                    responding = False
                elif kind == "input_audio_buffer.speech_started":
                    if downlink.audible:
                        await downlink.clear(peer)
                    else:
                        downlink.discard()
                elif kind == "response.output_audio.delta":
                    b64 = event.get("delta")
                    if isinstance(b64, str) and b64:
                        audio = base64.b64decode(b64, validate=True)
                        if audio:
                            downlink.add(audio)
                elif kind == "response.output_audio_transcript.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str) and delta:
                        await send_peer_json({"type": "caption", "role": "assistant", "text": delta[:4096]})
                elif kind in {
                    "conversation.item.input_audio_transcription.delta",
                    "conversation.item.input_audio_transcription.completed",
                }:
                    text = event.get("delta") if kind.endswith(".delta") else event.get("transcript")
                    if isinstance(text, str) and text:
                        await send_peer_json({"type": "caption", "role": "user", "text": text[:4096]})
                elif kind == "session.closed":
                    provider_ended = True
                    await downlink.frames.join()
                    drained = True
                    return

        async def to_glass() -> None:
            await downlink.play(peer, lambda _frame: None)

        async def watchdog() -> None:
            await asyncio.wait_for(ready.wait(), 12)
            deadline = clock() + seconds
            last_auth = clock()
            while clock() < deadline:
                await asyncio.sleep(min(2.0, max(0.05, deadline - clock())))
                if session_started_at is not None:
                    usage.seconds = max(usage.seconds, 15.0, clock() - session_started_at)
                if clock() - last_auth >= 30:
                    await recheck()
                    last_auth = clock()
            raise live.LiveFailure("Voice session time limit reached")

        await send_ws(_gpt_session_start(model))

        tasks = [
            asyncio.create_task(from_glass()),
            asyncio.create_task(from_provider()),
            asyncio.create_task(to_glass()),
            asyncio.create_task(watchdog()),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
            if drained:
                await asyncio.wait_for(downlink.drain(), 4)
        finally:
            if session_started_at is not None:
                usage.seconds = max(usage.seconds, 15.0, clock() - session_started_at)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


@router.websocket("/api/glassface/voice")
async def voice_socket(websocket: WebSocket) -> None:
    if len(handshakes) >= HANDSHAKE_LIMIT:
        await websocket.close(code=1013)
        return
    await websocket.accept()
    marker = object()
    handshakes.add(marker)
    identity: str | None = None
    try:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), 10)
            if len(raw) > 2048:
                raise ValueError("Start frame too large")
            start = StartFrame.model_validate_json(raw)
        except (TimeoutError, ValueError, ValidationError):
            with suppress(Exception):
                await websocket.send_json({"type": "error", "message": "Invalid voice start request."})
            await websocket.close(code=1008)
            return

        identity = await run_in_threadpool(authenticate_glass_token, start.token)
        provider: Literal["gemini", "openai"] = "gemini" if start.model.startswith("gemini-") else "openai"
        settings = await run_in_threadpool(authorized_settings, identity, provider)

        stale = active_peers.get(identity)
        if stale is not None:
            log.info("Glass voice preempting stale session for %s", identity)
            with suppress(Exception):
                await stale.close(code=1000)
            deadline = asyncio.get_running_loop().time() + 2.5
            while identity in active and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.05)

        if identity in active or len(active) >= 4:
            with suppress(Exception):
                await websocket.send_json({"type": "error", "message": "Dani already has an active Glass call."})
            await websocket.close(code=1008)
            return

        active.add(identity)
        active_peers[identity] = websocket
        handshakes.discard(marker)
        usage = live.Usage()
        try:
            async with leased_slot(identity, start.model, usage, VOICE_SECONDS) as recheck:
                if provider == "gemini":
                    await bridge_gemini(
                        websocket,
                        start.model,
                        settings.gemini_api_key,
                        usage,
                        recheck,
                        VOICE_SECONDS,
                        thinking=start.thinking,
                    )
                else:
                    await bridge_gpt(
                        websocket,
                        start.model,
                        settings.openai_api_key,
                        usage,
                        recheck,
                        VOICE_SECONDS,
                    )
        finally:
            if active_peers.get(identity) is websocket:
                active_peers.pop(identity, None)
            active.discard(identity)
    except DomainError as exc:
        with suppress(Exception):
            await websocket.send_json({"type": "error", "message": exc.message})
        with suppress(Exception):
            await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    except (TimeoutError, OSError, WebSocketException, ValueError, live.LiveFailure) as exc:
        log.warning("Glass voice session ended: %s", exc)
        with suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(exc)[:180] or "Voice connection interrupted."})
        with suppress(Exception):
            await websocket.close(code=1011)
    finally:
        handshakes.discard(marker)
