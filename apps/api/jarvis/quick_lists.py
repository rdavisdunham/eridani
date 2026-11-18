"""Compact lists reuse Task IDs, revisions, alerts, history and search indexes."""
from datetime import date
from typing import Literal
from pydantic import Field
from sqlalchemy import select
from .domain import Args, DomainError, TaskCreate, TaskUpdate, check_revision, emit, owned, serial
from .models import Task, now

FINISHED = ("completed", "cancelled")
# Parents of tasks whose status or membership changed during this command; settle() finishes or
# reopens the quick lists among them.
CHANGED = "quick_list_changes"

class Item(Args):
    title: str = Field(min_length=1,max_length=500)
    section: str = Field(default="",max_length=120)

class Create(Args):
    title: str = Field(min_length=1,max_length=500)
    items: list[Item] = Field(default_factory=list,max_length=100)
    due_date: date | None = None
    due_time: str | None = None
    due_timezone: str | None = None
    planned_date: date | None = None
    deadline_alert: Literal["off","on"] = "off"

class Change(Args):
    list_id: str
    expected_revision: int = Field(ge=1)

class ItemChange(Change):
    operation: Literal["add","edit","reorder","remove"]
    item_id: str | None = None
    expected_item_revision: int | None = Field(default=None,ge=1)
    title: str | None = Field(default=None,min_length=1,max_length=500)
    section: str | None = Field(default=None,max_length=120)
    completed: bool | None = None
    order: list[str] = Field(default_factory=list,max_length=100)

class Promote(Change):
    project_id: str | None = None

COMMANDS={"quicklist.create":Create,"quicklist.item":ItemChange,"quicklist.promote":Promote}

def children(db, owner, identity):
    from .hierarchy import children as canonical_children
    return canonical_children(db, owner, identity, include_finished_archives=True)

def on_list(items):
    """Open items and checked items not yet archived: what the cap and reorder count."""
    return [x for x in items if not x.archived and x.status!="cancelled"]

def read(db,owner,identity):
    row=owned(db,Task,identity,owner)
    if not row.is_quick_list:
        raise DomainError("NOT_QUICK_LIST","This is now a normal task; open its task details.",409)
    items=children(db,owner,identity)
    # Archived and removed items keep their saved order, after the items still on the list.
    shown=on_list(items);ids={x.id for x in shown}
    items=[*shown,*(x for x in items if x.id not in ids)]
    # A removed (cancelled) item counts as neither open nor done.
    return {**serial(row),"items":[serial(x) for x in items],"done":sum(x.status=="completed" for x in items),"total":sum(x.status!="cancelled" for x in items)}

def listing(db,owner,query=""):
    from .text_normalize import sql_filter
    q=select(Task).where(Task.owner_id==owner,Task.is_quick_list.is_(True),Task.archived.is_(False))
    if query:
        matches=select(Task.parent_task_id).where(Task.owner_id==owner,sql_filter(query,Task.title))
        q=q.where(sql_filter(query,Task.title) | Task.id.in_(matches))
    rows=list(db.scalars(q.order_by(Task.updated_at.desc()).limit(100)))
    return {"items":[read(db,owner,r.id) for r in rows],"limit":100}

def core(db,owner,tool,args,command_id):
    from .domain import mutate
    from .structure import observe_core
    # Use canonical task commands and index observation inside the enclosing atomic receipt.
    from .access import command_access
    values=args.model_dump(exclude_unset=True)
    command_access(db,owner,tool,values)
    args=type(args).model_validate(values)
    result=mutate(db,owner,tool,args,command_id)
    observe_core(db,owner,tool,result,command_id,arguments=args.model_dump(exclude_unset=True))
    return result

def set_status(db,owner,task,status,command_id,**consent):
    """A status change the owner did not type: same task path, without a second access check."""
    from .domain import mutate
    from .structure import observe_core
    result=mutate(db,owner,"task.update",TaskUpdate(task_id=task.id,expected_revision=task.revision,status=status,**consent),command_id)
    observe_core(db,owner,"task.update",result,command_id)

def touch(db,*task_ids):
    """Remember the parents of items whose status or membership changed; settle() picks out the quick lists."""
    db.info.setdefault(CHANGED,set()).update(identity for identity in task_ids if identity)

def complete_open_items(db,owner,row,*,consent,command_id=None):
    """A list finishes with unchecked items only on the owner's consent, and then they are completed with it."""
    items=[x for x in children(db,owner,row.id) if x.status not in FINISHED]
    if items and not consent:
        count=len(items)
        raise DomainError(
            "LIST_HAS_OPEN_ITEMS",
            f"{count} items aren't checked. Finishing the whole list completes them too, so ask first." if count>1
            else "1 item isn't checked. Finishing the whole list completes it too, so ask first.",
            409,{"task_id":row.id,"revision":row.revision,"open_count":count})
    for item in items:
        set_status(db,owner,item,"completed",command_id,complete_open_items=True)
    return [x.id for x in items]

def reopen_items(db,owner,row,item_ids,command_id):
    """The undo after finishing a whole list: reopen the items it completed, in the same command."""
    items={x.id:x for x in children(db,owner,row.id)} if row.is_quick_list else {}
    if not set(item_ids)<=set(items):
        raise DomainError("INVALID_ARGUMENT","Reopen only this quick list's own items; read the list again.")
    reopened=[]
    for identity in dict.fromkeys(item_ids):
        if items[identity].status in FINISHED:
            set_status(db,owner,items[identity],"open",command_id)
            reopened.append(identity)
    return reopened

def settle(db,owner,data,command_id):
    """Finish a quick list once no item is left open and one is checked; reopen it when an item reopens or joins.

    Runs once at the end of every command, after all of its writes, so the box, the dialog, a task card, Dani,
    a reminder or a bot key leave a list in the same state. A cancelled list is never changed, and a list
    whose remaining items were all removed stays open."""
    changed={}
    while pending:=db.info.pop(CHANGED,None):
        for identity in sorted(pending):
            row=db.get(Task,identity)
            if row is None or row.owner_id!=owner or not row.is_quick_list or row.status=="cancelled":continue
            items=children(db,owner,row.id)
            still_open=any(x.status not in FINISHED for x in items)
            if not still_open and row.status!="completed" and any(x.status=="completed" for x in items):
                set_status(db,owner,row,"completed",command_id);changed[row.id]="list_finished"
            elif still_open and row.status=="completed":
                set_status(db,owner,row,"open",command_id);changed[row.id]="list_reopened"
    if not changed or not isinstance(data,dict):return
    for outcome in set(changed.values()):data[outcome]=True
    if "items" in data and data.get("id") in changed:
        identity=data["id"];data.update(read(db,owner,identity))
    else:
        identity=next(reversed(changed))
    # The receipt names the list and its new revision, so an undo or a second add needs no re-read.
    row=db.get(Task,identity)
    data.update(list_id=row.id,list_revision=row.revision)

def reopens(tool,args,row):
    """An add or an uncheck brings back a list that was archived; settle() then reopens it if it was finished."""
    return tool=="quicklist.item" and row.status!="cancelled" and (args.operation=="add" or (args.operation=="edit" and args.completed is False))

def mutate(db,owner,tool,args,command_id):
    if tool=="quicklist.create":
        values=args.model_dump(exclude={"items"})
        root=core(db,owner,"task.create",TaskCreate(**values),command_id)
        row=owned(db,Task,root["id"],owner)
        row.is_quick_list=True
        for i,item in enumerate(args.items):
            child=core(db,owner,"task.create",TaskCreate(title=item.title,parent_task_id=row.id,deadline_alert="off"),command_id)
            task=owned(db,Task,child["id"],owner)
            task.quick_section=item.section;task.quick_order=i
        db.flush()
        return read(db,owner,row.id)
    row=owned(db,Task,args.list_id,owner,lock=True)
    check_revision(row,args.expected_revision)
    if not row.is_quick_list or (row.archived and not reopens(tool,args,row)):
        raise DomainError("NOT_QUICK_LIST","Open an active Quick list.",409)
    if row.archived:
        core(db,owner,"task.update",TaskUpdate(task_id=row.id,expected_revision=row.revision,archived=False),command_id)
    items=children(db,owner,row.id)
    if tool=="quicklist.promote":
        # The container becomes a normal parent task. Children are the same Task rows.
        for task in [row,*items]:
            patch={"is_quick_list":False} if task.id==row.id else {}
            if args.project_id is not None:patch["project_id"]=args.project_id
            from .hierarchy import for_task, project_parent
            record = for_task(db, owner, task.id)
            home = record.parent_id if record else None
            if patch:core(db,owner,"task.update",TaskUpdate(task_id=task.id,expected_revision=task.revision,**patch),command_id)
            # Legacy project_id remains a compatibility classification; promotion
            # must not flatten the list's canonical children into sibling tasks.
            if task.id != row.id and record:
                record.parent_id = home
                project_parent(db, record)
        db.flush()
        return {"task":serial(row),"task_ids":[x.id for x in items],"promoted":True,"note":"Same IDs and history; the list is now a normal parent task and its subtasks."}
    if args.operation=="add":
        if not args.title:raise DomainError("INVALID_ARGUMENT","Give the new item a title.")
        if len(on_list(items))>=100:raise DomainError("LIST_FULL","Quick lists hold up to 100 items, not counting removed items or checked items that were archived. Promote it to normal tasks for larger work.")
        child=core(db,owner,"task.create",TaskCreate(title=args.title,parent_task_id=row.id,deadline_alert="off"),command_id)
        item=owned(db,Task,child["id"],owner)
        item.quick_section=args.section or "";item.quick_order=max([x.quick_order for x in items],default=-1)+1
    elif args.operation in ("edit","remove"):
        item=next((t for t in items if t.id==args.item_id),None)
        if not item or not args.expected_item_revision:raise DomainError("INVALID_ARGUMENT","Read the list and use the item's ID and revision.")
        if args.operation=="remove":
            # A mistyped item is cancelled rather than deleted, so its history stays.
            patch={"status":"cancelled"}
        else:
            patch={}
            if args.title is not None:patch["title"]=args.title
            if args.section is not None:patch["quick_section"]=args.section
            if args.completed is not None:patch["status"]="completed" if args.completed else "open"
            if not patch:raise DomainError("INVALID_ARGUMENT","Provide an item change.")
        core(db,owner,"task.update",TaskUpdate(task_id=item.id,expected_revision=args.expected_item_revision,**patch),command_id)
    else:
        shown=on_list(items)
        if len(args.order)!=len(shown) or set(args.order)!={t.id for t in shown}:raise DomainError("REVISION_CONFLICT","The list changed. Read it again before reordering.",409)
        for i,identity in enumerate(args.order):
            task=next(t for t in shown if t.id==identity)
            if task.quick_order!=i:core(db,owner,"task.update",TaskUpdate(task_id=task.id,expected_revision=task.revision,quick_order=i),command_id)
    row.revision+=1;row.updated_at=now();emit(db,owner,"task.changed",row.id,row.revision)
    db.flush()
    return read(db,owner,row.id)
