"""Today's pinned boxes, one person at a time.

A pin belongs to one account in one workspace, so pinning or unpinning never changes another member's Today.
It lasts until that person removes it. A pin is not task data: removing one never changes what its box shows.
"""

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert

from .domain import DomainError, emit, owned
from .models import Task, TodayPin, now

# The kind stored for a quick list's box. The today_pins migration writes the same value for converted lists.
QUICK_LIST = "quick_list"


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


def change_pin(db, owner, args):
    """today.pin: puts a box on, or takes it off, the Today of the person acting. The target itself never changes,
    so its revision stays the same, and nothing goes to Activity: unpinning is the undo."""
    from .access import actor

    row = owned(db, Task, args.target_id, owner)
    if not row.is_quick_list:
        raise DomainError("NOT_QUICK_LIST", "Only quick lists can be pinned to Today.", 409)
    (pin if args.pinned else unpin)(db, owner, actor(db, owner), QUICK_LIST, row.id)
    # Open screens, on this device or another, reload their boxes.
    emit(db, owner, "today.changed", row.id)
    return {"kind": QUICK_LIST, "target_id": row.id, "pinned": args.pinned}


def pin_receipt(data):
    """True for the data of a today.pin receipt, which Activity leaves out."""
    return isinstance(data, dict) and data.keys() == {"kind", "target_id", "pinned"}


def boxes(db, owner, account, day=None):
    """This person's boxes for `day`, their local date (the workspace's today when it is missing), in Today's order.

    Pinned lists come first, in the order they were pinned. Unpinned lists whose due date or do date has arrived
    follow, by that date and then title. A finished, archived or promoted list has no box but keeps its pin, so a
    reopen brings the box back in its place."""
    from .agent_link import owner_today
    from .quick_lists import FINISHED, read

    day = day or owner_today(db, owner)
    pinned = pinned_lists(db, owner, account)
    showing = (Task.owner_id == owner, Task.is_quick_list.is_(True), Task.archived.is_(False),
               Task.status.not_in(FINISHED))
    rows = {row.id: row for row in db.scalars(select(Task).where(*showing, Task.id.in_(pinned)))}

    def box(row, reason, since=None):
        mine = reason == "pinned"
        return {"kind": QUICK_LIST, "target_id": row.id, "reason": reason, "pinned": mine,
                "date": since.isoformat() if since else None,
                "list": read(db, owner, row.id, account, pinned=mine)}

    def arrived(row):
        return min(d for d in (row.due_date, row.planned_date) if d and d <= day)

    dated = db.scalars(select(Task).where(*showing, Task.id.not_in(pinned),
                                          or_(Task.due_date <= day, Task.planned_date <= day)))
    return [*(box(rows[identity], "pinned") for identity in pinned if identity in rows),
            *(box(row, "dated", arrived(row)) for row in sorted(dated, key=lambda r: (arrived(r), r.title, r.id)))]
