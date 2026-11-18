"""Today pins: the boxes each person keeps on Today (today.py), and a one-time conversion of quick lists pinned the
old way.

The old "Pin to Today" control set a list's do-date to the day of pinning, so the list later showed as overdue. Each
open, unarchived quick list with a do-date on or before today, in the workspace's own time zone (the zone the old
control used), becomes a pin for the workspace owner, and its do-date is cleared. A list with a later do-date keeps it
and shows up on that day. Open quick lists whose items were all checked before lists could finish by themselves are completed the
way finishing a task completes one, alerts and notices included. Every changed list and alert gets a new revision, so
the record registry and open clients notice.

A new table, and data changes that leave valid lists, so the previous release keeps working. Downgrade drops the
pins; cleared do-dates and completed lists stay."""
import os
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision = "0065_today_pins"
down_revision = "0064_run_learnings"
branch_labels = depends_on = None


def default_zone():
    # The app's default time zone (the JARVIS_TIMEZONE setting), as the app itself falls back to it.
    zone = os.environ.get("JARVIS_TIMEZONE") or "America/Chicago"
    try:
        ZoneInfo(zone)
    except (ValueError, KeyError):
        return "America/Chicago"
    return zone


def upgrade():
    op.create_table(
        "today_pins",
        sa.Column("owner_id", sa.String(100), primary_key=True),
        sa.Column("account_id", sa.String(100), primary_key=True),
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.Column("target_id", sa.String(36), primary_key=True),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False),
    )
    bind = op.get_bind()
    # The workspace owner's account: the namespace itself in a personal workspace, else the shared workspace's
    # creator. The list's creation time stands in for when it was pinned, so these boxes keep a stable order.
    # "Today" is the workspace's own day: its saved time zone when that is a zone Postgres knows, else the app default.
    bind.execute(sa.text("""
        WITH zones AS (
            SELECT settings.owner_id, settings."values"->>'timezone' AS zone FROM owner_settings settings
            WHERE settings."values"->>'timezone' IN (SELECT name FROM pg_timezone_names)
        ), converted AS (
            UPDATE tasks SET planned_date = NULL, revision = tasks.revision + 1, updated_at = now()
            WHERE tasks.is_quick_list AND NOT tasks.archived AND tasks.status NOT IN ('completed', 'cancelled')
              AND tasks.planned_date <= (now() AT TIME ZONE COALESCE(
                  (SELECT zones.zone FROM zones WHERE zones.owner_id = tasks.owner_id), :default_zone))::date
            RETURNING tasks.id, tasks.owner_id, tasks.created_at
        )
        INSERT INTO today_pins (owner_id, account_id, kind, target_id, pinned_at)
        SELECT converted.owner_id, COALESCE(workspace.creator_id, converted.owner_id), 'quick_list', converted.id,
               converted.created_at
        FROM converted LEFT JOIN shared_workspaces workspace ON workspace.id = converted.owner_id
    """), {"default_zone": default_zone()})
    # A list's items are its children in the record tree, checked items already filed away automatically included.
    # Cancelled items count as neither open nor done, so a list of only cancelled items stays open.
    finished = bind.execute(sa.text("""
        WITH done AS (
            SELECT quick.id FROM tasks quick
            JOIN structure_records home ON home.owner_id = quick.owner_id AND home.task_id = quick.id
            JOIN structure_records child ON child.owner_id = quick.owner_id AND child.parent_id = home.id
            JOIN tasks item ON item.id = child.task_id AND item.owner_id = quick.owner_id
            WHERE quick.is_quick_list AND quick.status NOT IN ('completed', 'cancelled')
              AND (NOT item.archived OR (item.archive_reason = 'automatic' AND item.status IN ('completed', 'cancelled')))
            GROUP BY quick.id
            HAVING bool_and(item.status IN ('completed', 'cancelled')) AND bool_or(item.status = 'completed')
        )
        UPDATE tasks SET status = 'completed', completed_at = COALESCE(completed_at, now()), finished_at = now(),
            archive_eligible_at = now() + interval '24 hours', revision = revision + 1, updated_at = now()
        FROM done WHERE tasks.id = done.id
        RETURNING tasks.id
    """)).scalars().all()
    if not finished:
        return
    ids = {"ids": list(finished)}
    bind.execute(sa.text("""
        UPDATE schedules SET status = 'completed', completed_at = tasks.completed_at, next_run_at = NULL,
            revision = schedules.revision + 1
        FROM tasks WHERE tasks.id = schedules.task_id AND schedules.task_id = ANY(:ids)
          AND schedules.status IN ('active', 'finished')
    """), ids)
    bind.execute(sa.text("""
        UPDATE schedule_occurrences SET status = 'completed'
        WHERE id IN (SELECT occurrence_id FROM notifications WHERE task_id = ANY(:ids) AND completed_at IS NULL)
    """), ids)
    bind.execute(sa.text("""
        UPDATE notifications SET completed_at = now(), read_at = COALESCE(read_at, now())
        WHERE task_id = ANY(:ids) AND completed_at IS NULL
    """), ids)


def downgrade():
    op.drop_table("today_pins")
