"""Tests for Layer-5 in-process Eridani tools and agent-run controls on `/api/glassface/voice`."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from jarvis import agent_actor, agent_control, agent_decisions, agent_link, agent_plan, bot_access, domain
from jarvis import glassface_eridani_tools as et
from jarvis import memory_service, needs_you, notes, run_brainstorm, run_coordinator, task_tools, today, workspace


def _fake_db_scope(monkeypatch, db_obj):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        yield db_obj

    monkeypatch.setattr(et, "session_scope", scope)
    monkeypatch.setattr(
        bot_access,
        "google_glass",
        lambda _db, ident: SimpleNamespace(id=ident, owner_id="owner-1", account_id="owner-1"),
    )


def test_eridani_today_aggregates_tasks_boxes_calendar_and_needs_you(monkeypatch):
    today_date = date.today()
    t_overdue = SimpleNamespace(
        id="t-over",
        title="Pay electric bill",
        status="open",
        priority=2,
        due_date=today_date.fromordinal(today_date.toordinal() - 1),
        planned_date=None,
    )
    t_due = SimpleNamespace(
        id="t-due",
        title="Ship Layer 5 voice",
        status="open",
        priority=3,
        due_date=today_date,
        planned_date=None,
    )

    class FakeDB:
        def get(self, model, key):
            if model is et.UserSetting:
                return SimpleNamespace(timezone="America/Chicago")
            return None

        def scalars(self, _q):
            return [t_overdue, t_due]

    _fake_db_scope(monkeypatch, FakeDB())
    monkeypatch.setattr(today, "boxes", lambda *_a, **_kw: {"boxes": [{"title": "Glassface", "open_count": 3}]})
    monkeypatch.setattr(
        workspace,
        "calendar",
        lambda *_a, **_kw: {"events": [{"kind": "event", "title": "Standup", "at": "10:00"}]},
    )
    monkeypatch.setattr(
        needs_you,
        "spoken",
        lambda *_a, **_kw: {"items": [{"title": "Fix Wi-Fi roam", "decision": "Approve plan"}]},
    )

    sess = et.EridaniToolSession("bot-1")
    out = asyncio.run(sess.invoke("eridani_today", {}))
    assert out["ok"] is True
    assert "Pay electric bill" in out["result"]
    assert "Ship Layer 5 voice" in out["result"]
    assert "Glassface (3 open)" in out["result"]
    assert "Standup @ 10:00" in out["result"]
    assert "Fix Wi-Fi roam" in out["result"]


def test_eridani_tasks_create_complete_and_refuses_completing_run_owned_task(monkeypatch):
    executed = []
    task_row = SimpleNamespace(id="task-1", title="Test Layer 5", status="open", revision=4)

    class FakeDB:
        def scalars(self, _q):
            return [task_row]

    _fake_db_scope(monkeypatch, FakeDB())
    monkeypatch.setattr(
        domain,
        "execute",
        lambda _db, owner, _cid, tool, payload: (
            executed.append((owner, tool, payload, agent_actor.current().reason, agent_actor.current().credential_id))
            or {"task": {"id": "task-new", "title": payload.get("title", "Test Layer 5")}}
        ),
    )

    sess = et.EridaniToolSession("bot-glass-1")

    # Create records glass_voice actor provenance
    created = asyncio.run(sess.invoke("eridani_tasks", {"action": "create", "title": "Test Layer 5", "priority": 2}))
    assert created["ok"] is True
    assert "Created task 'Test Layer 5'" in created["result"]
    assert executed[-1][1] == "task.create"
    assert executed[-1][3] == "glass_voice"
    assert executed[-1][4] == "bot-glass-1"

    # Completing a task with an active Eridani run is refused cleanly
    monkeypatch.setattr(agent_actor, "active_run", lambda _db, _tid: SimpleNamespace(id="run-1", state="executing"))
    blocked = asyncio.run(sess.invoke("eridani_tasks", {"action": "complete", "query": "Test Layer 5"}))
    assert blocked["ok"] is False
    assert "active Eridani run" in blocked["result"]
    assert "eridani_control_run" in blocked["result"]

    # Completing an unowned task auto-supplies expected_revision=4
    monkeypatch.setattr(agent_actor, "active_run", lambda _db, _tid: None)
    done = asyncio.run(sess.invoke("eridani_tasks", {"action": "complete", "query": "Test Layer 5"}))
    assert done["ok"] is True
    assert executed[-1][1] == "task.complete"
    assert executed[-1][2] == {"task_id": "task-1", "expected_revision": 4}


def test_eridani_memory_async_search_save_and_confirmed_forget(monkeypatch):
    executed = []
    mem_row = SimpleNamespace(id="mem-1", content="Davin prefers dark roast coffee.")

    class FakeDB:
        def get(self, _model, key):
            return mem_row if key == "mem-1" else None

        def scalar(self, _q):
            return mem_row

    _fake_db_scope(monkeypatch, FakeDB())

    async def fake_semantic(owner, query, limit=10):
        assert owner == "owner-1"
        assert query == "coffee"
        return [{"id": "mem-1", "content": "Davin prefers dark roast coffee."}]

    monkeypatch.setattr(memory_service, "semantic_search", fake_semantic)
    monkeypatch.setattr(memory_service, "search", lambda _db, _o, _q, limit=4: [{"id": "mem-1", "content": mem_row.content}])
    monkeypatch.setattr(domain, "execute", lambda _db, _o, _cid, tool, payload: executed.append((tool, payload)) or {})

    sess = et.EridaniToolSession("bot-1")

    res_search = asyncio.run(sess.invoke("eridani_memory", {"action": "search", "query": "coffee"}))
    assert res_search["ok"] is True
    assert "dark roast coffee" in res_search["result"]

    res_save = asyncio.run(sess.invoke("eridani_memory", {"action": "save", "content": "Likes espresso."}))
    assert res_save["ok"] is True
    assert executed[-1] == ("memory.capture", {"content": "Likes espresso."})

    # Confirmed forget without prior preview is rejected by server
    rej = asyncio.run(sess.invoke("eridani_memory", {"action": "forget", "memory_id": "mem-1", "confirmed": True}))
    assert rej["ok"] is False
    assert "Preview and ask Davin" in rej["result"]

    # Two-phase forget succeeds
    prev = asyncio.run(sess.invoke("eridani_memory", {"action": "forget", "query": "coffee", "confirmed": False}))
    assert prev["ok"] is True
    assert "CONFIRMATION REQUIRED" in prev["result"]
    done = asyncio.run(sess.invoke("eridani_memory", {"action": "forget", "memory_id": "mem-1", "confirmed": True}))
    assert done["ok"] is True
    assert executed[-1] == ("memory.forget", {"memory_id": "mem-1"})


def test_eridani_start_run_enforces_server_two_phase_confirmation(monkeypatch):
    started_calls = []
    task_row = SimpleNamespace(id="task-wifi", title="Fix Wi-Fi roam", status="open", revision=2)
    target_row = SimpleNamespace(id="tgt-1", host_id="host-1", host_target="glassface", name="glassface", repo="/home/davin/glassface")
    host_row = SimpleNamespace(id="host-1", name="DavisPC")

    class FakeDB:
        def scalars(self, q):
            text = str(q)
            if "FROM tasks" in text or "tasks" in text:
                return [task_row]
            if "execution_targets" in text:
                return [target_row]
            if "agent_hosts" in text:
                return [host_row]
            return []

        def get(self, model, key):
            if model is et.AgentHost and key == "host-1":
                return host_row
            return None

    _fake_db_scope(monkeypatch, FakeDB())
    monkeypatch.setattr(agent_link, "gate", lambda _db, _o: None)
    monkeypatch.setattr(agent_link, "connected", lambda _h: True)
    monkeypatch.setattr(agent_control, "advertised", lambda _db, _o: [])
    monkeypatch.setattr(agent_control, "resolve_target", lambda _db, _o, _t: target_row)
    monkeypatch.setattr(
        agent_control,
        "start_run",
        lambda _db, _o, _a, body, *, actor: (
            started_calls.append((body.task_id, body.harness, body.execution_target_id, actor.reason))
            or {"id": "run-abc12345", "branch": "feat/fix-wifi", "state": "queued"}
        ),
    )

    sess = et.EridaniToolSession("bot-glass-1")

    # Jumping straight to confirmed=True is refused by Python server state
    blocked = asyncio.run(sess.invoke("eridani_start_run", {"task": "Fix Wi-Fi roam", "confirmed": True}))
    assert blocked["ok"] is False
    assert "Preview and ask Davin" in blocked["result"]
    assert started_calls == []

    # Step 1: preview with confirmed=False
    prev = asyncio.run(sess.invoke("eridani_start_run", {"task": "Fix Wi-Fi roam", "harness": "claude", "confirmed": False}))
    assert prev["ok"] is True
    assert "CONFIRMATION REQUIRED" in prev["result"]
    assert "glassface" in prev["result"]
    assert "DavisPC" in prev["result"]
    assert started_calls == []

    # Step 2: confirm with confirmed=True
    go = asyncio.run(sess.invoke("eridani_start_run", {"task": "Fix Wi-Fi roam", "harness": "claude", "confirmed": True}))
    assert go["ok"] is True
    assert "Started Eridani run run-abc1" in go["result"]
    assert started_calls == [("task-wifi", "claude", "tgt-1", "glass_voice")]


def test_eridani_control_run_pause_resume_and_confirmed_stop_approve(monkeypatch):
    calls = []
    run_row = SimpleNamespace(
        id="run-999",
        task_id="task-wifi",
        state="executing",
        state_revision=7,
        branch="feat/wifi",
        paused=False,
    )
    task_row = SimpleNamespace(id="task-wifi", title="Fix Wi-Fi roam")

    class FakeDB:
        def scalars(self, _q):
            return [run_row]

        def scalar(self, _q):
            return run_row

        def get(self, model, key):
            if model is et.Task and key == "task-wifi":
                return task_row
            return None

    _fake_db_scope(monkeypatch, FakeDB())
    monkeypatch.setattr(
        agent_decisions,
        "set_paused",
        lambda _db, _o, rid, body, paused, *, actor: calls.append(("pause", rid, paused, body.expected_revision, actor.reason)) or {},
    )
    monkeypatch.setattr(
        agent_control,
        "stop_run",
        lambda _db, _o, rid, body, *, actor: calls.append(("stop", rid, body.mode, actor.reason)) or {},
    )
    monkeypatch.setattr(
        agent_control,
        "approve",
        lambda _db, _o, rid, body, *, actor: calls.append(("approve", rid, body.expected_revision, actor.reason)) or {},
    )

    sess = et.EridaniToolSession("bot-glass-1")

    # Pause/resume execute directly without confirmation bounce
    p_res = asyncio.run(sess.invoke("eridani_control_run", {"action": "pause"}))
    assert p_res["ok"] is True
    assert calls[-1] == ("pause", "run-999", True, 7, "glass_voice")

    r_res = asyncio.run(sess.invoke("eridani_control_run", {"action": "resume"}))
    assert r_res["ok"] is True
    assert calls[-1] == ("pause", "run-999", False, 7, "glass_voice")

    # Stop requires confirmation
    stop_blocked = asyncio.run(sess.invoke("eridani_control_run", {"action": "stop", "confirmed": True}))
    assert stop_blocked["ok"] is False
    stop_prev = asyncio.run(sess.invoke("eridani_control_run", {"action": "stop", "confirmed": False}))
    assert stop_prev["ok"] is True and "CONFIRMATION REQUIRED" in stop_prev["result"]
    stop_go = asyncio.run(sess.invoke("eridani_control_run", {"action": "stop", "target": "run-999", "confirmed": True}))
    assert stop_go["ok"] is True
    assert calls[-1] == ("stop", "run-999", "interrupt", "glass_voice")

    # Approve requires confirmation
    ap_prev = asyncio.run(sess.invoke("eridani_control_run", {"action": "approve", "confirmed": False}))
    assert ap_prev["ok"] is True and "CONFIRMATION REQUIRED" in ap_prev["result"]
    ap_go = asyncio.run(sess.invoke("eridani_control_run", {"action": "approve", "target": "run-999", "confirmed": True}))
    assert ap_go["ok"] is True
    assert calls[-1] == ("approve", "run-999", 7, "glass_voice")
