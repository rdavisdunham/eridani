"""Hosted Dani for one dedicated Glass operator, using only its supplied terminal snapshot."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from time import monotonic
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from websockets.exceptions import WebSocketException

from . import bot_access, budget, glassface_live, work_crypto
from .config import get_settings, require_external_services
from .db import engine, session_scope
from .domain import DomainError
from .external_routes import Bot
from .live_voice import LIVE_PRICE_PER_SECOND

router = APIRouter()
SCOPE = "glassface:dani"
active = set()
MAX_REQUEST_BYTES = 96_000


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Terminal(Input):
    label: str = Field(max_length=160)
    task: str = Field(max_length=2400)
    reply: str = Field(max_length=4800)
    question: str = Field(max_length=1800)


class Exchange(Input):
    user: str = Field(max_length=1800)
    assistant: str = Field(max_length=1800)


class Turn(Input):
    kind: Literal["brief", "finished", "conversation"]
    question: str = Field(max_length=1800)
    terminal: Terminal
    history: Annotated[list[Exchange], Field(max_length=4)] = Field(default_factory=list)


async def read_body(request, schema=Turn):
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
        raise DomainError("INVALID_ARGUMENT", "Use application/json.", 415)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REQUEST_BYTES:
            raise DomainError("INVALID_ARGUMENT", "Glass turn exceeds its size limit.", 413)
        raw.extend(chunk)
    try:
        return schema.model_validate_json(raw)
    except ValidationError:
        # Pydantic's detailed error contains the submitted excerpt.
        raise DomainError("INVALID_ARGUMENT", "Invalid Glass turn.", 422) from None


def busy():
    return DomainError("RATE_LIMITED", "Dani is handling a Glass turn. Try again shortly.", 429)


def granted(db, identity):
    bot = bot_access.authorize(db, required=SCOPE, credential_id=identity)
    if set(bot.scopes) != {SCOPE}:
        raise DomainError("INSUFFICIENT_SCOPE", "Use a dedicated Glass Dani key.", 403)
    return bot.owner_id


@contextmanager
def slot(identity, model, usage, allowance_seconds=60):
    # A DB session-level lock spans the provider call across API replicas. Short
    # DB transactions on this same connection leave no transaction open on the network.
    with engine().connect() as conn:
        lock = {"name": f"glassface-turn:{identity}"}
        with conn.begin():
            acquired = conn.scalar(text("select pg_try_advisory_lock(hashtextextended(:name, 0))"), lock)
        if not acquired:
            raise busy()
        try:
            turn_id = str(uuid4())
            with Session(conn) as db, db.begin():
                owner = granted(db, identity)
                budget.reserve(db, owner, turn_id, allowance_seconds * LIVE_PRICE_PER_SECOND, model)

            touched = monotonic()

            def recheck():
                nonlocal touched
                with Session(conn) as db, db.begin():
                    granted(db, identity)
                    if monotonic() - touched >= 45:
                        # Keep a long-running voice reservation visible to the stale-hold sweep.
                        budget.ensure_room(db, owner, turn_id, 0)
                        touched = monotonic()

            try:
                yield recheck
            finally:
                with Session(conn) as db, db.begin():
                    if usage.seconds:
                        budget.record_usage(
                            db,
                            owner,
                            turn_id,
                            turn_id + ":glass",
                            model,
                            {"seconds": usage.seconds},
                            usage.seconds * LIVE_PRICE_PER_SECOND,
                            feature="voice",
                        )
                    budget.close(db, owner, turn_id, uncertain=usage.attempted and not usage.closed)
        finally:
            try:
                with conn.begin():
                    conn.execute(text("select pg_advisory_unlock(hashtextextended(:name, 0))"), lock)
            except BaseException:
                conn.invalidate()  # A locked connection must not reenter the pool.
                raise


@asynccontextmanager
async def leased_slot(identity, model, usage, allowance_seconds=60):
    # Serialize every use of the leased SQLAlchemy connection on one worker.
    # Cancellation can arrive during admission or a grant check. Enqueuing
    # release on the same worker makes it run after that operation finishes.
    loop = asyncio.get_running_loop()
    manager = slot(identity, model, usage, allowance_seconds)
    with ThreadPoolExecutor(max_workers=1) as worker:
        admitted = worker.submit(manager.__enter__)

        def release():
            if admitted.exception() is None:
                manager.__exit__(None, None, None)

        try:
            recheck = await asyncio.shield(asyncio.wrap_future(admitted))

            async def verify():
                await loop.run_in_executor(worker, recheck)

            yield verify
        finally:
            await asyncio.shield(loop.run_in_executor(worker, release))


def authorized_settings(identity):
    with session_scope() as db:
        granted(db, identity)
    require_external_services()
    settings = get_settings()
    if not settings.openai_api_key:
        raise DomainError("INTEGRATION_UNAVAILABLE", "Hosted GPT-Live is unavailable.", 503)
    return settings


@router.get("/api/glassface/dani/status")
def status(identity: Bot):
    settings = authorized_settings(identity)
    try:
        work_crypto.cipher()
        native = True
    except DomainError:
        native = False
    return JSONResponse(
        {
            "ready": True,
            "model": settings.live_model,
            "live": native,
            **({"screenContext": True, "screenControls": True, "navigationTree": True} if native else {}),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/glassface/dani/turn", response_model=dict[str, str])
async def glass_turn(request: Request, identity: Bot):
    settings = await run_in_threadpool(authorized_settings, identity)
    # Authentication runs before parsing; the cap also covers chunked bodies.
    body = await read_body(request)
    if identity in active or len(active) >= 4:
        raise busy()
    active.add(identity)
    usage = glassface_live.Usage()
    try:
        async with leased_slot(identity, settings.live_model, usage) as recheck:
            last_auth = 0

            async def check():
                nonlocal last_auth
                if await request.is_disconnected():
                    raise DomainError("CANCELLED", "Glass disconnected.", 408)
                now = asyncio.get_running_loop().time()
                if now - last_auth >= 4:
                    await recheck()
                    last_auth = now

            answer = await glassface_live.respond(
                settings.live_model, settings.openai_api_key, body.model_dump(), usage, check
            )
            await recheck()
            return JSONResponse({"text": answer}, headers={"Cache-Control": "no-store"})
    except (TimeoutError, OSError, WebSocketException, ValueError, glassface_live.LiveFailure):
        raise DomainError("INTEGRATION_UNAVAILABLE", "Dani could not finish this Glass turn.", 503) from None
    finally:
        active.discard(identity)
