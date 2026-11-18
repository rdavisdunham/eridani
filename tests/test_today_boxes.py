"""Today's pinned boxes: each person's pins."""
from jarvis import today
from jarvis.db import session_scope

PERSONAL = "pin-owner"
SHARED = "shared-workspace"


def pinned(owner, account):
    with session_scope() as db:
        return [(p.kind, p.target_id) for p in today.pins(db, owner, account)]


def test_pinning_twice_keeps_one_pin_and_its_first_time():
    with session_scope() as db:
        first = today.pin(db, PERSONAL, PERSONAL, today.QUICK_LIST, "groceries").pinned_at
    with session_scope() as db:
        again = today.pin(db, PERSONAL, PERSONAL, today.QUICK_LIST, "groceries").pinned_at
    with session_scope() as db:
        assert [(p.target_id, p.pinned_at) for p in today.pins(db, PERSONAL, PERSONAL)] == [("groceries", first)]
    assert again == first


def test_pins_list_in_pinned_order_and_unpin_removes_only_that_box():
    for target in ("packing", "errands", "groceries"):
        with session_scope() as db:
            today.pin(db, PERSONAL, PERSONAL, today.QUICK_LIST, target)
    assert pinned(PERSONAL, PERSONAL) == [(today.QUICK_LIST, t) for t in ("packing", "errands", "groceries")]
    with session_scope() as db:
        assert today.unpin(db, PERSONAL, PERSONAL, today.QUICK_LIST, "errands")
    assert pinned(PERSONAL, PERSONAL) == [(today.QUICK_LIST, "packing"), (today.QUICK_LIST, "groceries")]


def test_pins_in_a_shared_workspace_belong_to_each_person():
    with session_scope() as db:
        today.pin(db, SHARED, "account-a", today.QUICK_LIST, "team-list")
    assert pinned(SHARED, "account-b") == []
    with session_scope() as db:
        # Another member's unpin never reaches this person's Today.
        assert not today.unpin(db, SHARED, "account-b", today.QUICK_LIST, "team-list")
        today.pin(db, SHARED, "account-b", today.QUICK_LIST, "own-list")
    assert pinned(SHARED, "account-a") == [(today.QUICK_LIST, "team-list")]
    assert pinned(SHARED, "account-b") == [(today.QUICK_LIST, "own-list")]
