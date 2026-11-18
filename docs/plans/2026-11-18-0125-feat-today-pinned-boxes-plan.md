---
title: Today Pinned Boxes - Plan
type: feat
date: 2026-11-18
topic: today-pinned-boxes
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Today Pinned Boxes - Plan

## Goal Capsule

- **Objective:** The owner can keep a short, impromptu to-do list in front of them on Today and work through it there, adding and checking items, without filing anything into the organization. Later, a project's tasks for today get the same kind of box.
- **Means:** Pinned boxes on the Today screen, built on the existing quick lists (whose items are already real, unfiled tasks), with project boxes as the second phase (KTD1, KTD2).
- **Product authority:** Davis, in the brainstorm and planning answers of 2026-11-18. The Product Contract wins on behavior. Rearranging or hiding Today's built-in sections is not active scope.
- **Execution profile:** Two pull requests, both in `rdavisdunham/jarvis` (the Eridani app). PR1 ships quick-list boxes (U1–U6). PR2 ships project boxes (U7–U8) after PR1 merges. Claude may merge each PR on green CI and report afterwards.
- **Stop conditions:** Stop and ask Davis if a change would remove anything from Due and overdue (R12), change another member's Today (R14), or change task data when someone unpins (R16). The one-time old-pin conversion (R21, KTD14) is approved and is not a stop.
- **Open blockers:** None.

---

## Product Contract

**Product Contract preservation:** changed: R6, R7, R12 and Dependencies; added R17–R22. These follow Davis's planning answers of 2026-11-18, recorded as Key Decisions below.

### Summary

Pinning a quick list or a project to Today gives it its own box on the Today screen, alongside Schedule and Due and overdue. You start, add to and check off a quick list in its box, and the box goes away by itself once everything is checked. A quick list that has a date shows up as a box on that date. A project box shows that project's tasks for today, and anything added in it is filed into that project. Quick-list boxes ship first; project boxes follow.

### Problem Frame

Quick lists exist so the owner can capture "this, this and this" without setting up a project, but they don't stay in view. Their "Pin to Today" control only sets the list's do-date to today. The list then shows as one ordinary row under Due and overdue, and from the next day on it is styled as overdue. Its items are only visible in a dialog. An unpinned list with no project shows up in Inbox. Davis tried the pin and found the list sitting somewhere in Today's rows rather than pinned. As it stands, the quick list is not something he wants to use.

Separately, Davis wants to split part of his day by project (Eridani, remotea, ABC Home & Commercial) and add tasks straight into a project from Today. His organization is not fully set up yet, so this is the second need, not the first.

### Key Decisions

- **Items are real tasks that are never filed.** Each item can be searched and Dani can see it, but it is never placed into a project, area or space. Governs R8. (session-settled: user-directed — chosen over items that live only on the list until promoted, and over a checkbox notepad with no task features: the items should be ordinary work, just unfiled.)
- **Rebuild quick lists rather than add a parallel feature.** The box becomes the home of quick lists, replacing the dialog-only experience. Governs R1, R2, R4. (session-settled: user-approved — chosen over a separate scratch feature beside quick lists, and over removing quick lists: quick-list items already behave like the unfiled tasks this needs.)
- **A pin lasts until it is removed.** Pinning does not reset each day. Finishing a list hides its box but keeps the pin, so any reopen brings the box back. Governs R3, R6, R17. (session-settled: user-directed — chosen over a fresh list each morning, and over a pin that finishing deletes: the box should go away by itself once everything is checked and come back if the list reopens.)
- **Any number of boxes.** A box is just a view of tasks, so there is no reason to limit pins to one. Governs R13. (session-settled: user-directed — chosen over one pinned list at a time.)
- **A project box shows only that project's tasks for today.** Governs R9. (session-settled: user-directed — chosen over all open tasks with today's first, and over all open tasks in plain order.)
- **Due and overdue stays the complete safety net.** Pinning never removes a task from Due and overdue, so a task can appear in a box and in Due. This includes quick-list items that have their own date. Governs R7, R12. (session-settled: user-directed — chosen over moving boxed tasks out of Due, and over keeping dated quick-list items box-only: Davis wants Due to be predictable.)
- **Pinned boxes only; a fully customizable Today waits.** Governs R13 and the Scope Boundaries. (session-settled: user-approved — chosen over quick-list boxes alone, and over reordering, hiding and resizing every Today section.)
- **Quick-list boxes first, project boxes second.** Davis would use quick-list boxes first, and his organization is not fully set up yet. Governs the order of R1–R8 and R9–R11.
- **A pin belongs to the person, not to the list or project.** Each person's pins are part of their own Today, so pinning in a shared workspace does not change anyone else's Today. Governs R14.
- **Checking the last item can be undone.** Without an undo, one mis-tap makes the whole box disappear. Governs R6.
- **Finishing a list that still has open items asks first, then completes everything.** Governs R18. (session-settled: user-directed — chosen over finishing the list while leaving its items open, and over refusing: "Hey, two items aren't checked. Are you sure you want to finish this whole list?")
- **Lists are pinned when they are created, unless they get a date; a dated list shows up on its date.** Governs R19, R20. (session-settled: user-directed — chosen over unpinned-by-default lists that land in Inbox: "pin it to today by default unless I ask for a different due date. and lists that are due on a day should automatically show up on the day that they're due or do".)
- **Lists pinned the old way become real pins.** Governs R21. (session-settled: user-approved — chosen over leaving their old do-dates in place, which would keep them as overdue rows in Due.)

### Requirements

**Quick-list boxes (first phase)**

- R1. The owner can start a new quick list directly on Today by giving it a title and items, and it appears immediately as a pinned box.
- R2. Any existing quick list can be pinned or unpinned, from its box and from the list itself. The current "Pin to Today" control becomes this pin and no longer changes the list's do-date.
- R3. A pinned quick list stays on Today from day to day until it is unpinned or finished, and being pinned never marks it overdue.
- R4. Inside the box, the owner can add items, check and uncheck items, and edit an item's text without opening a dialog.
- R5. Checked items fold into a short "N done" line in the box. Opening the line shows them, so one can be unchecked.
- R6. When the last open item is checked, from any surface, the list is finished and its box leaves Today. The list stays pinned, and an undo reopens it with that item unchecked, so the box returns.
- R7. A pinned quick list does not also appear as its own row in Today's Inbox. If the list has its own due date or do date, Due and overdue still lists it (per R12).
- R8. Items keep today's quick-list behavior: they are real, searchable tasks that are never auto-filed, organized or scanned for agent readiness.

**Project boxes (second phase)**

- R9. The owner can pin a project to Today. Its box shows the project's open tasks that are due or planned for today, or overdue.
- R10. Adding a task in a project box creates it in that project, planned for today, exactly as adding it to that project anywhere else would.
- R11. A project box stays until it is unpinned, even when nothing is due today. It then shows that nothing is due, along with its add field.

**All boxes**

- R12. Due and overdue keeps listing every open task due or planned by today, whether or not that task also appears in a box. This includes quick-list items that have their own date.
- R13. Today shows every box in the order the boxes were pinned, followed by any dated boxes (R19). Boxes are the same size and look as Today's other boxes.
- R14. Pins are per person: pinning or unpinning changes only the Today of the person who did it.
- R15. In chat and by voice, Dani can pin and unpin quick lists and projects, and can add, check and uncheck items in a pinned quick list.
- R16. Unpinning a box never changes or deletes its tasks.

**Finishing and reopening (first phase)**

- R17. Adding an item to a finished list, or unchecking one of its items, reopens the list. If the list is pinned, its box returns.
- R18. Finishing a list that still has open items asks for confirmation, naming how many items aren't checked. Once confirmed, the list and all its open items are completed, and an undo reopens all of them.
- R19. A quick list with a due date or do date appears as a box on Today from that date on, until it is finished, whether or not it is pinned.
- R20. A new quick list is pinned for the person who created it, unless it is given a date or the creator asks for it not to be pinned. This applies on Today, from Tasks, through Dani and through outside agents.
- R21. Open quick lists that were pinned the old way (do-date set) become pinned for the workspace owner, and their do-date is cleared, once, when this ships.
- R22. An item typed by mistake can be removed from the box. It is cancelled rather than deleted, and it no longer counts as open or done.

### Quick-list box lifecycle

```mermaid
stateDiagram-v2
  direction TB
  [*] --> Showing: Created without a date (R1, R20)
  Hidden --> Showing: Pin (R2)
  Showing --> Hidden: Unpin (R2, R16)
  Showing --> Finished: Last open item checked (R6) or finish confirmed (R18)
  Finished --> Showing: Undo, add or uncheck (R6, R17)
  Dated --> Showing: Date arrives (R19)
```

### Key Flows

- F1. Jot a list on Today
  - **Trigger:** The owner wants a quick "this, this and this" list.
  - **Steps:** On Today, start a new list, type a title and a few items, and save. The box appears on Today. Through the day, check items off in the box and add more as they come up.
  - **Outcome:** The list stays on Today across days until every item is checked, then leaves by itself.
  - **Covered by:** R1, R3, R4, R5, R6
- F2. Work a project's day (second phase)
  - **Trigger:** The owner wants Eridani's tasks for today together.
  - **Steps:** Pin the Eridani project to Today. Its box shows Eridani tasks due or planned for today. Add "fix the voice toggle" in the box; it is filed in Eridani and planned for today.
  - **Outcome:** The box stays until unpinned, and Due and overdue still lists the same tasks.
  - **Covered by:** R9, R10, R11, R12
- F3. Ask Dani
  - **Trigger:** The owner says "add milk to my groceries list" or "make me a packing list".
  - **Steps:** Dani reads the owner's boxes, picks the list the owner meant by meaning (so "groceries" matches a list called "Grocery"), and adds the item. When nothing fits, Dani starts a new pinned list. When several lists fit, Dani asks which one.
  - **Outcome:** The item appears in the box on every open screen. Dani never claims a save that the server refused.
  - **Covered by:** R15, R20

### Acceptance Examples

- AE1. Covers R3. Given a quick list pinned on Monday with two open items, when the owner opens Today on Tuesday, then the box is still there and nothing about the list is shown as overdue.
- AE2. Covers R6. Given a pinned list with one open item left, when the owner checks it, then the list is finished, the box leaves Today and an undo is offered. When they undo, the box returns, pinned, with that item open.
- AE3. Covers R7, R12. Given a pinned quick list with no due date or do date, then it appears as its box and not as a row in Inbox or Due and overdue. Given the same list with a due date of today, then it appears as its box and as a row in Due and overdue.
- AE4. Covers R12. Given the Eridani project is pinned and one of its tasks is due today, then that task appears in the Eridani box and in Due and overdue, and checking it in either place finishes it in both.
- AE5. Covers R10. Given a pinned project that syncs with Linear, when the owner adds a task in its box, then the task is created in Eridani in that project and no Linear issue is created.
- AE6. Covers R14. Given a shared workspace, when one member pins a project or list, then the other members' Today screens are unchanged.
- AE7. Covers R6, R17. Given a pinned list that was finished yesterday, when Dani adds "eggs" to it, then the list reopens and its box is back on Today with "eggs" open.
- AE8. Covers R18. Given a pinned list with two open items, when the owner finishes the list from its Due row, then they are asked "2 items aren't checked. Finish the whole list?". Confirming completes the list and both items. Undo reopens all three.
- AE9. Covers R19. Given an unpinned list with a do date of Thursday, then it has no box on Wednesday and has a box on Thursday and every later day until it is finished.

### Scope Boundaries

**Deferred for later**

- Rearranging, hiding or resizing Today's built-in sections (Schedule, Due and overdue, Reviews, Inbox, Finished today, Recent notes).
- Boxes for areas, spaces, clients or saved filters.
- Reordering boxes other than by when they were pinned.
- Showing a project box's tasks beyond those for today.

**Outside this work**

- A free-text scratch pad whose lines are not tasks.
- Any change to what Due and overdue lists, other than including dated quick-list items (R12).

**Considered and not built**

- Pins in Activity's revert list. Unpinning is already the inverse of pinning, and pins are not task data. This would change if pins began carrying content.
- A per-box limit on how many open items are shown. A quick list holds at most 100 items, and Due already caps its own rows. Add a "Show all" limit if real lists make Today hard to scan.
- Deleting a member's pins when the member is removed, or a list's pins when it is promoted. Only that member's own Today reads a pin, and `boxes()` already skips promoted lists. Saved views and search preferences are kept the same way. Sweep stale rows with one query if they ever matter.

#### Deferred to Follow-Up Work

- A `planned_through` filter on Dani's `task_list`, so that Dani's "due and overdue" read matches the do-dates the web uses. This gap already exists today and is not new work.
- Adding `quicklist_item` to Dani's lean core tools, if voice evals show the extra tool-loading round matters.

### Dependencies / Assumptions

- Quick-list items are left out of Today's ordinary sections, except Due and overdue, which includes items that have their own due date or do date (R12).
- Viewers in a shared workspace can pin boxes for their own Today (R14), in the app and through Dani, but cannot add, check or remove items. This matches their read-only access everywhere else.

### Sources / Research

- `apps/api/jarvis/quick_lists.py`: a quick list is a parent task with child item tasks, with at most 100 items. Operations are add, edit and reorder; there is no delete, and the parent is never completed.
- `apps/web/src/QuickLists.tsx`: the current "Pin to Today" control sets the list's do-date, in both the create dialog and the detail view.
- `apps/web/src/Today.tsx` and `apps/web/src/productivity.ts`: Due and overdue is built from tasks whose do-date or due date is today or earlier. Inbox is built from open tasks with no project, space or area. Quick-list items are excluded from both.
- `apps/api/jarvis/placement.py`, `apps/api/jarvis/readiness.py`, `apps/api/jarvis/quick_sort.py`: quick lists and their items are skipped by auto-placement, readiness and Home filing.
- `apps/api/jarvis/linear_commands.py`: Linear issues are created only by explicit Linear create or publish commands, so a task added to a Linear-synced project stays local.
- `apps/web/src/undo-toast.tsx`: the app's existing undo toast.
- `docs/ERIDANI_WEB_V1_PRD.md` (C1 Quick lists): the original quick-list intent, including inline completion and a Today pin.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Pins live in a new `today_pins` table keyed by workspace, account, kind and target.** It follows the `SearchPreference` pattern (`apps/api/jarvis/search_models.py`), not `OwnerSettings`. `OwnerSettings` is keyed by workspace, and `settings.*` commands are blocked in shared workspaces (`access.py` `PERSONAL_TOOLS`). A composite `account:workspace` key would also show up as a fake owner to the workers that loop over `OwnerSettings` (`notices.py`, `readiness.py`, `auto_start.py`). Because this is stored data, choosing a separate table now is cheaper than moving the data later. The table needs migration `0065_today_pins`. Each row records `pinned_at`, which sets box order (R13). Governs R14.
- KTD2. **One server function builds a person's boxes. The web, Dani and MCP all read it.** `today.boxes(db, owner, account, day)` returns visible boxes in order. Pinned boxes come first, in `pinned_at` order. Dated boxes follow, by date (R19). Each box has its kind, target, title, open items with IDs and revisions, the checked items not yet auto-archived (they make up the "N done" line, R5), and why it is showing (`pinned` or `dated`). Finished (completed or cancelled), archived, promoted or unreadable targets are skipped. Their pin rows stay, so a reopen or restore brings the box back (R6, R17). The web Today uses it through `GET /api/v1/today/boxes`, so the boxes Dani describes are the boxes on screen.
- KTD3. **Finishing and reopening happen once per command, after the command's writes settle.** The rule runs at the end of `domain.execute`, after `observe_core`, for every quick list whose items changed status or membership during the command. That way it sees final state from every writer. The writers are the `task.*` branch (including `task.batch`, `task.selection_update` and `record.update` through `sync_capabilities`), `quicklist.item`, `task_alerts.finish_task` (used by `notification.complete` and `schedule.complete`), `schedule.reschedule`, and parent moves in `hierarchy.project_parent`. Each one records the affected list IDs in `db.info`, the way `task_parent_moves` already does. When no item is left open (not `completed` and not `cancelled`) and at least one item is completed, the rule completes the list. A list whose remaining items are all cancelled counts as empty and stays open. When an item reopens, or one is added to a completed list, the rule reopens the list. An add or an uncheck (`quicklist.item` with `completed:false`) on an archived list unarchives it first. The rule never changes a cancelled list. The command's result carries `list_finished` or `list_reopened`, and its list data (status and revision) is re-read after the rule runs. Results from task paths also carry the list's ID and new revision. That way an undo, or a second add, can use the receipt without a revision conflict. Dani can say "that was the last one". It applies to every quick list, not only pinned ones (R6, R17). Moving an item out of the list or cancelling it re-runs the rule, so a move or a removal never leaves a list stuck on Today with nothing open. Reopening the list itself (`task.reopen` with no `item_ids`) changes no item, so the rule does not re-finish it. The pinned box then shows its "All done" state until an item is added, the list is finished again, or it is unpinned.
- KTD4. **Any change that completes a quick list with open items needs explicit consent.** The check runs wherever a quick list's own status becomes completed: `task.complete`, `task.update`, `task.batch`, `task.selection_update`, `record.update` and `finish_task`. The list is refused with `LIST_HAS_OPEN_ITEMS` (with the count) unless the call passes `complete_open_items: true`. `notification.complete` and `schedule.complete` take no consent and always refuse such a list. With consent, the open items are completed in the same command, and the result lists their IDs. `task.reopen` on a quick list accepts optional `item_ids` and reopens those items in the same command; this is the undo. The refusal carries the list's task ID, revision and open count. `record.update` from the Tasks screen only ever refuses and takes no consent field. Whenever any command comes back with `LIST_HAS_OPEN_ITEMS`, the web shows the confirmation (R18). Confirming always sends `task.complete {task_id, expected_revision, complete_open_items: true}`. Dani and MCP get the refusal and must ask the owner before sending consent. Governs R18. (session-settled: user-directed — chosen over finishing the list while leaving its items open: Davis asked for a warning, then complete-all.)
- KTD5. **Undo is the inverse command, not Activity revert.** An undo after a last-item check sends `quicklist.item` edit `completed:false` for that item, and KTD3 reopens the list. An undo after complete-all sends `task.reopen` with `item_ids` (KTD4). `work_revert` reverses one change at a time and cannot undo the list and its items together. The toast lives at App level so it survives leaving Today (R6). Dani handles "undo that" by unchecking, through the same commands.
- KTD6. **Pinning is a command named `today.pin {target_id, pinned}`, with one narrow exemption for viewers in the app and through Dani.** The server works out the kind: a quick-list task in PR1; a project home record in PR2. The command is idempotent and journals nothing to Activity. It emits a `today.changed` event, so open screens reload their boxes when Dani, MCP or another device pins or unpins. The web pins through a dedicated `POST /api/v1/today/pins` route, which runs `today.pin` for the session's account. The route is listed in `access.request_access`'s viewer `reads` set beside `/api/v1/task-views`, because that gate refuses viewer posts to `/api/v1/commands` before any tool check. Viewers are also allowed `today.pin` by name in `access.command_access` and the Dani execution grant. This mirrors how `command_access` already special-cases the archive policy. `bot_access.authorize` is unchanged: viewers cannot hold write keys, and a key created before a downgrade to viewer must stay read-only. Every other write stays refused for viewers. Pinning a target the person cannot read is refused. A pin never changes the target's revision. Governs R2, R14, R15.
- KTD7. **`quicklist.create` takes `pinned`, defaulting to true when no date is given and false when one is.** Pins go to `access.actor()`, so the person who created the list gets the pin on each path: the browser session, the Dani grant or the bot key. Governs R20. `quicklist_list` and `quicklist_get` gain a per-person `pinned` field and an optional `pinned` filter. With `pinned: true`, `quicklist_list` returns the person's pinned lists in any state (open, finished or auto-archived), each marked with its state. That way Dani can find, and reopen, a pinned list that finished days ago (AE7). All three read sites pass the acting account: `tools.py` `_call_tool`, `external_service.backend_read`, and the web's `GET /api/v1/quick-lists` and `/quick-lists/{id}` routes in `api.py`.
- KTD8. **The 100-item cap, reorder and the box's "N done" line all count the same items: open items plus checked items not yet auto-archived.** Today the cap counts every child, auto-archived checked items included. With that count, a long-running list such as groceries fills up even though only three items are open. `reorder` requires exactly that same set of IDs, and the order array `QuickListBody` sends matches it. Auto-archived items keep their saved order after the others. The dialog still shows the older history. This changes a documented limit. Update `docs/BATCH_C_VALIDATION.md`, the `LIST_FULL` message and the `quicklist_item` description ("Reorder supplies all unarchived item IDs").
- KTD9. **A mistyped item is removed by a new `remove` operation on `quicklist.item`, which cancels the item.** Cancelled items are not open, so KTD3 treats a removal like any other status change. All three counters leave cancelled items out of `total` and out of the "N done" line: `read()`, `serial()` in `domain.py`, and the batch counter in `structure.py` that feeds the Tasks chip "Quick list · done/total". Governs R22.
- KTD10. **The box reuses the quick-list checklist, pulled out of its dialog, with a compact variant that looks like Today.** Extract a dialog-free `QuickListBody` and a `useQuickList(id)` hook from `QuickListDetail`. Then both `QuickListDetail` (the dialog) and `TodayBox` use them. In the box's compact variant, each item is a Today row: the `.check` ring, then the item text. The text becomes an input only when tapped or focused; Enter or blur saves, Escape cancels. A remove icon shows on hover or focus. Section names show as small labels. Editing sections and reordering stay in the full list. The box makes one network call per tap, not per refresh. It checks optimistically, with a write queue per box. It refreshes when a `task.changed` event arrives for the list or any of its items. After a revision conflict it reloads and retries the single action once. Unsaved text in the add field is kept in memory per list, not guarded with `useEditor`.
- KTD11. **Dani reaches boxes through the `quick_capture` group, not through CORE.** CORE already has 19 tools against a cap of under 20 (`tests/test_tool_refinement.py`). So `today_boxes` and `today_pin` join `quick_capture`, taking it from 6 tools to 8. The group's text becomes "Quick checklists and Today boxes: add, check, pin; promote". All new guidance goes in tool and group descriptions. The global prompt has about 147 bytes left and the live prompt about 96, so neither changes. In PR2, `today_pin` also joins `goals_projects`. The matching rule from F3 lives in the `today_boxes` and `quicklist_item` descriptions. Dani tries, in order: the boxes; then the person's pinned lists in any state (KTD7), where an add reopens a finished list; then unpinned lists, matched by noun; and only then starts a new pinned list. `quicklist_item`'s "Read quicklist_get first" becomes "Read today_boxes, quicklist_list or quicklist_get first".
- KTD12. **MCP gains the quick-list reads it is already told to use.** Add `quicklist_list`, `quicklist_get` and `today_boxes` to the read tuple in `external_mcp.py`, and route them to `service.backend_read`. Add `today.pin` to `bot_access.COMMAND_SCOPES` under `tasks:write`, and `today_boxes` to `READ_SCOPES` under `tasks:read`. Pinning a project also needs `organization:read`.
- KTD13. **A project box is keyed on the Structure home record, not the older `Project` row.** Projects created in Organize are task-backed homes with no `Project` row (`structure.py`, `tests/test_organization_foundation.py`). Linear issues filed into a home carry a `· Linear` project id that points elsewhere. The box shows open tasks in the home's subtree that Due's own rule would show (`isOpen` plus `scheduledBy`), so AE4 holds by construction. It reuses `task_list`'s `home_id` matching (`under_home` in `task_tools.py`). Adding in the box sends `task.create {parent_task_id: <home record's task_id>, planned_date: today}`, which `observe_core` files under the home (R10). Do not use `project_id`: Organize-made homes have no `Project` row, so it returns NOT_FOUND. The project box returns the home's task ID for this. Governs R9, R10.
- KTD14. **Old pins convert once, inside migration `0065`.** The conversion covers each open, unarchived quick list whose `planned_date` is on or before the workspace's own today when the migration runs: its saved time zone, else the app default (`JARVIS_TIMEZONE`). The old control only ever wrote the day of pinning in that zone, so a list deliberately dated for tomorrow keeps its date. (Revised after code review: the first cut used UTC plus one day, which could erase a deliberate date for tomorrow.) For each such list, insert a pin for the workspace owner, then clear the date. Lists with a later `planned_date` keep their date and show up on that day (R19). The workspace owner is the namespace itself for a personal workspace, or the `SharedWorkspace.creator_id`. The same migration completes every open quick list that has no open items and at least one completed item, setting the fields `finish_task` would set. Every row the migration changes gets its `revision` bumped and `updated_at` set, so the record registry and open clients notice. These lists were checked off before the finish rule existed, and completing them keeps them from appearing as "All done" boxes. Clearing dates and completing lists is safe for the previous release, because both leave valid lists. Governs R21.

### High-Level Technical Design

Every surface reaches the same domain commands and the same boxes read:

```mermaid
flowchart TB
  Web[Web Today: TodayBox, QuickListBody] -->|/commands, /today/pins| Domain
  Dani[Dani chat and voice: quick_capture group] -->|tools| Domain
  MCP[MCP and bot keys] -->|tasks:write / tasks:read| Domain
  Domain[domain.execute: quicklist.*, task.*, notification/schedule, today.pin] --> Hook[Finish / reopen rule after the writes settle KTD3]
  Hook --> Tasks[(tasks)]
  Domain --> Pins[(today_pins KTD1)]
  Boxes[today.boxes KTD2] --> Pins
  Boxes --> Tasks
  Web -->|GET /today/boxes| Boxes
  Dani -->|today_boxes| Boxes
  MCP -->|today_boxes| Boxes
```

Whether a quick list gets a box for a person on a given day:

```mermaid
flowchart TB
  A{Quick list archived, promoted or unreadable?} -->|yes| N[No box]
  A -->|no| B{List completed or cancelled?}
  B -->|yes| N
  B -->|no| C{Pinned by this person?}
  C -->|yes| P[Box, in pin order]
  C -->|no| D{Due date or do date on or before today?}
  D -->|yes| Q[Box, after pinned boxes, by date]
  D -->|no| N
```

What the finish and reopen hook does when an item changes:

```mermaid
flowchart TB
  S[Item status changed, item added, or item moved out] --> X{List cancelled?}
  X -->|yes| K
  X -->|no| O{Any item still open?}
  O -->|no, at least one completed, list open| F[Complete the list; result says list_finished]
  O -->|yes, and list completed| R[Reopen the list; unarchive if needed; result says list_reopened]
  O -->|otherwise| K[Leave the list as it is]
```

### Sequencing

U1 creates the table that U3 and U4 use. U2 is independent and should land early, because its tests cover every surface. U5 needs U2–U4. U6 needs U5. PR2 adds the project kind to the pin and boxes paths after PR1 merges.

### Deferred to Implementation

- Exact names of the hook's helper functions and the result keys, as long as `list_finished`, `list_reopened` and the completed item IDs are present.
- Whether `quicklist.item` add and item-level edit can drop the list `expected_revision` check. Keep it for `reorder`. Decide once the retry in KTD10 is measured.
- How the box's `task.changed` filter is keyed, by parent ID or by the summed child revisions that `TaskDetails` already uses.

---

## Implementation Units

### PR1: Quick-list boxes

Waits on: nothing.

### U1. Pin store, migration and old-pin conversion

**Goal:** Store per-person pins and convert lists pinned the old way.

**Requirements:** R2, R14, R16, R21; KTD1, KTD14.

**Dependencies:** None.

**Files:**
- `migrations/versions/0065_today_pins.py` (new)
- `apps/api/jarvis/models.py` or a new `apps/api/jarvis/today.py` model module
- `apps/api/jarvis/today.py` (new: pin, unpin and list-pins helpers)
- `tests/test_today_boxes.py` (new)
- `tests/test_release_migrations.py`

**Approach:**
1. Create the `today_pins` table. The key is (owner_id, account_id, kind, target_id), plus `pinned_at`.
2. Write the helpers. Pinning is an idempotent upsert that keeps the original `pinned_at`. Unpinning deletes the row. Listing returns pins in `pinned_at` order.
3. Do the KTD14 conversion and the completion of already-checked lists in the migration's upgrade, using plain SQL.

**Patterns to follow:** `SearchPreference` in `search_models.py`. The release-compatibility docstring style of `0064_run_learnings.py`.

**Test scenarios:**
- Pinning the same target twice keeps one row and the first `pinned_at`.
- In a shared workspace, pins for account A are not returned for account B (Covers AE6).
- Conversion: an open quick list with today's `planned_date` becomes a pin for the workspace owner, with its date cleared.
- Conversion leaves completed lists, archived lists and ordinary tasks with a `planned_date` untouched.
- Conversion leaves a quick list planned for next week with its date and no pin.
- An open quick list whose items were all checked before the migration is completed by it, with its revision bumped. A list with no items, or with only cancelled items, stays open.
- Migration compatibility: the previous release's models still load against the upgraded schema.

**Verification:** The migration upgrades and downgrades on the pgvector test database, and pin helpers are private per account.

### U2. Finish and reopen rule, complete-all consent, item removal and cap

**Goal:** A quick list finishes and reopens the same way whichever surface changed it.

**Requirements:** R6, R17, R18, R22; KTD3, KTD4, KTD8, KTD9.

**Dependencies:** None.

**Files:**
- `apps/api/jarvis/domain.py` (the settle step at the end of `execute`, the consent check on status changes, and the `complete_open_items` and `item_ids` arguments)
- `apps/api/jarvis/task_alerts.py`, the `notification.complete` / `schedule.complete` / `schedule.reschedule` handlers and `apps/api/jarvis/hierarchy.py` (record affected list IDs; refuse a list with open items)
- `apps/api/jarvis/quick_lists.py` (`remove` operation, cap count, reorder set, `read()` totals, add or uncheck on a completed or archived list, re-read after the rule)
- `apps/api/jarvis/structure.py` (the quick-list batch counter; `record.update` status changes refuse a list with open items)
- `apps/api/jarvis/task_archive.py` (only if unarchiving needs a helper)
- `tests/test_batch_c.py`
- `tests/test_task_archive.py`

**Approach:**
1. Record affected quick-list IDs in `db.info` from every writer KTD3 names, and run the rule once after `observe_core`.
2. Add the KTD4 consent check wherever a quick list's own status becomes completed.
3. Make `task.reopen` with `item_ids` reopen the list and those items in one receipt.
4. Change `read()`, the cap count and the reorder set per KTD8 and KTD9.
5. Return the finish and reopen flags in each command's result.

**Execution note:** Write the "last item checked" paths as failing tests first: `quicklist.item`, `task.complete`, `task.update status`, a bot-key `task_complete`, and a reminder's `notification.complete`.

**Patterns to follow:** `apply_lifecycle` in `task_archive.py` for status-driven field changes. `quick_lists.mutate` for revision bumps and `task.changed` events.

**Test scenarios:**
- Checking the last open item through `quicklist.item` completes the list, and the result has `list_finished: true` (Covers AE2).
- The same through `task.complete` on the item, `task.update status=completed`, and a bot key's `task_complete`.
- With one item cancelled and the others completed, the list finishes.
- Unchecking an item of a finished list reopens the list, and the result has `list_reopened: true`.
- Adding an item to a finished list reopens it (Covers AE7).
- Adding an item to a finished list that was auto-archived unarchives and reopens it.
- `task.complete` on a list with two open items, without consent, is refused with `LIST_HAS_OPEN_ITEMS` and count 2. Nothing changes.
- With consent, the list and both items are completed, and the result lists the two item IDs (Covers AE8).
- `task.reopen` with those `item_ids` reopens the list and both items in one command.
- `task.reopen` on a finished list with no `item_ids` leaves it open with its items still checked.
- Without consent, a list with two open items is refused the same way through `task.update status=completed`, a `record.update` status change from the Tasks screen, and its deadline notification's Complete.
- Moving the last open item to another parent finishes the list, including a `record.update parent_id` move from Organize.
- Completing the last open item from its own reminder (`notification.complete`) finishes the list.
- `remove` cancels the item. It drops out of `total` and "N done" in `read()`, `serial()` and the Tasks chip count.
- Removing the last open item finishes the list when another item is checked. Removing a list's only item leaves the list open and empty.
- A cancelled list is never finished or reopened by the rule.
- Undo from the receipt: check the last item, then uncheck it using only the list revision returned by that receipt; no revision conflict.
- Two adds to a finished list, each using the previous receipt's revision, both succeed (Covers AE7).
- Unchecking an item of a finished, auto-archived list through `quicklist.item` unarchives and reopens it.
- Rescheduling a checked item's reminder (`schedule.reschedule`) reopens a finished list.
- Cap: a list with 100 children, 97 of them checked and auto-archived, accepts a new item. A list with 100 open items refuses it with `LIST_FULL`.
- Reorder: a list with 3 open items and 100 auto-archived checked items reorders with just its 3 unarchived IDs.
- Replaying a command with the same command ID returns the same receipt and does not finish or reopen twice.

**Verification:** Every status path leaves a quick list in the same state, and existing quick-list tests pass.

### U3. `today.pin`, the boxes read and pinned-by-default creation

**Goal:** One server path for pinning and one for reading boxes, used by every surface.

**Requirements:** R2, R3, R7, R13, R14, R16, R19, R20; KTD2, KTD6, KTD7.

**Dependencies:** U1.

**Files:**
- `apps/api/jarvis/today.py` (the `today.pin` command, and `boxes()`)
- `apps/api/jarvis/domain.py` (register the command and its `workspace:` lock prefix)
- `apps/api/jarvis/quick_lists.py` (`pinned` on create; pinned field and filter on list and get)
- `apps/api/jarvis/access.py` (the viewer exemptions in `request_access`'s `reads` set, `command_access` and the execution grant)
- `apps/api/jarvis/api.py` (`GET /api/v1/today/boxes` and `POST /api/v1/today/pins`)
- `tests/test_today_boxes.py`
- `tests/test_accounts.py`

**Approach:**
1. `today.pin` resolves the target, checks that the person can read it, and writes or deletes the pin for `access.actor()`.
2. `POST /api/v1/today/pins` runs `today.pin` through `execute` with the request's command ID.
3. `boxes()` applies the KTD2 order and the visibility rule in the High-Level Technical Design.
4. `quicklist.create` pins for the actor per KTD7.

**Patterns to follow:** The saved-views tests in `tests/test_accounts.py`, which prove privacy between members. The `archive_policy` exemption shape in `access.command_access`.

**Test scenarios:**
- A list created without a date is pinned for its creator and shows in `boxes()`.
- A list created with a date is not pinned. It has no box before that date, and has one on and after it (Covers AE9).
- `pinned=false` with no date creates an unpinned list.
- Two pinned lists come back in pin order, followed by a dated list.
- Unpinning removes the box and leaves the list's tasks and revision unchanged.
- A finished pinned list has no box, and its pin row remains. After a reopen the box is back in its original position.
- An archived or promoted list has no box.
- Shared workspace: member A pins a list, and member B's boxes are unchanged (Covers AE6).
- Over HTTP with a viewer session, `POST /today/pins` pins and unpins, while the viewer's `POST /commands` for `quicklist.item` is still refused with `READ_ONLY`.
- A bot key created while its holder was an editor, then downgraded to viewer, is refused `today_pin`.
- Pinning a target in another workspace is refused.
- `GET /today/boxes` works for a viewer and requires a session.
- `today.pin` writes a `today.changed` event row.
- A cancelled pinned list has no box.

**Verification:** `boxes()` returns the expected list for owner, member and viewer fixtures.

### U4. Dani, MCP and bot-key parity

**Goal:** Dani and outside agents can see boxes, pin and unpin, and work items, with the same results the web gets.

**Requirements:** R15, R20; KTD11, KTD12.

**Dependencies:** U2, U3.

**Files:**
- `apps/api/jarvis/tools.py` (`VOICE_MUTATIONS` gets `today.`, the `today_boxes` read tool, and acting-account dispatch for quick-list reads)
- `apps/api/jarvis/tool_catalog.py` (group, short label and descriptions)
- `apps/api/jarvis/bot_access.py`
- `apps/api/jarvis/external_mcp.py`
- `apps/api/jarvis/external_service.py`
- `tests/test_tool_refinement.py`
- `tests/test_external_agents.py`
- `tests/test_drift_guards.py`
- `evals/app/features/quick_capture.json`

**Approach:**
1. Wire the tools per KTD11 and KTD12.
2. Descriptions carry the F3 matching rule:
   - read the boxes first
   - pick by meaning, ignoring "my", "list" and plurals
   - one fit: add the item
   - no box fits: try the person's pinned lists in any state (`quicklist_list` with `pinned: true`); an add to a finished one reopens it
   - still nothing: try unpinned lists by noun
   - several fit: ask
   - nothing fits: start a pinned list
3. Descriptions also say to ask before sending `complete_open_items`, and to treat "undo that" after a finish as an uncheck.
4. Add a length guard for each new description.

**Patterns to follow:** The `reviews_due` description guard in `tests/test_record_reviews.py`. The `test_external_record_kinds_and_mcp_reads_agree` drift guard.

**Test scenarios:**
- The registry has `today_pin` and `today_boxes` in `quick_capture`, every group has fewer than 10 tools, and CORE is unchanged.
- `test_global_prompts_are_small_and_live_has_no_schema_mechanics` passes unchanged.
- The tool list for a `tasks:read` MCP key includes `quicklist_list`, `quicklist_get` and `today_boxes`.
- Drift guard: every tool that a description says to "read first" is callable for that key.
- A bot key's `today_pin` pins for the key's account, not the workspace.
- A bot key's `task_complete` on a list with open items gets `LIST_HAS_OPEN_ITEMS`.
- Eval: with pinned "Grocery" and unpinned "Party groceries", "add milk to my groceries list" adds to "Grocery" and creates no list.
- Eval: with two pinned lists that both fit, Dani asks which one and saves nothing.
- Eval: a pinned "Grocery" list, finished and auto-archived two days earlier, gets "add eggs to my groceries list". The list reopens with eggs open, and no new list is created (Covers AE7).
- Eval: "take groceries off Today" unpins, and the list remains in `quicklist_list`.
- Eval: "what's on my Today" mentions the pinned boxes and their open counts.

**Verification:** The tool-refinement, external-agent and drift-guard tests pass, and the quick-capture evals pass.

### U5. The Today box and starting a list on Today

**Goal:** Boxes on Today where the owner starts, works and finishes lists.

**Requirements:** R1, R2, R4, R5, R13, R22; KTD10.

**Dependencies:** U2, U3.

**Files:**
- `apps/web/src/QuickLists.tsx` (extract `QuickListBody`, with its compact variant, and `useQuickList`; pin control in the dialog; `QuickCapture` pin default per KTD7)
- `apps/web/src/TodayBox.tsx` (new)
- `apps/web/src/Today.tsx`
- `apps/web/src/App.tsx` (the "+ Quick list" launcher leaves Today and stays on Tasks)
- `apps/web/src/today.css`
- `apps/web/src/types.ts`
- `apps/web/src/TodayBox.test.tsx` (new)
- `apps/web/src/QuickLists.test.tsx`

**Approach:**
1. Extract the body and hook so the dialog keeps working unchanged.
2. `TodayBox` uses the standard panel markup. The header holds the title and a menu: pin, open the full list, and "Finish list". Below it come the open items as KTD10 rows, the add field, the "N done" fold, and an "All done" state. A list with no items yet shows "Add your first item." instead of "All done".
3. "Finish list" with open items shows the R18 confirmation and sends consent. With nothing open, it completes the list at once. Both paths end with the KTD5 toast.
4. One "Start a list" control on Today, directly after the last box (or after Due and overdue when there are none), opens the title-and-items form in place. It replaces the "+ Quick list" launcher on Today. On save the form closes, the new box scrolls into view and its add field takes focus, and no dialog opens (R1). The form allows an empty list and stays disabled above 100 lines.
5. Focus: when a checked or removed item leaves the open list, focus moves to the next open item's check, or to the add field when none remain.
6. Viewers see boxes without checks, the add field, remove or "Finish list".
7. Dated boxes show a date chip instead of the unpin control.

**Patterns to follow:** The `section.panel` markup in `Today.tsx`. `useStructureActions().run` for commands, with command-ID reuse on retry. The static-markup tests in `FinishedToday.test.tsx`.

**Test scenarios:**
- A box renders its title, open items, an "N done" line, and the add field.
- Checking an item updates it at once. When two taps happen quickly, both commands are sent in order.
- On a revision conflict the box reloads and retries once. A second conflict shows an inline error.
- `LIST_FULL` shows inline under the add field.
- Removing an item drops it from the box.
- A box whose items are all checked shows "All done" with the add field. A box with no items shows "Add your first item."
- "Finish list" with two open items asks first. With nothing open, it finishes the list at once.
- Starting a list on Today closes the form, shows the new box with focus in its add field, and opens no dialog.
- Keyboard: checking the focused item moves focus to the next open item's check, and checking the last one moves focus to the add field.
- The "N done" line counts only checked items not yet auto-archived.
- A viewer's box has no checks, add field, remove or "Finish list".
- A dated, unpinned box shows its date and no unpin.
- `parseChecklist` and the static markup tests still pass.

**Verification:** The type check and vitest pass. Manually: start, check and finish a list on Today in the dev app.

### U6. Today sections, the finish toast and the browser test

**Goal:** Today's other sections and the undo match the new rules.

**Requirements:** R6, R7, R12, R18; KTD4, KTD5.

**Dependencies:** U5.

**Files:**
- `apps/web/src/Today.tsx` (box placement, the Inbox exclusion, quick-list items with dates in Due)
- `apps/web/src/App.tsx` (load boxes, including on `today.changed`; App-level finish toast; complete-all confirmation)
- `apps/web/src/Structure.tsx` (the Tasks today view shows quick-list items that have their own date, so Due's "See all" reaches them)
- `apps/web/src/undo-toast.tsx` (an App-level host, if the hook can't be lifted as it is)
- `apps/web/e2e/batch-c.mjs`
- `apps/web/src/today-counts.test.ts`
- `docs/TASK_CARDS.md`
- `docs/BATCH_C_VALIDATION.md`

**Approach:**
1. Boxes render in the side column directly after Due and overdue, before Reviews and Inbox. On a narrow screen they stack in the same order.
2. Inbox skips lists that have a box.
3. Due gets its own predicate: ordinary open tasks, plus open quick-list items that have their own due date or do date and whose list is open and unarchived. The shared `isOpen` keeps excluding quick-list items, so Inbox never shows them. Tasks' today view, which Due's "See all" opens, shows the same dated items.
4. When a command result says `list_finished`, App shows "Groceries is done" with Undo for 6 seconds, per KTD5. If the finished box held focus, focus moves to Undo, and the toast stays while Undo has focus.
5. Whenever a command comes back with `LIST_HAS_OPEN_ITEMS`, from any row or from the Tasks screen, App opens a confirmation ("2 items aren't checked. Finish the whole list?"). Confirming sends `task.complete` with consent, using the list ID and revision from the refusal (KTD4).
6. A `today.changed` event reloads the boxes, so a pin made by Dani or another device shows at once.
7. Update `batch-c.mjs` to start a list on Today and check that its box appears.

**Patterns to follow:** The optimistic toggle in `App.tsx` `toggle()`. The `useUndoToast` toast markup.

**Test scenarios:**
- A pinned, undated list is a box and is not an Inbox row (Covers AE3).
- The same list with a due date of today is a box and a Due row (Covers AE3).
- A quick-list item with a due date of today appears in Due and overdue. One dated tomorrow appears in neither Due nor Inbox. A dated item of a completed list does not appear in Due.
- A pin made through another session (a `today.changed` event) adds the box without a manual reload.
- A list pinned Monday shows no overdue styling on Tuesday (Covers AE1).
- Checking the last item shows the toast. Undo returns the box with that item open (Covers AE2).
- Checking a dated list's Due row with two open items asks first. Cancelling changes nothing. Confirming finishes all three, and Undo reopens all three (Covers AE8).
- The toast survives switching from Today to Tasks.
- Keyboard: when the last item's box leaves, focus lands on Undo.
- Completing a list with open items from the Tasks screen shows the same confirmation.
- Browser test: start a list on Today, check every item, the box leaves, Undo brings it back.

**Verification:** Vitest and `batch-c.mjs` pass against the dev stack.

### PR2: Project boxes

Waits on: PR1, merge order only. Davis wants quick-list boxes in production before project boxes are ready.

### U7. Project pins and project boxes on the server

**Goal:** Pin a project home and get its today's tasks as a box, through every surface.

**Requirements:** R9, R10, R11, R12, R14, R15; KTD6, KTD13.

**Dependencies:** U3, U4.

**Files:**
- `apps/api/jarvis/today.py`
- `apps/api/jarvis/bot_access.py`
- `apps/api/jarvis/tool_catalog.py`
- `tests/test_today_boxes.py`
- `tests/test_external_agents.py`
- `evals/app/features/quick_capture.json`

**Approach:**
1. `today.pin` accepts a project-type Structure record.
2. `boxes()` builds the project box from the home subtree with Due's predicate, leaving out quick-list items.
3. An archived home hides the box but keeps the pin.
4. Adding uses `task.create` with `parent_task_id` set to the home's task ID and today as its do-date (KTD13). The box returns that task ID.
5. Pinning a project with a bot key requires `organization:read`.

**Patterns to follow:** `under_home` in `task_tools.py`. `observe_core` / `from_task` in `structure.py`, which file a task under its parent's record.

**Test scenarios:**
- A project box lists open tasks in the home's subtree that are due or planned by today, and nothing else.
- A task due today appears in the box and in the Due data, and completing it once removes it from both (Covers AE4).
- Adding in the box files the task under the home with today's do-date, and creates no Linear issue (Covers AE5).
- A Linear issue filed under the home appears in the box.
- A pinned project with nothing due still returns an empty box (R11).
- An archived home has no box. Restoring it brings the box back.
- A bot key without `organization:read` cannot pin a project.
- Eval: "add fix the voice toggle to Eridani for today" files it in Eridani with today's do-date.

**Verification:** Project box tests and evals pass.

### U8. Project boxes on Today and pinning from Organize

**Goal:** Project boxes appear on Today, and projects can be pinned from where they live.

**Requirements:** R9, R10, R11, R13.

**Dependencies:** U7.

**Files:**
- `apps/web/src/TodayBox.tsx`
- `apps/web/src/Structure.tsx` (a pin control on project homes)
- `apps/web/src/TodayBox.test.tsx`
- `apps/web/e2e/batch-c.mjs` or a new `apps/web/e2e/today-boxes.mjs`

**Approach:**
1. `TodayBox` renders the project kind with ordinary task rows.
2. Its add field sends the KTD13 `task.create`, planned for today.
3. Its header links to the project.
4. Pin and unpin from the project's header in Organize.

**Patterns to follow:** `taskRow` in `Today.tsx`.

**Test scenarios:**
- A project box renders task rows and "Nothing due today" when empty.
- Adding in a project box sends `task.create` with the home's task ID as parent and today's date.
- Browser test: pin a project in Organize, its box appears on Today, and unpinning removes it.

**Verification:** Vitest and the browser test pass.

---

## Verification Contract

| Gate | Command or check | Applies to |
|---|---|---|
| Backend tests | `export JARVIS_ENV_FILE="" JARVIS_DATABASE_URL="postgresql+psycopg://postgres:verify@127.0.0.1:55432/postgres"; PYTHONPATH=apps/api:tests:. env -u NODE_ENV .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_today_boxes.py tests/test_batch_c.py tests/test_task_archive.py tests/test_accounts.py tests/test_tool_refinement.py tests/test_external_agents.py tests/test_drift_guards.py tests/test_release_migrations.py` | U1–U4, U7 |
| Full backend suite | The same pytest invocation over `tests/` | Before each PR merges |
| Lint | `ruff check --select E9,F63,F7,F82,F811 apps/api/jarvis tests` | All units |
| Web type check and tests | In `apps/web`: `env -u NODE_ENV npx tsc -b` and `env -u NODE_ENV npx vitest run` | U5, U6, U8 |
| Browser | `apps/web/e2e/batch-c.mjs` (and `today-boxes.mjs` if added) against the dev stack | U6, U8 |
| Dani evals | The quick-capture feature eval in `evals/app/features/quick_capture.json` through `scripts/app_eval` | U4, U7 |
| CI | GitHub Actions green on the PR | Each PR |

## Definition of Done

- Every acceptance example AE1–AE9 has a passing test named in a unit above.
- Checking the last item finishes the list whichever surface does it: the box, the dialog, a task card, Dani, voice or MCP.
- In a shared workspace, one member's pins never change another member's Today, and viewers can pin but not edit.
- After the migration, no open quick list keeps an old do-date from the old pin.
- The global and live prompt budget tests pass unchanged.
- `docs/TASK_CARDS.md` and `docs/BATCH_C_VALIDATION.md` describe boxes, pins, finishing and the new cap.
- No dead code from abandoned approaches remains in the diff.
- Each PR is merged on green CI, and Davis is told what changed, including the migration and the conversion of old pins.
