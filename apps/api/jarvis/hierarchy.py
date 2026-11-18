"""One local containment graph, with adapters for legacy task API identifiers."""
from sqlalchemy import select
from .models import Task, now
from .structure_models import StructureRecord


def for_task(db, owner, task_id):
    return db.scalar(select(StructureRecord).where(
        StructureRecord.owner_id == owner, StructureRecord.task_id == task_id))


def project_parent(db, row):
    """Compatibility cache only: immediate actionable parent, never a distant ancestor."""
    if not row.task_id:
        return
    task = db.get(Task, row.task_id)
    parent = db.get(StructureRecord, row.parent_id) if row.parent_id else None
    target = parent.task_id if parent and parent.owner_id == row.owner_id else None
    if task.parent_task_id != target:
        # Moving an item out of (or into) a quick list settles that list at the end of the command.
        from .quick_lists import touch
        touch(db, task.parent_task_id, target)
        task.parent_task_id = target
        task.revision += 1
        task.updated_at = now()
    row.provenance = {**row.provenance, "home_version": 1}


def from_task(db, owner, row, task, schema, *, explicit=False):
    from .structure import record_type, validate_parent
    from .domain import DomainError
    if not explicit and row.provenance.get("home_version") == 1:
        # Provider refreshes cannot undo an established local home.
        project_parent(db, row)
        return
    target = None
    if task.parent_task_id and not task.occurrence_id:
        parent = for_task(db, owner, task.parent_task_id)
        if not parent:
            row.provenance = {**row.provenance, "home_conflict": "missing_parent"}
            return
        target = parent.id
    elif explicit:
        target = None
    else:
        # Recurrence lineage is represented by occurrence -> schedule -> template,
        # not containment. Preserve the occurrence's normal project/area home.
        project_parent(db, row)
        return
    legacy_homes = {None, task.project_id, task.area_id, task.space_id}
    if not explicit and row.parent_id not in legacy_homes and row.parent_id != target:
        row.provenance = {**row.provenance, "home_conflict": "different_saved_homes"}
        return
    try:
        validate_parent(db, owner, row, record_type(schema, row.type_id, archived=True), target)
    except DomainError:
        if explicit:
            raise
        row.provenance = {**row.provenance, "home_conflict": "invalid_parent"}
        return
    if row.parent_id != target:
        row.parent_id = target
        row.revision += 1
        row.updated_at = now()
    row.provenance = {k: v for k, v in row.provenance.items() if k != "home_conflict"}
    project_parent(db, row)


def adopt(db, owner, schema):
    """Backfill unambiguous edges only; repeatable, with visible conflict reports."""
    rows = list(db.scalars(select(StructureRecord).where(
        StructureRecord.owner_id == owner, StructureRecord.task_id.is_not(None))))
    for row in rows:
        # Load the task only for rows still to adopt; this runs on every record list.
        if row.provenance.get("home_version") != 1:
            from_task(db, owner, row, db.get(Task, row.task_id), schema)
    db.flush()


def report(db, owner):
    rows = list(db.scalars(select(StructureRecord).where(StructureRecord.owner_id == owner)))
    return {"records": len(rows), "conflicts": [
        {"record_id": r.id, "title": r.title, "reason": r.provenance["home_conflict"]}
        for r in rows if r.provenance.get("home_conflict")
    ]}


# A parent's children in their saved order.
SAVED_ORDER = (Task.quick_order, Task.created_at, Task.id)


def child_tasks(owner, parent_ids, *, include_finished_archives=False):
    """Tasks whose records sit directly under the records `parent_ids`. Finished archives are the checked or
    removed children the automatic archive filed, which a quick list keeps as its history."""
    visible = Task.archived.is_(False)
    if include_finished_archives:
        visible = visible | ((Task.archive_reason == "automatic") & Task.status.in_(("completed", "cancelled")))
    return select(Task).join(StructureRecord, StructureRecord.task_id == Task.id).where(
        StructureRecord.owner_id == owner, StructureRecord.parent_id.in_(parent_ids), Task.owner_id == owner, visible)


def children(db, owner, task_id, *, include_finished_archives=False):
    parent = for_task(db, owner, task_id)
    if not parent:
        return []
    return list(db.scalars(child_tasks(owner, [parent.id], include_finished_archives=include_finished_archives)
                           .order_by(*SAVED_ORDER)))
