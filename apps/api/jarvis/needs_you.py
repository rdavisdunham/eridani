"""One list of everything waiting for the owner (docs/END_TO_END_UPGRADE_PLAN.md, Phase 2 "One queue").

Each source keeps its own rows and its own way of resolving them; this module only reads them and says, for each
waiting item, the same four things:

- `decision`: what is being asked, in one line;
- `recommendation`: what Eridani suggests, or None when there is nothing to suggest (a question only the owner
  can answer);
- `evidence`: a few short lines the decision rests on (the agent's summary, the stop detail, the last output);
- `if_accepted`: what happens on "accept", or None when the item has no single accept (it needs an answer).

and where to act: `open` (a view and its parameters, for the web app's navigation) and, for the items that can be
accepted in one tap, `accept` (the shared decision the web app answers through `respondDecision`).

Sources, in the order they are listed (urgent first, then oldest first within each):

| kind | source | waiting when |
|---|---|---|
| `run` | agent runs (remotea) | needs_you, capped, awaiting_approval, waiting_answer, interviewing |
| `proposal` | Dani's control proposals with no run yet | pending and not expired |
| `meeting` | meeting review | proposals still pending |
| `question` | Questions (memory, organization, field, routing, record reviews, context) | pending, not deferred |
| `work` | requests Dani is working on | Dani asked the owner something (needs_input) |
| `draft` | voice drafts on this device | not sent or discarded, not expired |
| `setup` | Set up with Dani | the proposal is waiting to be reviewed |

A source that does not apply (remotea or meeting memory off, a shared workspace) is skipped, never an error: the
list is whatever is waiting that this owner can act on. Each source is read in its own savepoint so one failing
source cannot hide the others; it is named in `unavailable` instead.
"""

import logging

from sqlalchemy import or_, select

from .models import now

logger = logging.getLogger(__name__)

RUN_STATES = ("needs_you", "capped", "awaiting_approval", "waiting_answer", "interviewing")
# Run stops that block work until the owner acts; they push now instead of waiting for a batch.
URGENT_REASONS = {"question_timed_out", "rate_limited", "auth_expired", "agent_errored", "host_offline",
                  "surface_lost", "exited", "verify_infra", "merge_blocked"}
EVIDENCE_LINES, EVIDENCE_CHARS = 5, 300
LIMIT = 200

# What a run in each human-wait state asks, recommends, and does when accepted. Reason-specific rows win.
RUN_ASKS = {
    "awaiting_approval": ("Accept the finished work", "Read the summary and accept it if it does what the task asked.",
                          "The run is approved: the task is completed, or merged first when the run merges its pull request."),
    "waiting_answer": ("Answer the agent's question", None, None),
    "interviewing": ("Answer the agent's questions before it plans", None, None),
    "plan_approval": ("Approve the plan", "Read the plan and approve it, or send it back with what to change.",
                      "The agent starts the work as planned."),
    "plan_review": ("Review the agent's proposed plan changes", None, None),
    "direction": ("Confirm the direction", "Read the direction brief and confirm it, or say what to change.",
                  "The agent plans and works in that direction without asking again."),
    "brainstorm": ("Reply to the agent", None, None),
    "awaiting_merge": ("Merge the pull request", "Merge it once the checks pass.",
                       "The pull request is merged and the task completed."),
}


def listing(db, owner, account=None, device=None) -> dict:
    """Everything waiting for the owner, as one list (see the module doc)."""
    items, unavailable = [], []
    for name, source in (("runs", runs), ("proposals", proposals), ("meetings", meetings),
                         ("questions", questions), ("work", work), ("drafts", drafts), ("setup", setup)):
        try:
            with db.begin_nested():
                items.extend(source(db, owner, account, device))
        except Exception as exc:  # noqa: BLE001 - one source failing must not hide the rest.
            code = getattr(exc, "code", None)
            if code not in ("PERSONAL_WORKSPACE", "REMOTEA_DISABLED", "CONTEXT_DISABLED", "NOT_AUTHORIZED"):
                logger.warning("needs_you: %s failed: %s", name, exc)
                unavailable.append(name)
    items.sort(key=lambda i: (not i["urgent"], i.get("since") or ""))
    counts = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {"items": items[:LIMIT], "total": len(items), "counts": counts, "urgent": sum(i["urgent"] for i in items),
            "unavailable": unavailable, "at": now().isoformat()}


def item(kind, key, title, decision, *, recommendation=None, evidence=(), if_accepted=None, open=None, accept=None,
         urgent=False, since=None, **extra):
    lines = [str(line).strip()[:EVIDENCE_CHARS] for line in evidence if line and str(line).strip()]
    return {"key": key, "kind": kind, "title": (title or "")[:300], "decision": decision,
            "recommendation": recommendation, "evidence": lines[:EVIDENCE_LINES], "if_accepted": if_accepted,
            "open": open, "accept": accept, "urgent": bool(urgent),
            "since": since.isoformat() if hasattr(since, "isoformat") else since, **extra}


# ---------------------------------------------------------------- sources


def brief_lines(brief):
    """A direction brief as evidence: how the agent reads the task, its approach, what it leaves alone."""
    if not isinstance(brief, dict):
        return []
    return [f"{label}: {brief[k]}" for k, label in (("reading", "Reading"), ("approach", "Approach"),
                                                     ("leaves_alone", "Leaves alone")) if brief.get(k)]


def runs(db, owner, account, device):
    from . import agent_control as control
    from . import agent_decisions, agent_link, run_attention, run_direction
    from .models import Task
    from .session_models import AgentRun

    if not agent_link.enabled(db, owner):
        return []
    out = []
    rows = db.scalars(select(AgentRun).where(AgentRun.owner_id == owner, AgentRun.state.in_(RUN_STATES),
                                             AgentRun.dismissed_at.is_(None)).order_by(AgentRun.state_since))
    for run in rows:
        task = db.get(Task, run.task_id) if run.task_id else None
        decisions = agent_decisions.for_run(db, run)
        reason = run.state_reason or ""
        direction = run_direction.public(db, run) if reason == "plan_approval" else None
        key = "direction" if (direction or {}).get("open") else reason if reason in RUN_ASKS else run.state
        attention = run_attention.attention(db, run, control.reason_detail(db, run) or "")
        if key in RUN_ASKS:
            decision, recommendation, accepted = RUN_ASKS[key]
        else:
            decision = (attention or {}).get("headline") or "This run needs you"
            recommendation, accepted = (attention or {}).get("action"), None
        evidence = [run.summary if key == "awaiting_approval" else "",
                    *(brief_lines((direction or {}).get("brief")) if key == "direction" else []),
                    (attention or {}).get("detail"),
                    *((attention or {}).get("last_output") or [])]
        # One tap accepts only where the shared decision has a plain yes (approve, or approve the plan).
        accept = next((d for d in decisions if d.get("status") in ("pending", "open")
                       and ("approve" in d.get("actions", []))), None)
        out.append(item("run", f"run:{run.id}", task.title if task else "A run", decision,
                        recommendation=recommendation, evidence=evidence,
                        if_accepted=accepted if accept else None, accept=accept,
                        open={"view": "remotea", "run_id": run.id},
                        urgent=reason in URGENT_REASONS or run.state == "waiting_answer",
                        since=run.state_since, run_id=run.id, task_id=run.task_id, state=run.state, reason=reason))
    return out


def proposals(db, owner, account, device):
    from . import agent_decisions, agent_link
    from .session_models import AgentPendingControl

    if not agent_link.enabled(db, owner):
        return []
    rows = db.scalars(select(AgentPendingControl).where(
        AgentPendingControl.owner_id == owner, AgentPendingControl.status == "pending",
        AgentPendingControl.run_id.is_(None),
        or_(AgentPendingControl.expires_at.is_(None), AgentPendingControl.expires_at > now()))
        .order_by(AgentPendingControl.created_at))
    out = []
    for row in rows:
        shared = agent_decisions.present(db, row, "control")
        needs_target = bool((shared.get("payload") or {}).get("needs_target"))
        out.append(item("proposal", f"proposal:{row.id}", row.summary, "Start this run?",
                        recommendation=None if needs_target else "Confirm it if it is what you asked for.",
                        evidence=["Choose where it runs first." if needs_target else ""],
                        if_accepted=None if needs_target else "The agent starts on the task.",
                        accept=None if needs_target else shared, open={"view": "remotea", "pending_id": row.id},
                        since=row.created_at, pending_id=row.id))
    return out


def meetings(db, owner, account, device):
    from . import bot_access
    from .context import settings as context_settings
    from .context.routes.review import inbox

    if not context_settings.enabled() or bot_access.shared(db, owner):
        return []
    rows = [r for r in inbox(db, owner, 50, 0)["items"] if r["status"] == "pending"]
    return [item("meeting", f"meeting:{r['source_id']}", r["title"] or "A meeting",
                 f"Review {r['pending']} proposal{'s' if r['pending'] != 1 else ''} from this meeting",
                 recommendation="Approve the ones that are right and dismiss the rest.",
                 open={"view": "meetings", "source": r["source_id"]}, since=r["occurred_at"],
                 source_id=r["source_id"]) for r in rows]


def questions(db, owner, account, device):
    from . import review_questions

    rows = review_questions.listing(db, owner, status="pending", limit=100)["items"]
    return [item("question", f"question:{q['key']}", q.get("question") or "A question", "Answer a question",
                 open={"view": "questions"}, since=q.get("created_at"), question_key=q["key"],
                 question_kind=q.get("kind")) for q in rows]


def work(db, owner, account, device):
    from .agent_work import list_work

    if not account:
        return []
    out = []
    for row in list_work(db, owner, account, limit=50)["items"]:
        if row.get("status") != "needs_input":
            continue
        asked = row.get("clarification") or {}
        question = asked.get("question") if isinstance(asked, dict) else str(asked)
        out.append(item("work", f"work:{row['id']}", row.get("message") or "A request",
                        "Dani needs an answer to carry on", evidence=[question],
                        open={"view": "activity", "work_id": row["id"]}, since=row.get("updated_at"),
                        work_id=row["id"]))
    return out


def drafts(db, owner, account, device):
    from .work_intake import list_drafts

    if not (account and device):
        return []
    return [item("draft", f"draft:{d['id']}", d.get("message") or "A draft", "Send or discard what you said",
                 recommendation="Send it if it says what you meant.", if_accepted="It is sent to Dani as a request.",
                 open={"view": "chat", "draft_id": d["id"]}, since=None, draft_id=d["id"])
            for d in list_drafts(db, owner, account, device)["items"]]


def setup(db, owner, account, device):
    from . import setup as setup_flow

    state = setup_flow.public(db, owner)
    if state.get("status") != "reviewing" or not (state.get("tree_proposal_id") or state.get("memory_candidates")):
        return []
    return [item("setup", "setup", "Set up with Dani", "Review the proposed organization and facts",
                 recommendation="Create what fits and leave out the rest.", open={"view": "setup"})]


# ---------------------------------------------------------------- for Dani


def spoken(db, owner, account=None, device=None, limit=12) -> dict:
    """The list as Dani reads it aloud: one line per item, urgent first, with what to say about the rest."""
    value = listing(db, owner, account, device)
    lines = [{"key": i["key"], "kind": i["kind"], "title": i["title"], "decision": i["decision"],
              "recommendation": i["recommendation"], "urgent": i["urgent"],
              **{k: i[k] for k in ("run_id", "pending_id", "question_key", "work_id") if k in i}}
             for i in value["items"][:limit]]
    return {"total": value["total"], "urgent": value["urgent"], "counts": value["counts"], "items": lines,
            "more": max(0, value["total"] - len(lines)), "next": SPOKEN_NEXT if lines else "Nothing is waiting for the owner."}


SPOKEN_NEXT = ("Say how many things are waiting and read the urgent ones first, each as its decision and title, "
               "with the recommendation when there is one. Act only on the owner's answer, with the tool for that "
               "kind: runs with control_status then control_approve, control_answer, control_plan_review or "
               "control_message; proposals with control_confirm; questions with review_questions and the answer "
               "tool it names; Dani's own questions with work_answer. Meetings are reviewed on the Meetings page.")


# ---------------------------------------------------------------- the summary notice


SUMMARY = "needs_you"
SUMMARY_WINDOW_MINUTES = 60  # A slot still goes out when the scan runs late, within this hour.


def summary_text(value) -> tuple[str, str]:
    """Title and body of the summary: how many wait, how many block work, and the first few decisions."""
    total, urgent = value["total"], value["urgent"]
    title = f"{total} {'thing needs' if total == 1 else 'things need'} you"
    lead = [f"{i['decision']}: {i['title']}" for i in value["items"][:3]]
    body = " · ".join([*([f"{urgent} blocking work"] if urgent else []), *lead])
    return title, body[:1000]


def summary(db, owner, instant=None):
    """At each of the owner's summary times (`needs_you_times`, local), one notice when anything is waiting: the
    batch the plan asks for, so non-urgent decisions arrive together instead of one push each. Between those
    times, also once after meetings whose proposals are ready (`needs_you_after_meetings`, after_meetings). Urgent
    run problems still notify on their own (run_coordinator.notify). Once per slot or meeting; nothing when the
    list is empty."""
    from zoneinfo import ZoneInfo

    from .domain import preferences
    from .models import Notification, SharedWorkspace

    instant = instant or now()
    prefs = preferences(db, owner)
    if not prefs.get("needs_you_summary") or db.get(SharedWorkspace, owner):
        return None
    local = instant.astimezone(ZoneInfo(prefs["timezone"]))
    slot = due_slot(prefs.get("needs_you_times") or [], local)
    met = []
    if slot is not None:
        key = f"needs_you:{owner}:{local.date().isoformat()}T{slot}"
        if db.scalar(select(Notification.id).where(Notification.dedup_key == key)):
            return None
    elif prefs.get("needs_you_after_meetings", True):
        # After a meeting: its proposals are ready, so the batch goes out now rather than at the next time.
        met = after_meetings(db, owner, instant)
        if not met:
            return None
        key = f"needs_you:{owner}:after:{met[0]}"
    else:
        return None
    value = listing(db, owner)
    if not value["total"]:
        return None
    title, body = summary_text(value)
    row = Notification(owner_id=owner, dedup_key=key, category=SUMMARY, title=title, body=body, importance="normal",
                       scheduled_at=instant, eligible_at=instant, created_at=instant,
                       target={"view": "needs", "keys": [i["key"] for i in value["items"][:50]],
                               **({"meetings": met} if met else {})})
    db.add(row)
    db.flush()
    return row


AFTER_MEETING_HOURS = 6  # A meeting older than this is left to the next set time (and to the first deploy's backlog).
AFTER_MEETING_QUIET_MINUTES = 30  # No second summary this soon after one; the next scan picks the meeting up.


def after_meetings(db, owner, instant) -> list[str]:
    """Meetings whose proposals are waiting and that no summary has announced yet, newest first; [] when none, or
    when a summary went out in the last half hour (several meetings ending together make one notice, not several)."""
    from datetime import timedelta

    from .models import Notification

    cutoff = instant - timedelta(hours=AFTER_MEETING_HOURS)
    recent = [m for m in meetings(db, owner, None, None) if when(m.get("since")) and when(m["since"]) >= cutoff]
    if not recent:
        return []
    quiet = instant - timedelta(minutes=AFTER_MEETING_QUIET_MINUTES)
    if db.scalar(select(Notification.id).where(Notification.owner_id == owner, Notification.category == SUMMARY,
                                               Notification.created_at > quiet).limit(1)):
        return []
    announced = set()
    for target in db.scalars(select(Notification.target).where(
            Notification.owner_id == owner, Notification.category == SUMMARY,
            Notification.created_at > instant - timedelta(hours=AFTER_MEETING_HOURS * 2))):
        announced.update((target or {}).get("meetings") or [])
    return [m["source_id"] for m in sorted(recent, key=lambda m: when(m["since"]), reverse=True)
            if m["source_id"] not in announced]


def when(value):
    """An item's `since` as an aware datetime, or None."""
    from datetime import datetime, timezone

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def due_slot(times, local):
    """The summary time (`HH:MM`) whose hour `local` falls in, or None."""
    minutes = local.hour * 60 + local.minute
    for value in sorted(set(times)):
        try:
            hour, minute = (int(part) for part in value.split(":"))
        except ValueError:
            continue
        start = hour * 60 + minute
        if start <= minutes < start + SUMMARY_WINDOW_MINUTES:
            return value
    return None


def still_current(db, n) -> bool:
    """Delivery check: recount the items the summary listed; drop it when all were decided, else refresh its text."""
    listed = set((n.target or {}).get("keys") or [])
    value = listing(db, n.owner_id)
    left = [i for i in value["items"] if i["key"] in listed]
    if not left:
        return False
    n.title, n.body = summary_text({"total": len(left), "urgent": sum(i["urgent"] for i in left), "items": left})
    return True
