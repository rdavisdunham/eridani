"""Opt-in, dedicated Glass project. Export work and failures stay off the audio loop."""
import array
import asyncio
import io
import logging
import re
import sys
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit
import time
import wave
from functools import lru_cache
from uuid import uuid4

import httpx

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from typing import Literal

log = logging.getLogger("uvicorn.error")
ORIGINS = {"us": "https://us.cloud.langfuse.com", "eu": "https://cloud.langfuse.com"}


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: Literal["us", "eu"]
    public: str = Field(pattern=r"^pk-lf-[A-Za-z0-9_-]{8,128}$")
    secret: SecretStr

    @field_validator("secret")
    @classmethod
    def valid_secret(cls, value):
        if not re.fullmatch(r"sk-lf-[A-Za-z0-9_-]{8,128}", value.get_secret_value()):
            raise ValueError("Expected a Langfuse project secret")
        return value


pending = set()


def background(fn, *args):
    if len(pending) >= 12:
        log.warning("Glass trace queue full; diagnostic segment dropped")
        return
    async def export():
        try:
            await asyncio.to_thread(fn, *args)
        except Exception as error:
            log.warning("Glass trace export failed (%s)", type(error).__name__)
    task = asyncio.create_task(export())
    pending.add(task)
    task.add_done_callback(pending.discard)


@lru_cache(maxsize=1)
def pcm_table():
    samples = []
    for code in range(256):
        value = (~code) & 255
        magnitude = (((value & 15) * 8 + 132) << ((value >> 4) & 7)) - 132
        samples.append(-magnitude if value & 128 else magnitude)
    return samples


def wav_audio(data):
    table = pcm_table()
    pcm = array.array("h", (table[b] for b in data))
    if sys.byteorder != "little":
        pcm.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


SECRET = re.compile(r"(?:eri_bot_|sk-(?:lf-|proj-|ant-)?|pk-lf-|gh[pousr]_|github_pat_|lin_api_)[A-Za-z0-9_-]{12,}|Bearer [A-Za-z0-9._~+/=-]{12,}", re.I)


def scrub(value):
    if isinstance(value, str):
        return SECRET.sub("[redacted]", value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()
                if k.casefold() not in {"ticket", "proof", "secret", "authorization", "token", "api_key", "focus", "binding"}}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def attachment(api, identity, observation, field, data):
    """Register media with Langfuse, then PUT to its signed URL without project credentials."""
    checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
    response = api.post("/api/public/media", json={
        "traceId": identity, "observationId": observation, "field": field, "contentType": "audio/wav",
        "contentLength": len(data), "sha256Hash": checksum})
    response.raise_for_status()
    media = response.json()
    if url := media.get("uploadUrl"):
        if not url.startswith("https://"):
            raise ValueError("Expected HTTPS media storage")
        started = time.monotonic()
        headers = {"Content-Type": "audio/wav"}
        if "storage.googleapis.com" not in urlsplit(url).hostname:
            headers.update({"x-amz-checksum-sha256": checksum, "x-ms-blob-type": "BlockBlob"})
        result = httpx.put(url, content=data, headers=headers, timeout=14, follow_redirects=False)
        result.raise_for_status()
        ack = api.patch("/api/public/media/" + media["mediaId"], json={
            "uploadedAt": datetime.now(timezone.utc).isoformat(), "uploadHttpStatus": result.status_code,
            "uploadTimeMs": round((time.monotonic() - started)*1000)})
        ack.raise_for_status()
    return f"@@@langfuseMedia:type=audio/wav|id={media['mediaId']}|source=bytes@@@"


def upload(project, identity, name, inputs, outputs, tracks):
    """Return only after the dedicated project's OTLP endpoint acknowledges the span."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest, ExportTraceServiceResponse
    from .config import get_settings

    if project.public == get_settings().langfuse_public_key:
        raise ValueError("Use a dedicated Google Glass project")
    inputs, outputs = scrub(inputs), scrub(outputs)
    packet = ExportTraceServiceRequest()
    resource = packet.resource_spans.add()
    resource.resource.attributes.add(key="service.name").value.string_value = "glassface"
    scope = resource.scope_spans.add()
    scope.scope.name = "glassface"
    stamp = time.time_ns()
    span = scope.spans.add(trace_id=bytes.fromhex(identity), span_id=os.urandom(8),
                           name=name, kind=1, start_time_unix_nano=stamp, end_time_unix_nano=stamp+1)
    with httpx.Client(base_url=ORIGINS[project.region], auth=(project.public, project.secret.get_secret_value()),
                      timeout=12, follow_redirects=False) as api:
        for lane, data in tracks.items():
            field = "input" if lane in ("microphone", "dictation") else "output"
            target = inputs if field == "input" else outputs
            target[lane] = attachment(api, identity, span.span_id.hex(), field,
                                      data if lane == "dictation" else wav_audio(data))
        for key, value in {"langfuse.trace.name": name, "session.id": identity,
                           "langfuse.observation.type": "span",
                           "langfuse.observation.input": json.dumps(inputs, ensure_ascii=False),
                           "langfuse.observation.output": json.dumps(outputs, ensure_ascii=False)}.items():
            span.attributes.add(key=key).value.string_value = value
        span.attributes.add(key="langfuse.trace.tags").value.array_value.values.add().string_value = "googleglass"
        response = api.post("/api/public/otel/v1/traces", content=packet.SerializeToString(),
                            headers={"Content-Type": "application/x-protobuf", "x-langfuse-ingestion-version": "4"})
        response.raise_for_status()
        if ExportTraceServiceResponse.FromString(response.content).partial_success.rejected_spans:
            raise ValueError("Langfuse rejected the observation")


class Session:
    def __init__(self, project, identity=None):
        self.project = project
        self.id = identity or uuid4().hex
        self.start = self.boundary = time.monotonic()
        self.sequence = 0
        self.events = []
        self.tracks = {}
        self.size = 0
        self.offsets = {}

    def event(self, kind, **data):
        self.events.append({"ms": round((time.monotonic()-self.start)*1000), "event": kind, **data})
        self.size += sum(len(str(v)) for v in data.values())
        self.maybe_flush()

    def audio(self, lane, data):
        if not data:
            return
        self.tracks.setdefault(lane, bytearray()).extend(data)
        self.maybe_flush()

    def maybe_flush(self):
        if (time.monotonic()-self.boundary >= 15 or len(self.events) >= 250 or self.size >= 45000
                or any(len(track) >= 240000 for track in self.tracks.values())):
            self.flush()

    def flush(self):
        if not self.events and not self.tracks:
            return
        inputs = {"segment": self.sequence, "from_ms": round((self.boundary-self.start)*1000),
                  "sample_offsets": self.offsets.copy()}
        outputs = {"timeline": self.events}
        background(upload, self.project, self.id, "Glass · Dani Live", inputs, outputs, self.tracks)
        for lane, data in self.tracks.items():
            self.offsets[lane] = self.offsets.get(lane, 0) + len(data)
        self.sequence += 1
        self.events, self.tracks, self.size = [], {}, 0
        self.boundary = time.monotonic()
