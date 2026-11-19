"""Today's pinned boxes: each person's pins, the boxes read and lists pinned when they are created."""
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select, text

from jarvis.config import get_settings
from jarvis.db import session_scope
from jarvis.domain import DomainError
from jarvis.models import ActionChange, Command, Event, Task
from jarvis import quick_lists, today
from test_structure import run

PERSONAL = "pin-owner"
SHARED = "shared-workspace"
OWNER = "davin"
DAY = date(2030, 1, 16)


def pinned(owner, account):
    with session_scope() as db:
        return [(p.kind, p.target_id) for p in today.pins(db, owner, account)]


def create(title, *items, **args):
    return run("quicklist.create", {"title": title, "items": [{"title": t} for t in items], **args})


def boxes(day=DAY):
    with session_scope() as db:
        return [(box["reason"], box["list"]["title"]) for box in today.boxes(db, OWNER, OWNER, day)]


def check(row, item, completed=True):
    return run("quicklist.item", {"list_id": row["id"], "expected_revision": row["revision"], "operation": "edit",
                                  "item_id": item["id"], "expected_item_revision": item["revision"],
                                  "completed": completed})


def read(identity):
    with session_scope() as db:
        return quick_lists.read(db, OWNER, identity, OWNER)


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


def test_a_list_created_without_a_date_is_pinned_for_its_creator_from_day_to_day():
    groceries = create("Groceries", "Milk")
    assert groceries["pinned"] is True and groceries["due_date"] is None and groceries["planned_date"] is None
    assert pinned(OWNER, OWNER) == [(today.QUICK_LIST, groceries["id"])]
    # A pin lasts until it is removed, and never makes the list due.
    assert boxes(DAY) == boxes(DAY + timedelta(days=1)) == [("pinned", "Groceries")]
    with session_scope() as db:
        box = today.boxes(db, OWNER, OWNER, DAY)[0]
    assert {k: v for k, v in box.items() if k != "list"} == {
        "kind": "quick_list", "target_id": groceries["id"], "reason": "pinned", "pinned": True, "date": None,
        "title": "Groceries"}
    assert box["list"]["pinned"] is True and [i["title"] for i in box["list"]["items"]] == ["Milk"]


def test_a_dated_list_is_not_pinned_and_has_a_box_from_its_date_on():
    thursday = DAY + timedelta(days=1)
    party = create("Party", "Balloons", planned_date=thursday.isoformat())
    assert party["pinned"] is False and pinned(OWNER, OWNER) == []
    assert boxes(DAY) == []
    assert boxes(thursday) == boxes(thursday + timedelta(days=3)) == [("dated", "Party")]
    with session_scope() as db:
        box = today.boxes(db, OWNER, OWNER, thursday + timedelta(days=3))[0]
    assert (box["pinned"], box["date"]) == (False, thursday.isoformat())


def test_pinned_false_creates_a_list_with_no_pin_and_no_box():
    someday = create("Someday", "Learn piano", pinned=False)
    assert someday["pinned"] is False and pinned(OWNER, OWNER) == [] and boxes() == []


def test_pinned_boxes_come_in_pin_order_then_dated_boxes_by_date():
    create("Packing", "Socks")
    create("Errands", "Bank")
    create("Taxes", "Forms", due_date=(DAY - timedelta(days=1)).isoformat())
    # The earlier date that has arrived places a dated box; a date still to come does not.
    create("Gifts", "Card", planned_date=(DAY - timedelta(days=3)).isoformat(),
           due_date=(DAY + timedelta(days=5)).isoformat())
    create("Later", "Plan", due_date=(DAY + timedelta(days=1)).isoformat())
    # Pinned and dated: one box, in pin order.
    create("Trip", "Tickets", planned_date=DAY.isoformat(), pinned=True)
    assert boxes() == [("pinned", "Packing"), ("pinned", "Errands"), ("pinned", "Trip"),
                       ("dated", "Gifts"), ("dated", "Taxes")]


def test_unpinning_removes_the_box_and_changes_no_task():
    groceries = create("Groceries", "Milk", "Eggs")
    before = read(groceries["id"])
    assert run("today.pin", {"target_id": groceries["id"], "pinned": True}) == {
        "kind": "quick_list", "target_id": groceries["id"], "pinned": True, "on_today": True, "reason": "pinned"}
    receipt = run("today.pin", {"target_id": groceries["id"], "pinned": False})
    assert receipt == {"kind": "quick_list", "target_id": groceries["id"], "pinned": False, "on_today": False,
                       "reason": None}
    assert boxes() == [] and pinned(OWNER, OWNER) == []
    after = read(groceries["id"])
    assert after["pinned"] is False and after == {**before, "pinned": False}
    run("today.pin", {"target_id": groceries["id"], "pinned": True})
    assert boxes() == [("pinned", "Groceries")] and read(groceries["id"]) == before


def test_unpinning_a_list_whose_date_has_come_says_it_stays_on_today():
    from jarvis.agent_link import owner_today
    with session_scope() as db:
        day = owner_today(db, OWNER)
    party = create("Party", "Balloons", planned_date=day.isoformat(), pinned=True)
    receipt = run("today.pin", {"target_id": party["id"], "pinned": False})
    assert receipt == {"kind": "quick_list", "target_id": party["id"], "pinned": False, "on_today": True,
                       "reason": "dated"}
    assert boxes(day) == [("dated", "Party")]


def test_a_finished_list_hides_its_box_and_a_reopen_brings_it_back_in_place():
    groceries = create("Groceries", "Milk")
    errands = create("Errands", "Bank")
    finished = check(groceries, groceries["items"][0])
    assert finished["list_finished"] is True
    assert boxes() == [("pinned", "Errands")]
    assert pinned(OWNER, OWNER) == [(today.QUICK_LIST, groceries["id"]), (today.QUICK_LIST, errands["id"])]
    reopened = check(finished, finished["items"][0], completed=False)
    assert reopened["list_reopened"] is True
    assert boxes() == [("pinned", "Groceries"), ("pinned", "Errands")]


@pytest.mark.parametrize("change", ["archived", "promoted", "cancelled"])
def test_archived_promoted_and_cancelled_lists_have_no_box(change):
    groceries = create("Groceries", "Milk")
    party = create("Party", "Balloons", due_date=DAY.isoformat())
    for row in (groceries, party):
        if change == "promoted":
            run("quicklist.promote", {"list_id": row["id"], "expected_revision": row["revision"]})
        else:
            patch = {"archived": True} if change == "archived" else {"status": "cancelled"}
            run("task.update", {"task_id": row["id"], "expected_revision": row["revision"], **patch})
    assert boxes() == []
    assert pinned(OWNER, OWNER) == [(today.QUICK_LIST, groceries["id"])]


def test_pinning_another_workspaces_list_or_anything_but_a_list_or_project_is_refused():
    from test_structure import create as record
    private = run("quicklist.create", {"title": "Private"}, owner="other")
    plain = run("task.create", {"title": "Plain task"})
    client = record("client", "Harbor")
    for target, code in ((private["id"], "NOT_FOUND"), (plain["id"], "NOT_PINNABLE"), (client["id"], "NOT_PINNABLE"),
                         ("missing", "NOT_FOUND")):
        with pytest.raises(DomainError) as refused:
            run("today.pin", {"target_id": target, "pinned": True})
        assert refused.value.code == code
    assert pinned(OWNER, OWNER) == []


def test_quick_list_reads_mark_this_persons_pins_and_find_finished_pinned_lists():
    groceries = create("Groceries", "Milk")
    create("Someday", "Learn piano", pinned=False)
    finished = check(groceries, groceries["items"][0])
    with session_scope() as db:
        # The automatic archive files a finished list after a day.
        db.execute(text("UPDATE tasks SET archived=true, archive_reason='automatic', archived_at=now() WHERE id=:id"),
                   {"id": groceries["id"]})
    with session_scope() as db:
        state = lambda **kw: [(r["title"], r["status"], r["archived"], r["pinned"])  # noqa: E731
                              for r in quick_lists.listing(db, OWNER, account=OWNER, **kw)["items"]]
        assert state() == [("Someday", "open", False, False)]
        assert state(pinned=True) == [("Groceries", "completed", True, True)]
        assert state(pinned=False) == [("Someday", "open", False, False)]
        assert quick_lists.read(db, OWNER, groceries["id"], "another-person")["pinned"] is False
    # Adding to the finished pinned list reopens it, and its box comes back.
    added = run("quicklist.item", {"list_id": groceries["id"], "expected_revision": finished["revision"],
                                   "operation": "add", "title": "Eggs"})
    assert added["list_reopened"] is True and added["pinned"] is True
    assert boxes() == [("pinned", "Groceries")]


def test_today_pin_emits_today_changed_replays_and_stays_out_of_activity(monkeypatch):
    monkeypatch.setattr(get_settings(), "integration_encryption_key", Fernet.generate_key().decode())
    groceries = create("Groceries", "Milk", pinned=False)
    with session_scope() as db:
        changes = db.scalar(select(func.count()).select_from(ActionChange))
    # Dani's commands carry its request's ID, which is how Activity finds what a request saved.
    work = SimpleNamespace(id=str(uuid4()), owner_id=OWNER, account_id=OWNER, result={})
    args = {"target_id": groceries["id"], "pinned": True}
    first = run("today.pin", args, key=work.id + ":0")
    assert run("today.pin", args, key=work.id + ":0") == first
    from jarvis.action_history import changes_for_work
    with session_scope() as db:
        assert [e.entity_id for e in db.scalars(select(Event).where(Event.kind == "today.changed"))] == [groceries["id"]]
        assert db.get(Command, (OWNER, work.id + ":0")).result["data"] == first
        assert db.scalar(select(func.count()).select_from(ActionChange)) == changes
        assert changes_for_work(db, work) == []


# Project boxes: a pinned project shows its open tasks for today. A project is pinned by its home record.

def home(title="Eridani", **args):
    from test_structure import create as record
    return record("project", title, **args)


def task(title, parent, **args):
    return run("task.create", {"title": title, "parent_task_id": parent["task_id"], **args})


def project_box(identity, day=DAY, account=OWNER):
    with session_scope() as db:
        return next((box for box in today.boxes(db, OWNER, account, day) if box["target_id"] == identity), None)


def shown(identity, day=DAY):
    box = project_box(identity, day)
    return None if box is None else [t["title"] for t in box["tasks"]]


def pin_project(record, pinned=True):
    return run("today.pin", {"target_id": record["id"], "pinned": pinned})


def test_a_project_box_lists_the_open_tasks_in_its_home_due_or_planned_by_today():
    eridani, remotea = home("Eridani"), home("Remotea")
    task("Overdue fix", eridani, due_date=(DAY - timedelta(days=3)).isoformat())
    task("Slipped plan", eridani, planned_date=(DAY - timedelta(days=1)).isoformat())
    step = task("Due today", eridani, due_date=DAY.isoformat())
    run("task.create", {"title": "Nested step", "parent_task_id": step["id"], "planned_date": DAY.isoformat()})
    task("Tomorrow", eridani, planned_date=(DAY + timedelta(days=1)).isoformat())
    task("Someday", eridani)
    done = task("Already done", eridani, due_date=DAY.isoformat())
    run("task.complete", {"task_id": done["id"], "expected_revision": done["revision"]})
    shelved = task("Shelved", eridani, due_date=DAY.isoformat())
    run("task.update", {"task_id": shelved["id"], "expected_revision": shelved["revision"], "archived": True})
    task("Other project", remotea, due_date=DAY.isoformat())
    # A quick list's items have boxes of their own, so a dated item never shows in a project's box.
    packing = create("Packing", "Charger", pinned=False)
    run("task.update", {"task_id": packing["items"][0]["id"], "expected_revision": packing["items"][0]["revision"],
                        "due_date": DAY.isoformat()})
    run("task.update", {"task_id": packing["id"], "expected_revision": read(packing["id"])["revision"],
                        "parent_task_id": eridani["task_id"]})
    receipt = pin_project(eridani)
    assert receipt == {"kind": "project", "target_id": eridani["id"], "pinned": True, "on_today": True,
                       "reason": "pinned"}
    box = project_box(eridani["id"])
    assert {k: box[k] for k in ("kind", "target_id", "reason", "pinned", "date", "title", "total")} == {
        "kind": "project", "target_id": eridani["id"], "reason": "pinned", "pinned": True, "date": None,
        "title": "Eridani", "total": 4}
    # Due and overdue's own order: by date, then time, priority and title.
    assert shown(eridani["id"]) == ["Overdue fix", "Slipped plan", "Due today", "Nested step"]
    assert project_box(remotea["id"]) is None


def test_a_task_in_a_project_box_is_still_due_and_finishing_it_once_clears_both():
    eridani = home()
    pin_project(eridani)
    due = task("Ship the release", eridani, due_date=DAY.isoformat())
    assert shown(eridani["id"]) == ["Ship the release"]
    # Due and overdue keeps listing every open task due by today; the box is a second view of the same task.
    with session_scope() as db:
        row = db.get(Task, due["id"])
        assert row.status == "open" and row.due_date <= DAY
    finished = run("task.complete", {"task_id": due["id"], "expected_revision": due["revision"]})
    assert shown(eridani["id"]) == []
    with session_scope() as db:
        assert db.get(Task, due["id"]).status == "completed"
    run("task.reopen", {"task_id": due["id"], "expected_revision": finished["revision"]})
    assert shown(eridani["id"]) == ["Ship the release"]


def test_adding_in_a_project_box_files_the_task_under_the_project_for_today_and_stays_local():
    from jarvis.hierarchy import for_task
    from jarvis.models import Job, LinearIssue

    eridani = home()
    pin_project(eridani)
    box = project_box(eridani["id"])
    assert box["add"] == {"parent_task_id": eridani["task_id"]}
    added = run("task.create", {"title": "Fix the voice toggle", **box["add"], "planned_date": DAY.isoformat()})
    assert shown(eridani["id"]) == ["Fix the voice toggle"]
    with session_scope() as db:
        assert for_task(db, OWNER, added["id"]).parent_id == eridani["id"]
        assert db.get(Task, added["id"]).planned_date == DAY
        # Filing into a project never creates a Linear issue; only Linear's own create or publish does.
        assert db.scalar(select(func.count()).select_from(LinearIssue)) == 0
        assert not db.scalar(select(func.count()).select_from(Job).where(Job.kind.like("linear%")))


def test_a_linear_issue_filed_under_the_project_shows_in_its_box():
    from jarvis.hierarchy import for_task
    from jarvis.linear_structure import move
    from jarvis.structure import ensure

    eridani = home()
    pin_project(eridani)
    # Linear issues keep the legacy "· Linear" project; the Linear mapping files their records under the home.
    issue = run("task.create", {"title": "Voice toggle sticks", "project": "Eridani · Linear",
                                "due_date": DAY.isoformat()})
    assert shown(eridani["id"]) == []
    with session_scope() as db:
        assert move(db, OWNER, ensure(db, OWNER), for_task(db, OWNER, issue["id"]), eridani["id"])
    assert shown(eridani["id"]) == ["Voice toggle sticks"]


def test_a_pinned_project_with_nothing_due_keeps_an_empty_box():
    eridani = home()
    task("Someday", eridani)
    pin_project(eridani)
    box = project_box(eridani["id"])
    assert (box["tasks"], box["total"], box["add"]) == ([], 0, {"parent_task_id": eridani["task_id"]})


@pytest.mark.parametrize("change", ["archived", "completed"])
def test_an_archived_or_finished_project_hides_its_box_until_it_is_back(change):
    from test_structure import definition

    eridani = home()
    pin_project(eridani)
    changes = {"archived": True} if change == "archived" else {
        "status_id": next(s["id"] for s in next(t for t in definition()["types"] if t["id"] == "project")["statuses"]
                          if s["meaning"] == "completed")}
    hidden = run("record.update", {"record_id": eridani["id"], "expected_revision": eridani["revision"],
                                   "schema_revision": definition()["revision"], **changes})
    assert project_box(eridani["id"]) is None
    assert pinned(OWNER, OWNER) == [(today.PROJECT, eridani["id"])]
    back = {"archived": False} if change == "archived" else {"status_id": eridani["status_id"]}
    run("record.update", {"record_id": eridani["id"], "expected_revision": hidden["revision"],
                          "schema_revision": definition()["revision"], **back})
    assert project_box(eridani["id"])["title"] == "Eridani"


def test_a_project_pins_by_its_record_or_its_task_and_only_for_the_person_pinning():
    eridani = home()
    # Dani may hold the task behind the project rather than its record; the pin is the record's either way.
    assert run("today.pin", {"target_id": eridani["task_id"], "pinned": True})["target_id"] == eridani["id"]
    assert pinned(OWNER, OWNER) == [(today.PROJECT, eridani["id"])]
    assert project_box(eridani["id"], account="someone-else") is None
    assert pin_project(eridani, pinned=False) == {"kind": "project", "target_id": eridani["id"], "pinned": False,
                                                  "on_today": False, "reason": None}
    assert pinned(OWNER, OWNER) == [] and project_box(eridani["id"]) is None


def test_project_and_list_boxes_share_one_pin_order():
    groceries = create("Groceries", "Milk")
    eridani = home()
    pin_project(eridani)
    errands = create("Errands", "Bank")
    with session_scope() as db:
        assert [(b["kind"], b["title"]) for b in today.boxes(db, OWNER, OWNER, DAY)] == [
            ("quick_list", "Groceries"), ("project", "Eridani"), ("quick_list", "Errands")]
    assert [b["target_id"] for b in [project_box(x["id"]) for x in (groceries, eridani, errands)]] == [
        groceries["id"], eridani["id"], errands["id"]]
