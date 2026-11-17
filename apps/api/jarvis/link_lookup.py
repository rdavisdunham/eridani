"""Read-only lookups for the assistant on a remotea host (docs/AGENT_CONTROL.md "Lookups over the link").

Dani on a remotea host can see the owner's runs, tasks and Needs you list. It asks over the link the host already
holds (`lookup.request`, answered by `lookup.response` with the same `req_id`), so the host needs no second key and
nothing new to keep secret. Like `context.request`, the pair is ephemeral: never acked, spooled or replayed, and a
reply that arrives after the host gave up is dropped there.

Everything here is read-only and limited to the link's owner. Starting, approving or stopping a run stays in Eridani
(the app, or Dani there), so what the host's assistant can do is what any reader of the run page can.
"""

from sqlalchemy import func, or_, select

from .domain import DomainError
from .models import Task

# What a run looks like in a list: enough to say what it is doing and why, small enough for a model's context.
RUN_FIELDS = ("id", "task", "state", "state_reason", "reason_text", "state_since", "tool", "model", "branch", "paused",
              "turn_count", "turn_cap", "execution_mode", "trouble", "ci")
DONE = ("completed", "cancelled")  # A task's finished statuses (domain.py task.update).
DETAIL_TURNS = 10


def lookup(db, bot, host_id, frame) -> dict:
    """The answer's `data` for one request; a DomainError becomes `ok: false` with its message."""
    from . import agent_control as control
    from . import run_coordinator as coordinator

    owner = bot.owner_id
    if frame.what == "runs":
        runs = control.list_runs(db, owner, active=frame.active, limit=frame.limit, dismissed=False)
        return {"runs": [{k: r[k] for k in RUN_FIELDS if k in r} for r in runs]}
    if frame.what == "run":
        if not frame.run_id:
            raise DomainError("INVALID_ARGUMENT", "Say which run (run_id).")
        run = coordinator.load(db, owner, frame.run_id, lock=False)
        return {"run": control.public_run(db, run, detail=True, limit=DETAIL_TURNS)}
    if frame.what == "tasks":
        return tasks(db, owner, frame.query, frame.status, frame.limit)
    from . import needs_you

    value = needs_you.spoken(db, owner, owner)
    # Read-only here: the host's assistant reports what waits; the decision is made in Eridani.
    return {**value, "next": READ_ONLY_NEXT if value["items"] else "Nothing is waiting for the owner."}


READ_ONLY_NEXT = ("Say how many things are waiting and name the urgent ones first, each as its decision and title, with "
                  "the recommendation when there is one. You cannot decide them from here: the owner does that on "
                  "Eridani's Needs you page, or by asking Dani there.")


def tasks(db, owner, text, status, limit) -> dict:
    query = select(Task).where(Task.owner_id == owner, Task.archived.is_(False), Task.is_template.is_(False))
    if status == "open":
        query = query.where(Task.status.not_in(DONE))
    elif status == "done":
        query = query.where(Task.status.in_(DONE))
    if text:
        term = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(or_(Task.title.ilike("%" + term + "%", escape="\\")))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Task.updated_at.desc(), Task.id).limit(limit))
    return {"total": total, "tasks": [{"id": t.id, "title": t.title, "status": t.status,
                                       "due_date": t.due_date.isoformat() if t.due_date else None,
                                       "updated_at": t.updated_at.isoformat() if t.updated_at else None} for t in rows]}
