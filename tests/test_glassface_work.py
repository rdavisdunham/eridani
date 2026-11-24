import json
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from jarvis import glassface_work as work
from jarvis.config import get_settings
from jarvis.db import session_scope
from jarvis.domain import DomainError
from jarvis.models import Job, Outbox, now
from sqlalchemy import func, select
from test_glassface_dani import key


@pytest.fixture
def glass(client, monkeypatch):
    monkeypatch.setenv("JARVIS_INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    ident, _ = key(client, ["glassface:dani"])
    yield ident
    get_settings.cache_clear()


def test_worker_claims_comparison_once_and_reports_after_reconnect(glass, client, monkeypatch):
    from jarvis import memory_learning
    from jarvis.worker import _perform_job

    question = "Compare the Mobile and API terminals. Which one needs my input first?"
    snapshot = {
        "visibleLive": 2,
        "sessions": [
            {"name": "Mobile", "status": "needs_you", "question": "Ship the fold layout?"},
            {"name": "API", "status": "finished", "lastAgent": "Migration tests passed."},
        ],
    }
    calls = []

    def model(owner, path, body, model_name, allowance, **options):
        calls.append(json.loads(body["input"]))
        assert owner == "davin" and path == "responses" and options["agent"].model == model_name
        assert not body["store"] and "tools" not in body and not options["trace_content"]
        return {
            "choices": [{"message": {"content": "Mobile needs your fold layout decision. API has finished."}}]
        }

    monkeypatch.setattr(memory_learning, "provider_request", model)
    key_id = work.submit(glass, "utterance-1", question, snapshot)
    assert work.submit(glass, "utterance-1", question, snapshot) == key_id
    with pytest.raises(DomainError):
        work.submit(glass, "utterance-1", "Another instruction", snapshot)
    assert work.waiting(glass) == [(key_id, "queued", "")]
    other, _ = key(client, ["glassface:dani"])
    assert work.waiting(other) == []
    with session_scope() as db:
        assert db.get(Outbox, key_id) and "fold layout" not in str(db.get(Job, key_id).payload)
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.job_id == key_id)) == 1
    _perform_job(key_id)
    _perform_job(key_id)
    assert calls == [{"question": question, "snapshot": snapshot}]
    assert work.waiting(glass) == [
        (key_id, "succeeded", "Mobile needs your fold layout decision. API has finished.")
    ]
    work.reported(other, key_id)
    assert work.waiting(glass)
    work.reported(glass, key_id)
    assert work.waiting(glass) == []
    with session_scope() as db:
        row = db.get(Job, key_id)
        assert "input" not in row.payload and "fold layout" not in str(row.result)
        row.created_at = now() - timedelta(hours=25)
        db.flush()
        work.expire(db)
        assert db.get(Job, key_id) is None and db.get(Outbox, key_id) is None


def test_revoked_or_abandoned_work_never_repeats_the_model_call(glass, client, monkeypatch):
    calls = []
    monkeypatch.setattr(work, "analyze", lambda *args: calls.append(args))
    abandoned = work.submit(glass, "utterance-A", "Which tasks are blocked?", {"sessions": []})
    with session_scope() as db:
        row = db.get(Job, abandoned)
        row.status = "running"
        row.created_at = now() - timedelta(minutes=4)
    assert work.waiting(glass) == [(abandoned, "failed", work.UNCONFIRMED)]
    revoked = work.submit(glass, "utterance-B", "Compare my two terminals.", {"sessions": []})
    client.post(f"/api/v1/bot-keys/{glass}/revoke")
    work.perform(revoked)
    work.perform(abandoned)
    assert not calls
    with session_scope() as db:
        assert db.get(Job, revoked).status == "failed"


def test_live_conversation_can_continue_while_its_verified_terminal_task_runs(client, monkeypatch):
    import asyncio
    import threading
    import time
    from contextlib import asynccontextmanager

    from jarvis import glassface_media_stream as stream
    from jarvis import memory_learning
    from jarvis.worker import _perform_job
    from test_glassface_media import BODY, ROOT, timed

    monkeypatch.setenv("JARVIS_INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JARVIS_OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("JARVIS_EXTERNAL_SERVICES_ENABLED", "true")
    get_settings.cache_clear()
    phrase = "Compare my Mobile and API sessions and tell me which one needs a decision."
    snapshot = {
        "visibleLive": 2,
        "sessions": [
            {"name": "Mobile", "question": "Ship the fold layout?"},
            {"name": "API", "status": "finished"},
        ],
    }
    question = threading.Event()
    accepted = threading.Event()
    start = threading.Event()
    finish = threading.Event()
    spoken = []

    def model(owner, route, body, *args, **kwargs):
        if "text" in body:
            assert json.loads(body["input"])["wearer"] == phrase
            assert "brief" in body["text"]["format"]["schema"]["properties"]["name"]["enum"]
            return {"choices": [{"message": {"content": '{"name":"brief","query":""}'}}]}
        start.set()
        assert finish.wait(5)
        assert json.loads(body["input"]) == {"question": phrase, "snapshot": snapshot}
        return {
            "choices": [{"message": {"content": "Mobile needs your fold layout decision. API is finished."}}]
        }

    class Provider:
        def __init__(self):
            self.events = asyncio.Queue()
            self.frames = 0

        async def recv(self):
            return json.dumps(await self.events.get())

        async def send(self, raw):
            item = json.loads(raw)
            if item["type"] == "session.start":
                self.events.put_nowait({"type": "session.started"})
            elif item["type"] == "session.input_audio.append":
                self.frames += 1
                if self.frames == 1:
                    self.events.put_nowait(timed(phrase, 30, 100, "first"))
                    self.events.put_nowait(
                        {
                            "type": "session.delegation.created",
                            "delegation": {"target": "client", "id": "d-work"},
                        }
                    )
                else:
                    self.events.put_nowait(timed("I'm still listening.", 1400, 1600, "listen", "output"))
            elif item["type"] == "session.commentary.append":
                self.events.put_nowait(
                    {"type": "session.commentary.appended", "client_event_id": item["event_id"]}
                )
                spoken.append(item)
                if "worker received the terminal snapshot" in item["content"]:
                    accepted.set()
                if "fold layout decision" in item["content"]:
                    question.set()
            elif item["type"] == "session.close":
                self.events.put_nowait({"type": "session.closed", "usage": {"seconds": 10}})

    @asynccontextmanager
    async def upstream(*args, **kwargs):
        yield Provider()

    monkeypatch.setattr(memory_learning, "provider_request", model)
    monkeypatch.setattr(stream, "connect", upstream)
    ident, auth = key(client, ["glassface:dani"])
    view = {
        "screen": "home",
        "page": "home",
        "actions": ["open"],
        "destinations": [{"id": "home", "label": "Home", "parent": ""}],
    }
    ticket = client.post(ROOT + "/tickets", json={**BODY, "view": view}, headers=auth).json()["ticket"]
    with client.websocket_connect(ROOT) as native:
        native.send_json({"type": "start", "ticket": ticket})
        assert native.receive_json()["type"] == "ready"
        native.send_bytes(bytes(800))
        assert native.receive_json()["text"] == phrase
        claim = native.receive_json()
        assert claim["type"] == "utterance"
        verified = client.post(ROOT + "/verify", json={"proof": claim["proof"]}, headers=auth).json()
        assert verified["tool"] == {"name": "list", "detail": "brief"}
        receipt = {
            "type": "receipt",
            "operation": claim["operation"],
            "text": "Workspace snapshot v1\n" + json.dumps(snapshot),
        }
        native.send_json(receipt)
        native.send_json(receipt)
        for _ in range(60):
            if jobs := work.waiting(ident):
                break
            time.sleep(0.04)
        assert len(jobs) == 1
        thread = threading.Thread(target=_perform_job, args=(jobs[0][0],), daemon=True)
        thread.start()
        try:
            assert start.wait(3)
            assert accepted.wait(2)
            native.send_bytes(bytes(800))
            assert native.receive_json()["text"] == "I'm still listening."
        finally:
            finish.set()
        thread.join(3)
        assert question.wait(6)
        assert len([e for e in spoken if "fold layout decision" in e["content"]]) == 1
        assert spoken[-1]["delegation_id"] == "d-work"
        for _ in range(40):
            if not work.waiting(ident):
                break
            time.sleep(0.05)
        native.send_json({"type": "stop"})
        assert native.receive_json()["reason"] == "ended"
    assert work.waiting(ident) == []
    get_settings.cache_clear()
