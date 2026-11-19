# Task cards: RecordCard and TaskDetails

Eridani roadmap task fe21bb75, "One task card". Written 2026-10-30 against `main` at `a8775fb` plus the
`task-card-parity` branch. Line numbers are from that branch. Code wins over this document.

Two cards open a task:

- **RecordCard** (`apps/web/src/RecordCard.tsx`): the organization record card. It edits the task's
  *record*: schema fields, statuses, home, relationships. Structure.tsx renders it, so it exists only
  inside a `StructureWorkspace` (the Tasks page tabs and Organize). Editor kind `record`; URL
  `?record=record:<id>`.
- **TaskDetails** (`apps/web/src/TaskDetails.tsx`): the original task card. It edits the *task* row
  (`task.update`) and is rendered by App.tsx from `calendarDetail`, so it opens over any page. Editor
  kind `task`; URL `?record=task:<id>`.

Neither card is retired here. This branch closes the cheap gaps with shared components and adds a test
that keeps the shared sections on both cards; it does not change which entry point opens which card.

## Entry points

### Opens RecordCard

| Entry point | Where |
|---|---|
| Tasks page rows (list, board, timeline, all tabs) and its search | `Structure.tsx:158-159` `go`/`open` → `:355`; the header search refilters this list (`App.tsx:974` `searchAllTasks`) |
| Organize: Browse, Atlas, Tree, list rows | same (`Structure.tsx:355`) |
| Dani `ui_records` with `record_id` | `App.tsx:1106` `setRecordControl({record_id})` → `Structure.tsx:72` |
| Activity → open a changed record of kind `record` | `App.tsx:1681` `openWorkRecord` |
| A `?record=record:<id>` link (Copy record link from RecordCard), history restore | `App.tsx:1004` `openLinkedRecord` → Organize; restore `App.tsx` `useAppHistory` → `setTaskRecordControl`/`setRecordControl` |
| Review queue rows, "Main home" on TaskDetails | `Reviews.tsx:16` `openRecord` and `TaskDetails.tsx:491` → `eri-open-custom-record` → `App.tsx:220` (switches to Organize) |
| `eri-open-record` event | `Structure.tsx:71` (no dispatcher left in the web app) |
| Contents and Related records links inside a RecordCard | `RecordCard.tsx` `onOpen` → Structure `go` |

### Opens TaskDetails (all through `openTaskCard`, `App.tsx:253`)

| Entry point | Where |
|---|---|
| Today page task rows | `Today.tsx:142` → `App.tsx:2533` |
| Today box menu "Open full list" (the quick list's dialog) | `TodayBox.tsx` → `Today` `onOpenList` → `openTaskCard`; TaskDetails routes the list to `QuickListDetail` |
| Today schedule entries of kind task, Calendar task entries | `Today.tsx:156`, `CalendarView.tsx:214/433` → `openCalendarEntry` `App.tsx:270` (sets `calendarDetail` directly) |
| Calendar and Task alerts pages (board, timeline, list rows; parent links) | `Workspace.tsx:401/442/457/481` → `App.tsx:2598` |
| Calendar entry details: parent, linked task, Edit | `CalendarDetails.tsx:286/385/406/509/528` → `App.tsx:3425/3446` |
| Tasks page row action "Schedule and linked notes" (calendar-clock icon) | `Structure.tsx:188` → `App.tsx:2623` `onTask` |
| Note → Linked work | `Notes.tsx:777` → `App.tsx:3516` → `openNoteTask` `:998` |
| `?record=task:<id>` link (Copy record link from TaskDetails), history restore of a task detail | `App.tsx:1005` `openLinkedRecord` |
| Notifications: primary Open on a task notice | `App.tsx:2659` (`noticeDestination` → `open: "task"`) |
| Quick list launcher ("+ Quick list", Tasks page only): always opens the new list. "Start a list" on Today opens no card; the new box takes focus | `App.tsx:2531` |
| Inline capture: only when the new task does not match the current filters | `App.tsx:873` `drainCaptures` |
| New task form saved | `App.tsx:3364` |
| Dani `ui_show` on `all` with `entity_id`; `form: task` with `entity_id`; a calendar entry of kind task | `App.tsx:1434`, `:1411`, `:1239` |
| Related tasks links inside TaskDetails | `TaskDetails.tsx` `onTask` → `openTaskCard` |

Sessions (`Sessions.tsx`) show the filed record as text only; no session opens either card.

## Inventory

"Shared" means both cards render the same component (from `TaskCardSections.tsx` unless noted) under
a label in `TASK_CARD_SECTIONS` (`task-card-sections.ts`). "Both" means each card has its own version.

| Section / control | RecordCard | TaskDetails |
|---|---|---|
| Header: kind, home path chip, save state, Close | Both. RC: type name, "Close record"; TD: "Task"/"Routine template", "Close task details" (focused on open) | |
| Title and description | Both. RC edits record `title`/`body` (always-on textareas); TD click-to-edit `title`/`notes` with Enter/Ctrl+Enter, Escape cancels | |
| Save conflicts | Both. RC "Compare saved version" (raw JSON) / Use saved / Reapply; TD per-field table / Use saved / Apply my change | |
| Source (provider, sync, Open original) | **Shared** `SourceDetails` ("Source") | |
| Eridani-only notes | **Shared label** "Local notes". RC saves through its own `record.update`; TD uses `SourceNotes` | |
| Copy record link, Previous record | **Shared** `RecordTools` ("Record link"). RC copies `record:<id>` (opens Organize), TD copies `task:<id>` (opens TaskDetails) | |
| Bug report (screenshot and status of a Report a bug task) | **Shared** `BugReportDetails` ("Bug report"); only for tasks tagged `bug-report`. RC reads the tags from the shell's loaded tasks | |
| remotea Run | **Shared** `TaskRun` → Remotea.tsx `RunTask` ("Agent run"). TD also gates on `remotea_enabled` | |
| Related tasks (parent, subtasks) | **Shared** `RelatedTasks`. RC: parent link only (Contents lists the subtasks); ported here | TD: parent and subtasks |
| Add subtask | **Shared** `AddSubtask`. RC: `record.create` of the child type | TD: `task.create` with `parent_task_id`; ported here |
| Linked notes, New linked note | **Shared** `LinkedNotes`; ported to RC here | |
| Reminders and time: list, Add reminder, Reserve time, scheduling help | **Shared** `TaskSchedule` ("Schedule"); ported to RC here | |
| Save as template | **Shared** `SaveTemplate`. TD loads the record's type on click (disabled until the task's record loads); ported to TD here | |
| Contents (child records, paging, progress), blockers notice | RC only | — (TD lists child *tasks* only) |
| Related records (relationships: search, add, remove) | RC only | — |
| Status | Schema statuses (`status_id`) | Fixed seven statuses; locked on routine templates |
| Due date / time / zone, Do date, Priority, Estimate | Both (RC from bound schema fields) | |
| Assigned to | Text field (binding `assignee`) | Actor picker |
| Custom schema fields, inherited values | RC only | — |
| Main home | `HomePicker` + move dialog | Button that opens the RecordCard in Organize |
| Deadline alert, Urgent | Both | |
| Review cadence | Both (`ReviewProps`) | |
| Linear sync section | — | TD only (`LinearTask`) |
| Complete / Reopen button | — (status select) | TD only |
| Archive / Restore | RC: archive asks about contents (`ContentsDialog`) | TD: task only |
| Open in Linear | Via Source "Open original" | Footer button + Source |
| Quick lists | Structure routes them to `QuickListDetail` | TaskDetails routes them to `QuickListDetail` |
| Escape | Bubble listener; ignores handled events; closes after saving | Capture listener; first Escape cancels an edit, next closes; now ignores Escape while a dialog inside the card (Save as template) is open |
| Backdrop click | Closes after saving | Same |
| Dani editor (`useEditor`) | kind `record`: title, body, local_notes, parent_id, status_id, values, archived | kind `task`: title, notes, status, priority, homes, parent, assignee, tags, dates, estimate, alerts |
| URL / deep link | `?record=record:<id>`; reloading on the Tasks page with it open lands in Organize | `?record=task:<id>` (with `view=tasks&tab=all`) |
| Mobile (≤760px) | Same `.detail-card` bottom sheet (`details.css:584`); `task-detail-card` has no rules of its own | |

### What this branch ported

- To RecordCard: Linked notes (list, New linked note), Reminders and time (list, Add reminder, Reserve
  time for this task), Related tasks (parent link). They use the shell's editors through
  `TaskCardHostContext` (provided in App.tsx): the card closes itself, then the note, reminder or
  time-block editor opens, as TaskDetails does.
- To TaskDetails: Add subtask, Save as template (+ its notice).
- Shared, not copied: Run, Related tasks, Add subtask, Linked notes, Schedule, Save as template; labels
  for Source, Local notes and Record link.
- TaskDetails now starts from the task already in the loaded list instead of a blank "Loading task…"
  state; the fetch still replaces it.

### Still different (not ported)

RecordCard lacks the Linear sync section, one-click Complete/Reopen, the actor picker for Assigned to,
routine-template labelling, focus on Close. TaskDetails lacks Related records, custom fields and
inherited values, Contents with paging and progress, blockers, the home picker and the archive-contents
dialog. Each needs data the other card does not load (TaskDetails has no schema; RecordCard has no
`Task` or `mutate`), so none is a cheap shared component.

## Quick lists on Today

Neither card shows a quick list itself: both route it to `QuickListDetail`, the full-list dialog. On
Today, a pinned list, or a dated one from its date on, is a box instead (`TodayBox.tsx`), built on the
same checklist (`QuickListBody` and `useQuickList` in `QuickLists.tsx`) without the dialog. Boxes come
from `GET /api/v1/today/boxes` and sit after Due and overdue.

- Pins belong to the person (`POST /api/v1/today/pins`), so a viewer can pin too. The box menu and the
  dialog's "Pin to Today" set the same pin, which no longer sets a do date. A pin changed by Dani or
  another device arrives as a `today.changed` event, which reloads the boxes.
- Checking the last open item finishes the list on any surface, and its box leaves Today. When a box
  or a task row (Today, Task alerts, Calendar, the Tasks page) finishes it, App shows "Groceries is
  done." with Undo (`list-finish.tsx`). The toast stays six seconds, longer while Undo has focus, and
  survives a page change; Undo takes focus when the finished box held it. The dialog shows no toast:
  the list stays open there, so unchecking the item is the undo.
- Completing a list that still has unchecked items is refused with `LIST_HAS_OPEN_ITEMS`. From any row
  or the Tasks page, App asks "2 items aren't checked. Finish the whole list?"; Finish list sends
  `task.complete` with `complete_open_items`, and Undo reopens the list and those items. The box asks
  the same question inside itself.
- Due and overdue, and the Tasks Today tab its "See all" opens, also list a quick-list item that has
  its own due or do date while its list is open. Such an item opens as an ordinary task. Inbox skips
  lists that have a box.
- A list holds up to 100 items; removed items and checked items already archived don't count.

## Projects on Today

A project can be pinned to Today too, on the same pins (`kind: "project"`, keyed on the project's home
record). "Pin to Today" sits in the project's header in Organize (`OrganizationBrowse.tsx`, which reads
`GET /api/v1/today/pins`); a viewer can pin. Its box (`ProjectBox` in `TodayBox.tsx`) lists the open work
under the project that is due or planned for today or earlier, by the same rule as Due and overdue, so
undated work stays out. It shows up to 50 tasks and an "N more in <project>" link, and its rows are the
ordinary Today task rows. The add field files a task under the project, planned for today. The title and
the menu's "Open project" open the project in Organize; the menu also unpins. Quick lists and projects
share one pin order on Today. A bot key needs `organization:read` to pin a project or to see project
boxes.

## Drift guard

`apps/web/src/task-card-parity.test.tsx` renders both cards for one task (a parent, a subtask, a
reminder, a Linear source) with `renderToStaticMarkup` and fails if either card lacks an aria-label
in `TASK_CARD_SECTIONS`. It also checks that the Run stand-in's label is RunTask's real one, and that
neither card spells a shared label itself. To add a shared section: add its label to
`TASK_CARD_SECTIONS`, render it from a shared component in both cards, and extend the fixture if it
only shows for some tasks.

## Recommendation

Rule (b): the RecordCard quick view everywhere, TaskDetails only when the task itself is opened as a
destination. I read "from its own page" as "from a link that names the task", which is the one place
the task-row editor is the point. Confirm that reading before routing changes.

Exact routing rule for (b):

1. `openTaskCard(task)` opens the RecordCard for the task's record (`/structure/by-core/task/<id>`),
   over the current page. Every row in "Opens TaskDetails" above goes through it, so they all switch at
   once: Today, Calendar, Task alerts, calendar entry details, notes, notices, quick capture, new task
   form, Dani `ui_show`/`form`/calendar.
2. TaskDetails opens only for `?record=task:<id>` (old copied links, history restore of a `task`
   detail) and from a new "Open full task" button in the RecordCard header.
3. RecordCard's Related tasks and Contents links stay in the RecordCard.
4. The Tasks row action "Schedule and linked notes" goes away (the RecordCard now has both).

What (b) needs first:

- A shell-level RecordCard host. RecordCard is only mounted inside `StructureWorkspace`, and needs the
  schema (`/structure`), choices and an `onOpen`. App.tsx needs its own host (like `calendarDetail`)
  that loads the schema once and renders the card over Today and Calendar.
- Dani: with a RecordCard open, the open editor is kind `record`, so Dani patches `values`/`status_id`
  instead of `status`/`due_date`. Check `ui_contracts.EDITOR_KINDS` callers and the Dani prompt text
  that assumes a `task` editor after `ui_show`.
- RecordCard should gain the TaskDetails-only controls people use from Today and Calendar: Complete /
  Reopen, the Linear section (needs the `Task` and `mutate`; the host context can lend them), and the
  actor picker for Assigned to.
- e2e: `google.mjs` (Close task details, Reserve time from Calendar), `batch-b.mjs` (native task card
  notes), `shell-navigation.mjs` and `custom-planner.mjs` (dialog "Task details": the RecordCard has the
  same name, but the Close button is "Close record").

Retiring TaskDetails outright (a) costs all of (b) plus:

- `?record=task:<id>` links must resolve to the record (map through `by-core`) so old links keep
  working; the URL sync and history restore lose the `task` detail kind.
- Editor kind `task` goes away for details: `site-actions.ts` `editorKinds` / `ui_contracts.EDITOR_KINDS`
  (guarded by `test_editor_kinds_match_the_browser`) still need it for QuickLists and the task form.
- The per-field conflict table, click-to-edit with Escape-to-cancel, and Close focus would be lost or
  rebuilt in RecordCard.
- About 570 lines go, and the parity test becomes a single-card section test.

Until routing changes, keep both cards and add any new task-card section through `TaskCardSections.tsx`
and `TASK_CARD_SECTIONS`; the parity test enforces it.
