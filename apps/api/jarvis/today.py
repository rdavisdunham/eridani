"""Today's pinned boxes, one person at a time.

A pin belongs to one account in one workspace, so pinning or unpinning never changes another member's Today.
It lasts until that person removes it. A pin is not task data: removing one never changes what its box shows.

Every box has a kind and a target. A quick list's target is its task; a project's is its home record in the
organization, which every project has, whether it was made in Organize or imported.
"""

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased, object_session

from .domain import DomainError, emit
from .models import Project, Task, TodayPin, now
from .structure_models import StructureRecord

# The kind stored for a quick list's box. The today_pins migration writes the same value for converted lists.
QUICK_LIST = "quick_list"
PROJECT = "project"
# A project box lists at most this many of its tasks; its `total` counts them all.
PROJECT_TASKS = 50


def pin(db, owner, account, kind, target_id):
    """Pinning again keeps the first `pinned_at`, so the box keeps its place on Today."""
    db.execute(insert(TodayPin).values(owner_id=owner, account_id=account, kind=kind, target_id=target_id,
                                       pinned_at=now()).on_conflict_do_nothing())
    return db.get(TodayPin, (owner, account, kind, target_id))


def unpin(db, owner, account, kind, target_id):
    """Removes this person's pin only. True when there was one."""
    removed = db.execute(delete(TodayPin).where(
        TodayPin.owner_id == owner, TodayPin.account_id == account,
        TodayPin.kind == kind, TodayPin.target_id == target_id))
    return bool(removed.rowcount)


def pins(db, owner, account):
    """This person's pins, oldest first: the order of their boxes on Today."""
    return list(db.scalars(select(TodayPin).where(TodayPin.owner_id == owner, TodayPin.account_id == account)
                           .order_by(TodayPin.pinned_at, TodayPin.target_id)))


def pinned_lists(db, owner, account):
    """The quick lists this person pinned, in pin order."""
    return [p.target_id for p in pins(db, owner, account) if p.kind == QUICK_LIST]


def is_pinned(db, owner, account, kind, target_id):
    return db.scalar(select(TodayPin.target_id).where(
        TodayPin.owner_id == owner, TodayPin.account_id == account,
        TodayPin.kind == kind, TodayPin.target_id == target_id)) is not None


def reason(row, pinned, day):
    """Why a target has a box on `day`: "pinned", "dated" (a quick list whose due date or do date has come), or
    None for no box. A finished or archived target has none, pinned or not, and neither does a promoted list.
    `row` is a quick list's task or a project's home record."""
    from .quick_lists import FINISHED

    if isinstance(row, StructureRecord):
        work = object_session(row).get(Task, row.task_id) if row.task_id else None
        return "pinned" if pinned and not row.archived and not (work and work.status in FINISHED) else None
    if not row.is_quick_list or row.archived or row.status in FINISHED:
        return None
    if pinned:
        return "pinned"
    return "dated" if any(d and d <= day for d in (row.due_date, row.planned_date)) else None


def target(db, owner, identity):
    """What `identity` pins: (QUICK_LIST, its task) or (PROJECT, its home record). A project can be named by its
    record or by the task behind it, as Dani's task reads show it."""
    from .hierarchy import for_task

    task = db.scalar(select(Task).where(Task.id == identity, Task.owner_id == owner))
    if task and task.is_quick_list:
        return QUICK_LIST, task
    home = for_task(db, owner, task.id) if task else db.scalar(
        select(StructureRecord).where(StructureRecord.id == identity, StructureRecord.owner_id == owner))
    if home and home.type_id == PROJECT:
        return PROJECT, home
    if task or home:
        raise DomainError("NOT_PINNABLE", "Only quick lists and projects can be pinned to Today.", 409)
    raise DomainError("NOT_FOUND", "That record is no longer available.", 404)


def change_pin(db, owner, args):
    """today.pin: puts a box on, or takes it off, the Today of the person acting. The target itself never changes,
    so its revision stays the same, and nothing goes to Activity: unpinning is the undo.

    The receipt says whether the target still shows on Today and why, so an unpinned list whose date has come
    is not reported as gone."""
    from .access import actor
    from .agent_link import owner_today

    kind, row = target(db, owner, args.target_id)
    (pin if args.pinned else unpin)(db, owner, actor(db, owner), kind, row.id)
    # Open screens, on this device or another, reload their boxes.
    emit(db, owner, "today.changed", row.id)
    why = reason(row, args.pinned, owner_today(db, owner))
    return {"kind": kind, "target_id": row.id, "pinned": args.pinned, "on_today": why is not None, "reason": why}


def pin_receipt(data):
    """True for the data of a today.pin receipt, which Activity leaves out."""
    return isinstance(data, dict) and data.keys() == {"kind", "target_id", "pinned", "on_today", "reason"}


def project_box(db, owner, home, day):
    """A pinned project's box: its open tasks due or planned by `day`, the rule Due and overdue uses, so a task here
    is in Due too. Quick-list items are left out; their lists have boxes of their own. `add` holds the task.create
    arguments that file a new task in this project, the same way adding it anywhere else does."""
    from .quick_lists import FINISHED, sources
    from .domain import serial
    from .task_tools import under_home

    parent = aliased(Task)
    due = (Task.owner_id == owner, Task.archived.is_(False), Task.is_template.is_(False), Task.status.not_in(FINISHED),
           or_(Task.due_date <= day, Task.planned_date <= day), under_home(owner, home.id),
           ~select(parent.id).where(parent.id == Task.parent_task_id, parent.is_quick_list.is_(True)).exists())
    rows = list(db.scalars(select(Task).where(*due).order_by(
        func.coalesce(Task.due_date, Task.planned_date), Task.due_time.nulls_last(), Task.priority.desc(), Task.title,
        Task.id).limit(PROJECT_TASKS)))
    total = len(rows) if len(rows) < PROJECT_TASKS else db.scalar(select(func.count(Task.id)).where(*due))
    origin = sources(db, owner, rows)
    # Imported projects can lack the task that Organize gives each project; their tasks file by the older project ID.
    add = ({"parent_task_id": home.task_id} if home.task_id
           else {"project_id": home.id} if db.get(Project, home.id) else None)
    return {"kind": PROJECT, "target_id": home.id, "reason": "pinned", "pinned": True, "date": None,
            "title": home.title, "tasks": [serial(row, source=origin[row.id]) for row in rows], "total": total,
            "add": add}


def boxes(db, owner, account, day=None):
    """This person's boxes for `day`, their local date (the workspace's today when it is missing), in Today's order.

    Pinned lists and projects come first, in the order they were pinned. Unpinned lists whose due date or do date
    has arrived follow, by that date and then title. A finished or archived target, or a promoted list, has no box
    but keeps its pin, so a reopen or restore brings the box back in its place."""
    from .agent_link import owner_today
    from .quick_lists import FINISHED, read

    day = day or owner_today(db, owner)
    mine = pins(db, owner, account)
    listed = {p.target_id for p in mine if p.kind == QUICK_LIST}
    # Every candidate in one read per kind; reason() then decides each, the same rule today.pin reports.
    lists = {row.id: row for row in db.scalars(select(Task).where(
        Task.owner_id == owner, Task.is_quick_list.is_(True), Task.archived.is_(False), Task.status.not_in(FINISHED),
        or_(Task.id.in_(listed), Task.due_date <= day, Task.planned_date <= day)))}
    homes = {row.id: row for row in db.scalars(select(StructureRecord).where(
        StructureRecord.owner_id == owner, StructureRecord.id.in_([p.target_id for p in mine if p.kind == PROJECT])))}

    def list_box(row, why, since=None):
        own = why == "pinned"
        return {"kind": QUICK_LIST, "target_id": row.id, "reason": why, "pinned": own,
                "date": since.isoformat() if since else None, "title": row.title,
                "list": read(db, owner, row.id, account, pinned=own, row=row)}

    def pinned_box(p):
        if p.kind == QUICK_LIST and p.target_id in lists:
            return list_box(lists[p.target_id], "pinned")
        home = homes.get(p.target_id)
        return project_box(db, owner, home, day) if home and reason(home, True, day) else None

    def arrived(row):
        return min(d for d in (row.due_date, row.planned_date) if d and d <= day)

    dated = [row for row in lists.values() if reason(row, row.id in listed, day) == "dated"]
    return [*filter(None, map(pinned_box, mine)),
            *(list_box(row, "dated", arrived(row)) for row in sorted(dated, key=lambda r: (arrived(r), r.title, r.id)))]
