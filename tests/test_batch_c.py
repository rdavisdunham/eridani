"""Batch C acceptance: capture identity, setup confirmation and explicit-rule authority."""
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, text
from cryptography.fernet import Fernet
from jarvis.db import session_scope
from jarvis.domain import DomainError, deliver_occurrence, execute, scan_schedules
from jarvis.config import get_settings
from jarvis.models import Task, Note, Schedule, ActionChange, OwnerSettings, Memory, Job, Notification, now
from jarvis.structure_models import FieldUnderstanding, RoutingPattern, StructureRecord
from jarvis import quick_lists, onboarding, structure, routing
from test_structure import run, create, definition, apply

@pytest.fixture(autouse=True)
def crypto(monkeypatch):
    monkeypatch.setattr(get_settings(),"integration_encryption_key",Fernet.generate_key().decode())

def capture(**args):
    return run("quicklist.create",{"title":"Get ready for Houston","items":[{"title":"Pack Hayes food","section":"Hayes"},{"title":"Pack clothes","section":"Personal"},{"title":"Gather moped tools","section":"Moped"},{"title":"Pack work laptop","section":"Work"}],**args})

def read(identity,owner="davin"):
    with session_scope() as db:return quick_lists.read(db,owner,identity)

def setup(owner="davin"):
    with session_scope() as db:return onboarding.state(db,owner)

def test_houston_capture_is_atomic_idempotent_searchable_and_no_alerts():
    args={"title":"Houston","items":[{"title":"Hayes food","section":"Hayes"}]}
    first=run("quicklist.create",args,key="capture-1")
    assert first==run("quicklist.create",args,key="capture-1")
    assert first["total"]==1 and first["items"][0]["quick_list_parent_id"]==first["id"]
    with session_scope() as db:
        assert len(list(db.scalars(select(Task))))==2
        assert not list(db.scalars(select(Schedule)))
        assert all(t.deadline_alert=="off" for t in db.scalars(select(Task)))
        assert quick_lists.listing(db,"davin","Hayes")["items"][0]["id"]==first["id"]
        assert not quick_lists.listing(db,"other")["items"]
        assert len(list(db.scalars(select(ActionChange))))>=2

def test_check_add_reorder_and_reopen_keep_item_ids():
    row=capture();item=row["items"][0]
    updated=run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":"edit","item_id":item["id"],"expected_item_revision":item["revision"],"completed":True})
    assert updated["done"]==1
    added=run("quicklist.item",{"list_id":row["id"],"expected_revision":updated["revision"],"operation":"add","title":"Phone charger","section":"Personal"})
    order=[t["id"] for t in added["items"]][::-1]
    moved=run("quicklist.item",{"list_id":row["id"],"expected_revision":added["revision"],"operation":"reorder","order":order})
    assert [t["id"] for t in read(row["id"])["items"]]==order
    item=next(t for t in moved["items"] if t["id"]==item["id"])
    reopened=run("quicklist.item",{"list_id":row["id"],"expected_revision":moved["revision"],"operation":"edit","item_id":item["id"],"expected_item_revision":item["revision"],"completed":False})
    assert reopened["done"]==0 and reopened["total"]==5

def test_stale_list_or_item_never_overwrites():
    row=capture();item=row["items"][0]
    run("task.update",{"task_id":item["id"],"expected_revision":item["revision"],"title":"Human changed this"})
    with pytest.raises(DomainError):run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":"edit","item_id":item["id"],"expected_item_revision":item["revision"],"completed":True})
    assert read(row["id"])["items"][0]["title"]=="Human changed this"
    added=run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":"add","title":"New"})
    with pytest.raises(DomainError):run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":"add","title":"Stale"})
    assert read(row["id"])["total"]==added["total"]

@pytest.mark.parametrize("order",[[],["foreign"],["duplicate","duplicate"]])
def test_invalid_reorder_is_atomic(order):
    row=capture()
    with pytest.raises(DomainError):run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":"reorder","order":order})
    assert read(row["id"])["revision"]==row["revision"]

def test_promote_preserves_ids_completion_and_history():
    row=capture();item=row["items"][0]
    row=run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":"edit","item_id":item["id"],"expected_item_revision":item["revision"],"completed":True})
    project=run("project.create",{"name":"Trip"})
    promoted=run("quicklist.promote",{"list_id":row["id"],"expected_revision":row["revision"],"project_id":project["id"]})
    assert promoted["task_ids"]==[t["id"] for t in row["items"]]
    with session_scope() as db:
        assert len(list(db.scalars(select(Task))))==5
        assert db.get(Task,item["id"]).status=="completed"
        assert all(t.project_id==project["id"] for t in db.scalars(select(Task)))
        assert not db.get(Task,row["id"]).is_quick_list
        assert len(list(db.scalars(select(ActionChange).where(ActionChange.entity_id==item["id"]))))>=2

def test_foreign_list_item_and_project_are_rejected():
    row=capture();other=run("quicklist.create",{"title":"Private"},owner="other")
    with pytest.raises(DomainError):read(row["id"],"other")
    with pytest.raises(DomainError):run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":"edit","item_id":other["id"],"expected_item_revision":1,"title":"steal"})
    project=run("project.create",{"name":"Other"},owner="other")
    with pytest.raises(DomainError):run("quicklist.promote",{"list_id":row["id"],"expected_revision":row["revision"],"project_id":project["id"]})
    assert read(row["id"])["is_quick_list"]

def test_past_deadline_is_retained_with_opt_in_alert():
    row=capture(due_date="2020-01-01",planned_date="2020-01-01")
    assert row["status"]=="open" and row["total"]==4 and row["deadline_alert"]=="off"
    assert all(t["due_date"] is None for t in row["items"])

def test_capture_limit_rejects_whole_transaction():
    with pytest.raises(DomainError):capture(items=[{"title":"x"}]*101)
    with session_scope() as db:assert not list(db.scalars(select(Task)))

def checklist(*titles):
    return run("quicklist.create",{"title":"Groceries","items":[{"title":t} for t in titles]})

def item_change(row,operation,key=None,**args):
    return run("quicklist.item",{"list_id":row["id"],"expected_revision":row["revision"],"operation":operation,**args},key=key)

def check(row,item,completed=True):
    return item_change(row,"edit",item_id=item["id"],expected_item_revision=item["revision"],completed=completed)

def status(identity):
    with session_scope() as db:return db.get(Task,identity).status

def record_revision(identity):
    with session_scope() as db:return db.get(StructureRecord,identity).revision

def reminder_notice(task_id):
    run("schedule.create",{"title":"Buy it","when":(now()-timedelta(minutes=1)).replace(microsecond=0).isoformat(),"timezone":"America/Chicago","task_id":task_id})
    with session_scope() as db:
        scan_schedules(db)
        for job in db.scalars(select(Job).where(Job.kind=="reminder")):deliver_occurrence(db,job)
        db.flush()
        return db.scalar(select(Notification).where(Notification.task_id==task_id)).id

def deadline_notice(task_id):
    with session_scope() as db:
        notice=Notification(owner_id="davin",dedup_key="deadline:"+task_id,category="deadline",title="Due",body="",task_id=task_id,scheduled_at=now(),eligible_at=now())
        db.add(notice);db.flush()
        return notice.id

def test_last_check_finishes_the_list_and_its_receipt_undoes_it():
    row=checklist("Milk","Eggs")
    row=check(row,row["items"][0])
    assert row["status"]=="open" and "list_finished" not in row
    eggs=row["items"][1]
    args={"list_id":row["id"],"expected_revision":row["revision"],"operation":"edit","item_id":eggs["id"],"expected_item_revision":eggs["revision"],"completed":True}
    finished=run("quicklist.item",args,key="last-check")
    assert finished["list_finished"] is True and finished["status"]=="completed"
    # A replay returns the same receipt and finishes nothing twice.
    assert run("quicklist.item",args,key="last-check")==finished
    assert read(row["id"])["revision"]==finished["revision"]
    # Undo uses only what the receipt returned: the list revision and the item revision.
    eggs=next(i for i in finished["items"] if i["id"]==eggs["id"])
    reopened=check(finished,eggs,completed=False)
    assert reopened["list_reopened"] is True and reopened["status"]=="open"
    assert [i["status"] for i in reopened["items"]]==["completed","open"]

@pytest.mark.parametrize("path",["task.complete","task.update","notification.complete"])
def test_last_item_finishes_the_list_from_task_paths(path):
    row=checklist("Milk","Eggs")
    row=check(row,row["items"][0])
    eggs=row["items"][1]
    if path=="notification.complete":
        result=run(path,{"notification_id":reminder_notice(eggs["id"])})
    else:
        args={"task_id":eggs["id"],"expected_revision":eggs["revision"]}
        result=run(path,{**args,"status":"completed"} if path=="task.update" else args)
    current=read(row["id"])
    assert current["status"]=="completed" and result["list_finished"] is True
    assert (result["list_id"],result["list_revision"])==(row["id"],current["revision"])

def test_finishing_a_list_with_open_items_needs_consent_and_undo_reopens_them():
    row=checklist("Milk","Eggs","Bread")
    row=check(row,row["items"][0])
    with pytest.raises(DomainError) as refused:
        run("task.complete",{"task_id":row["id"],"expected_revision":row["revision"]})
    assert refused.value.code=="LIST_HAS_OPEN_ITEMS" and "2 items" in refused.value.message
    assert refused.value.data=={"task_id":row["id"],"revision":row["revision"],"open_count":2,"open_item_ids":[i["id"] for i in row["items"][1:]]}
    unchanged=read(row["id"])
    assert unchanged["revision"]==row["revision"] and [i["status"] for i in unchanged["items"]]==["completed","open","open"]
    done=run("task.complete",{"task_id":row["id"],"expected_revision":row["revision"],"complete_open_items":True})
    assert done["status"]=="completed"
    assert sorted(done["completed_item_ids"])==sorted(i["id"] for i in row["items"][1:])
    assert {i["status"] for i in read(row["id"])["items"]}=={"completed"}
    undone=run("task.reopen",{"task_id":row["id"],"expected_revision":done["revision"],"item_ids":done["completed_item_ids"]})
    assert undone["status"]=="open" and sorted(undone["reopened_item_ids"])==sorted(done["completed_item_ids"])
    assert [i["status"] for i in read(row["id"])["items"]]==["completed","open","open"]
    # The undo reopens only this list's own items: another list's item, or item_ids on a normal task, are refused.
    finished=run("task.complete",{"task_id":row["id"],"expected_revision":undone["revision"],"complete_open_items":True})
    other=checklist("Soap")
    plain=run("task.create",{"title":"Call the bank"})
    for target,ids in ((finished,[other["items"][0]["id"]]),(plain,[row["items"][0]["id"]])):
        with pytest.raises(DomainError) as invalid:
            run("task.reopen",{"task_id":target["id"],"expected_revision":target["revision"],"item_ids":ids})
        assert invalid.value.code=="INVALID_ARGUMENT"
    assert status(row["id"])=="completed" and {i["status"] for i in read(row["id"])["items"]}=={"completed"}
    assert status(other["items"][0]["id"])=="open" and status(plain["id"])=="open"

def test_consent_covers_only_the_open_items_the_owner_was_shown():
    row=checklist("Milk")
    milk=row["items"][0]["id"]
    with pytest.raises(DomainError) as asked:
        run("task.complete",{"task_id":row["id"],"expected_revision":row["revision"]})
    assert asked.value.data["open_item_ids"]==[milk]
    # Eggs joins through a task path while the question is up, which leaves the list's revision as it was.
    eggs=run("task.create",{"title":"Eggs","parent_task_id":row["id"]})["id"]
    consent={"task_id":row["id"],"expected_revision":row["revision"],"complete_open_items":True}
    with pytest.raises(DomainError) as refused:
        run("task.complete",{**consent,"open_item_ids":asked.value.data["open_item_ids"]})
    assert refused.value.code=="LIST_HAS_OPEN_ITEMS" and "2 items" in refused.value.message
    assert refused.value.data=={"task_id":row["id"],"revision":row["revision"],"open_count":2,"open_item_ids":[milk,eggs]}
    assert [status(i) for i in (row["id"],milk,eggs)]==["open","open","open"]
    done=run("task.complete",{**consent,"open_item_ids":refused.value.data["open_item_ids"]})
    assert done["status"]=="completed" and sorted(done["completed_item_ids"])==sorted([milk,eggs])
    assert [status(i) for i in (milk,eggs)]==["completed","completed"]

def test_reopening_a_finished_list_alone_keeps_its_items_checked():
    row=checklist("Milk")
    finished=check(row,row["items"][0])
    assert finished["status"]=="completed"
    reopened=run("task.reopen",{"task_id":row["id"],"expected_revision":finished["revision"]})
    assert reopened["status"]=="open" and "list_finished" not in reopened
    assert [i["status"] for i in read(row["id"])["items"]]==["completed"]

@pytest.mark.parametrize("path",["task.update","task.batch","record.update","notification.complete"])
def test_other_ways_of_finishing_a_list_with_open_items_are_refused(path):
    row=checklist("Milk","Eggs")
    if path=="task.update":
        args={"task_id":row["id"],"expected_revision":row["revision"],"status":"completed"}
    elif path=="task.batch":
        args={"items":[{"task_id":row["id"],"expected_revision":row["revision"],"status":"completed"}]}
    elif path=="record.update":
        # The Tasks screen changes the list's status through its record.
        args={"record_id":row["id"],"expected_revision":record_revision(row["id"]),"schema_revision":definition()["revision"],"status_id":"completed"}
    else:
        args={"notification_id":deadline_notice(row["id"])}
    with pytest.raises(DomainError) as refused:run(path,args)
    assert refused.value.code=="LIST_HAS_OPEN_ITEMS"
    assert refused.value.data=={"task_id":row["id"],"revision":row["revision"],"open_count":2,"open_item_ids":[i["id"] for i in row["items"]]}
    current=read(row["id"])
    assert current["status"]=="open" and current["revision"]==row["revision"]

def test_a_batch_with_consent_finishes_the_list_and_its_items():
    row=checklist("Milk","Eggs")
    result=run("task.batch",{"items":[{"task_id":row["id"],"expected_revision":row["revision"],"status":"completed","complete_open_items":True}]})
    assert result["applied_ids"]==[row["id"]] and status(row["id"])=="completed"
    assert {i["status"] for i in read(row["id"])["items"]}=={"completed"}

def test_a_selection_update_finishes_a_list_only_with_consent():
    from jarvis.task_tools import list_tasks
    row=checklist("Milk","Eggs")
    receipt=run("task.create",{"title":"Groceries receipt"})
    with session_scope() as db:
        selection=list_tasks(db,"davin",{"query":"Groceries"})["selection_id"]
    with pytest.raises(DomainError) as refused:
        run("task.selection_update",{"selection_id":selection,"changes":{"status":"completed"}})
    assert refused.value.code=="LIST_HAS_OPEN_ITEMS"
    assert [status(i) for i in (row["id"],receipt["id"],*(i["id"] for i in row["items"]))]==["open"]*4
    # Consent reaches the list; the plain task in the same selection simply completes.
    run("task.selection_update",{"selection_id":selection,"changes":{"status":"completed","complete_open_items":True}})
    assert [status(i) for i in (row["id"],receipt["id"],*(i["id"] for i in row["items"]))]==["completed"]*4

def test_schedule_complete_refuses_a_list_with_open_items_and_finishes_a_list_through_its_last_item():
    row=checklist("Milk","Eggs")
    when={"when":"2030-01-02T09:00:00","timezone":"America/Chicago"}
    on_list=run("schedule.create",{"title":"Shop",**when,"task_id":row["id"]})
    with session_scope() as db:revision=db.get(Schedule,on_list["id"]).revision
    with pytest.raises(DomainError) as refused:
        run("schedule.complete",{"schedule_id":on_list["id"],"expected_revision":revision})
    assert refused.value.code=="LIST_HAS_OPEN_ITEMS"
    with session_scope() as db:
        alert=db.get(Schedule,on_list["id"])
        assert (alert.status,alert.revision)==("active",revision)
    assert status(row["id"])=="open"
    row=check(row,row["items"][0])
    eggs=run("schedule.create",{"title":"Buy eggs",**when,"task_id":row["items"][1]["id"]})
    with session_scope() as db:revision=db.get(Schedule,eggs["id"]).revision
    result=run("schedule.complete",{"schedule_id":eggs["id"],"expected_revision":revision})
    assert result["list_finished"] is True and status(row["id"])=="completed"

def test_archiving_the_last_open_item_finishes_the_list_and_unarchiving_reopens_it():
    row=checklist("Milk","Eggs")
    row=check(row,row["items"][0])
    eggs=row["items"][1]
    archived=run("task.update",{"task_id":eggs["id"],"expected_revision":eggs["revision"],"archived":True})
    assert archived["list_finished"] is True and status(row["id"])=="completed"
    restored=run("task.update",{"task_id":eggs["id"],"expected_revision":archived["revision"],"archived":False})
    assert restored["list_reopened"] is True and status(row["id"])=="open"

@pytest.mark.parametrize("path",["task.update","record.update"])
def test_moving_the_last_open_item_out_finishes_the_list(path):
    row=checklist("Milk","Eggs")
    row=check(row,row["items"][0])
    eggs=row["items"][1]
    if path=="task.update":
        errands=run("task.create",{"title":"Errands"})
        moved=run(path,{"task_id":eggs["id"],"expected_revision":eggs["revision"],"parent_task_id":errands["id"]})
    else:
        # Organize moves the item's record to another home.
        errands=create("project","Errands")
        moved=run(path,{"record_id":eggs["id"],"expected_revision":record_revision(eggs["id"]),"schema_revision":definition()["revision"],"parent_id":errands["id"]})
    current=read(row["id"])
    assert moved["list_finished"] is True and current["status"]=="completed"
    assert [i["id"] for i in current["items"]]==[row["items"][0]["id"]]

def test_remove_cancels_an_item_and_drops_it_from_every_count():
    row=checklist("Milk","Eggs","Bread")
    row=check(row,row["items"][0])
    milk=row["items"][0]
    removed=item_change(row,"remove",item_id=milk["id"],expected_item_revision=milk["revision"])
    assert status(milk["id"])=="cancelled" and removed["status"]=="open"
    assert (removed["total"],removed["done"])==(2,0)
    assert (removed["quick_total"],removed["quick_done"])==(2,0)
    with session_scope() as db:
        listed=next(r for r in structure.records(db,"davin",limit=200)["items"] if r["id"]==row["id"])
    assert (listed["quick_total"],listed["quick_done"])==(2,0)  # The Tasks chip "Quick list · done/total".

def test_removing_items_finishes_a_checked_list_and_leaves_an_emptied_one_open():
    row=checklist("Milk","Eggs")
    row=check(row,row["items"][0])
    eggs=row["items"][1]
    finished=item_change(row,"remove",item_id=eggs["id"],expected_item_revision=eggs["revision"])
    assert finished["list_finished"] is True and finished["status"]=="completed"
    lone=checklist("Typo")
    typo=lone["items"][0]
    emptied=item_change(lone,"remove",item_id=typo["id"],expected_item_revision=typo["revision"])
    assert emptied["status"]=="open" and (emptied["total"],emptied["done"])==(0,0) and "list_finished" not in emptied

def test_a_cancelled_list_is_never_finished_or_reopened():
    row=checklist("Milk")
    cancelled=run("task.update",{"task_id":row["id"],"expected_revision":row["revision"],"status":"cancelled"})
    checked=check(cancelled,row["items"][0])
    assert checked["status"]=="cancelled" and "list_finished" not in checked
    unchecked=check(checked,checked["items"][0],completed=False)
    assert unchecked["status"]=="cancelled" and "list_reopened" not in unchecked

def test_adds_to_a_finished_list_reopen_it_using_each_receipt():
    row=checklist("Milk")
    finished=check(row,row["items"][0])
    first=item_change(finished,"add",title="Eggs")
    assert first["list_reopened"] is True and first["status"]=="open"
    second=item_change(first,"add",title="Bread")
    assert "list_reopened" not in second and [i["title"] for i in second["items"]]==["Milk","Eggs","Bread"]

def test_rescheduling_a_checked_items_reminder_reopens_the_finished_list():
    row=checklist("Milk")
    milk=row["items"][0]
    alert=run("schedule.create",{"title":"Buy milk","when":"2030-01-02T09:00:00","timezone":"America/Chicago","task_id":milk["id"]})
    assert check(row,milk)["status"]=="completed"
    with session_scope() as db:revision=db.get(Schedule,alert["id"]).revision
    result=run("schedule.reschedule",{"schedule_id":alert["id"],"expected_revision":revision,"when":"2030-01-03T09:00:00"})
    current=read(row["id"])
    assert result["list_reopened"] is True and current["status"]=="open"
    assert current["items"][0]["status"]=="open"

def test_cap_and_reorder_count_open_and_unarchived_checked_items():
    row=checklist(*[f"Item {i}" for i in range(100)])
    with pytest.raises(DomainError) as full:item_change(row,"add",title="One more")
    assert full.value.code=="LIST_FULL"
    filed=[i["id"] for i in row["items"][:97]]
    with session_scope() as db:
        # The automatic archive files checked items after a day; they stay in the list's history.
        db.execute(text("UPDATE tasks SET status='completed', completed_at=now(), archived=true, archive_reason='automatic', archived_at=now() WHERE id = ANY(:ids)"),{"ids":filed})
    added=item_change(row,"add",title="One more")
    unarchived=[i["id"] for i in added["items"] if not i["archived"]]
    assert len(unarchived)==4
    moved=item_change(added,"reorder",order=unarchived[::-1])
    assert [i["id"] for i in moved["items"]][:4]==unarchived[::-1]

def test_a_long_used_list_reads_its_recent_history_and_counts_all_of_it():
    row=checklist(*[f"Item {i}" for i in range(62)])
    ids=[i["id"] for i in row["items"]]
    with session_scope() as db:
        # Sixty checked items filed by the automatic archive, Item 0 the most recently checked.
        for n,identity in enumerate(ids[:60]):
            db.execute(text("UPDATE tasks SET status='completed', completed_at=now()-make_interval(mins=>:n), archived=true, archive_reason='automatic', archived_at=now() WHERE id=:id"),{"n":n,"id":identity})
    current=read(row["id"])
    # The items still on the list, then the fifty most recently finished, in their saved order.
    assert [i["id"] for i in current["items"]]==[*ids[60:],*ids[:50]]
    assert (current["done"],current["total"])==(current["quick_done"],current["quick_total"])==(60,62)

def test_setup_is_account_scoped_skip_resume_and_stale_protected():
    row=run("onboarding.save",{"expected_revision":0,"preferred_name":"Morgan","timezone":"America/Chicago","purpose":"Work and home","status":"skipped"})
    assert setup()["preferred_name"]=="Morgan" and setup()["status"]=="skipped"
    assert setup("other")["revision"]==0
    with pytest.raises(DomainError):run("onboarding.save",{"expected_revision":0,"preferred_name":"Overwrite"})
    resumed=run("onboarding.save",{"expected_revision":row["revision"],"status":"in_progress"})
    assert resumed["purpose"]=="Work and home"

def test_setup_requires_explanation_and_separate_confirmation():
    row=run("onboarding.save",{"expected_revision":0,"classification_name":"Client","description":"Short"})
    with pytest.raises(DomainError):run("onboarding.preview",{"expected_revision":row["revision"]})
    row=run("onboarding.save",{"expected_revision":row["revision"],"description":"Organizations I do paid projects for at work.","examples":"ABC is a client; Andi is an ABC project."})
    result=run("onboarding.preview",{"expected_revision":row["revision"]},key="setup-turn:1")
    proposal=result["proposal"]
    assert definition()["revision"]==1
    with pytest.raises(DomainError):run("structure.apply",{"proposal_id":proposal["id"],"expected_revision":1},key="setup-turn:2")
    with pytest.raises(DomainError):run("onboarding.save",{"expected_revision":result["progress"]["revision"],"status":"completed"})
    apply(proposal)
    completed=run("onboarding.save",{"expected_revision":result["progress"]["revision"],"status":"completed","step":"done"})
    assert completed["status"]=="completed"
    assert "setup-group" in [t["id"] for t in definition()["types"]]
    with session_scope() as db:
        assert not list(db.scalars(select(Task))) and not list(db.scalars(select(Note)))
        assert db.get(FieldUnderstanding,("davin","type:setup-group"))

def test_changed_setup_answers_invalidate_preview():
    result=run("onboarding.preview",{"expected_revision":0})
    apply(result["proposal"])
    with pytest.raises(DomainError):run("onboarding.save",{"expected_revision":1,"status":"completed","classification_name":"Different"})
    assert setup()["status"]=="in_progress"

def test_setup_invalid_timezone_never_changes_profile():
    with pytest.raises(DomainError):run("onboarding.save",{"expected_revision":0,"preferred_name":"Nope","timezone":"invalid/zone"})
    assert setup()["revision"]==0

def test_explicit_rules_work_without_waiting_for_model_assessment():
    home=create("client","ABC")
    with session_scope() as db:
        for field in db.scalars(select(FieldUnderstanding)):field.status="needs_input"
    rule=run("routing.create",{"phrase":"Transcript Intelligence","type_id":"task","parent_id":home["id"],"reason":"Confirmed ABC project"})
    task=create("task","Finish Transcript Intelligence docs")
    assert task["parent_id"]==home["id"]
    with session_scope() as db:
        stored=db.get(RoutingPattern,rule["id"]);stored.origin="learned"
    assert create("task","Transcript Intelligence follow-up")["parent_id"] is None

def test_rule_edit_has_revision_guard_and_keeps_memory_separate():
    home=create("client","ABC")
    rule=run("routing.create",{"phrase":"Old phrase","type_id":"task","parent_id":home["id"],"reason":"Old"})
    edited=run("routing.change",{"pattern_id":rule["id"],"expected_revision":rule["revision"],"action":"edit","phrase":"New phrase","reason":"Corrected by me"})
    assert edited["origin"]=="explicit"
    assert create("task","New phrase docs")["parent_id"]==home["id"]
    assert create("task","Old phrase docs")["parent_id"] is None
    with pytest.raises(DomainError):run("routing.change",{"pattern_id":rule["id"],"expected_revision":rule["revision"],"action":"pause"})
    with session_scope() as db:
        assert not list(db.scalars(select(Memory)))
        state=routing.state(db,"davin")
        assert state["patterns"][0]["destination"]=="ABC"
        assert "Confirmed" in state["patterns"][0]["explanation"]


def test_shared_list_roles_and_personal_setup_boundary(client):
    from test_accounts import client_for,command,shared
    guest=client_for("guest")
    shared(client,guest)
    row=command(guest,"quicklist.create",title="Team checklist",items=[{"title":"Team item"}])
    assert guest.get("/api/v1/quick-lists/"+row["id"]).status_code==200
    assert guest.get("/api/v1/onboarding").status_code==403
    assert guest.post("/api/v1/commands",json={"command_id":str(uuid4()),"tool":"onboarding.save","arguments":{"expected_revision":0}}).status_code==403
    from jarvis.models import WorkspaceMember
    with session_scope() as db:
        member=db.scalar(select(WorkspaceMember).where(WorkspaceMember.account_id=="guest"));member.role="viewer"
    assert guest.get("/api/v1/quick-lists/"+row["id"]).status_code==200
    assert guest.post("/api/v1/commands",json={"command_id":str(uuid4()),"tool":"quicklist.item","arguments":{"list_id":row["id"],"expected_revision":row["revision"],"operation":"add","title":"No"}}).status_code==403
    personal=client_for("stranger")
    assert personal.get("/api/v1/quick-lists/"+row["id"]).status_code==404


def test_scoped_bot_can_capture_but_not_change_setup(client):
    from test_external_agents import key,call
    from jarvis import bot_access,external_service
    from jarvis.api import app
    from fastapi.testclient import TestClient
    credential,headers=key(client)
    response=call(headers,"quicklist.create",{"title":"Bot checklist","items":[{"title":"One"}]})
    assert response.status_code==200,response.text
    assert call(headers,"onboarding.save",{"expected_revision":0}).status_code==403
    assert client.post("/api/v1/bot-keys/"+credential["id"]+"/revoke").status_code==200
    assert call(headers,"quicklist.create",{"title":"Revoked"}).status_code==401


def test_resumed_setup_uses_current_profile_preferences():
    run("onboarding.save",{"expected_revision":0,"preferred_name":"Morgan","timezone":"America/Chicago","status":"skipped"})
    run("settings.update",{"preferred_name":"Rowan","timezone":"Europe/London"})
    resumed=setup()
    assert resumed["preferred_name"]=="Rowan" and resumed["timezone"]=="Europe/London"
    assert resumed["status"]=="skipped"
