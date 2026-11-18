"""Today's pinned boxes, one person at a time.

A pin belongs to one account in one workspace, so pinning or unpinning never changes another member's Today.
It lasts until that person removes it. A pin is not task data: removing one never changes what its box shows.
"""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from .models import TodayPin, now

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
