# Batch C — Quick lists and guided setup

Implemented October 3, 2026 on `codex/batch-c-capture-setup`, based on `cfc9c6e`
(the Batch B / PR #23 merge). This report records local synthetic verification,
not deployment, model-quality acceptance or a real-device test.

## What changed

- Quick lists reuse Task rows: one parent list, stable child Task IDs, optional
  sections and a deadline. Ordinary Tasks/Today views show the parent; search can
  still find children. Due and overdue, and the Tasks Today tab its "See all"
  opens, also list an item with its own due or do date while its list is open.
  Completion, add/edit and reorder are inline. Alerts default off; a missed
  deadline never discards work.
- Today shows each pinned list as a box after Due and overdue: its open items, an
  add field, and the checked items folded into "N done". "Start a list" on Today
  makes a list that is pinned at once. A new list is pinned unless it gets a date;
  a dated list shows as a box from that date until it is finished, pinned or not.
  A list with a box is not also an Inbox row. If it has its own date it still
  shows in Due and overdue, which keeps listing every open task due or planned by
  today.
- Pins belong to the person: pinning changes only your own Today, and viewers in a
  shared workspace can pin but not edit. A pin lasts until it is removed, is never
  shown as overdue, and pinning or unpinning never changes the list or its items.
  "Pin to Today" in the list and in the box menu no longer sets a do date. Lists
  pinned the old way became pins for the workspace owner once, with the date
  cleared.
- Checking the last open item finishes the list, wherever it is checked, and its
  box leaves Today while keeping the pin. When a box or a task row finishes it, a
  toast says "Groceries is done." with Undo for six seconds, longer while Undo has
  focus, and it stays when you change pages. Undo unchecks that item; adding or
  unchecking an item reopens a finished list, so its box comes back. Finishing a
  list that still has unchecked items asks first ("2 items aren't checked. Finish
  the whole list?"), then completes the list and those items together, and Undo
  reopens all of them. Dani asks you the same question before doing it.
- A list holds up to 100 items. Removed items and checked items that were already
  archived don't count, so a long-running list such as groceries keeps accepting
  new items. Reorder takes exactly the items that count; archived ones keep their
  saved order after them.
- Promotion turns that same parent and its children into ordinary tasks/subtasks,
  optionally assigned to an existing project. It does not clone work or create a
  second project engine. Create a new project through the existing project tools.
- Capture/edit/promotion use the existing command transaction, revisions,
  idempotency, action history, Revert, owner lock, permissions and search observation.
  New typed tools load through the existing tool catalog. API/MCP bot access requires
  task scopes; revoked keys and shared viewers cannot mutate.
- Setup is account-scoped progress in OwnerSettings: name, timezone, purpose,
  optional custom grouping with a meaningful description/example, skip and resume.
  Preview and apply are separate commands using existing schema confirmation and
  stale-proposal guards. It creates no sample tasks. Current profile preferences
  remain authoritative when setup is resumed. Shared members configure their own
  Personal account, not the shared owner's profile.
- Setup exposes text/voice tools to Eri and reuses field-understanding/clarification
  and schema tools. The form offers a simple optional group; more elaborate schema
  design remains in Organization and conversational schema preview/apply.
- Explicitly confirmed filing rules work without waiting for automatic field
  assessment. Automatic rules retain understood-field and held-out quality gates,
  explicit assignments still win, and conflicting rules abstain. Rules show their
  destination, reason and evidence, with edit/confirm/pause/forget controls. Editing
  a pending rule resolves its weekly interview question. Nothing writes personal memory.
- Login/invitation/setup copy distinguishes owned personal records from a selected
  shared membership. Install the v19 peeling-note mark as SVG, monochrome SVG and
  PNG PWA icons; see [Brand](BRAND.md). Orbit styling is retained.

## Evidence

All commands used synthetic local data and empty application environment settings.
No paid model inference, connected-provider writes or production mutations ran.

| Check | Result |
| --- | --- |
| Full backend `pytest -q --tb=short` on PostgreSQL 16.15 | 836 passed, 1 skipped |
| Eval harness `python -m pytest -q evals --tb=short` | 82 passed, 2 skipped |
| Frontend `npm test -- --run` | 175 passed, 1 skipped |
| Frontend TypeScript/Vite build | Passed; existing large-chunk advisory remains |
| All browser acceptance fixtures | Eight suites passed; Batch C rerun after final UI polish |
| Python correctness lint and `git diff --check` | Passed |
| Migration 0019 → 0020 → 0019 → 0020 and model agreement | Passed in disposable database |

`tests/test_batch_c.py` covers atomic/idempotent capture, item IDs, stale revisions,
invalid reorder, promotion/history, foreign records, deadline retention, list cap,
setup isolation/skip/resume, explanation and separate confirmation, changed-answer
invalidation, timezone validation, current profile preferences, explicit versus
learned routing, edited-rule history/memory separation, shared roles and bot scopes.

The new browser fixture uses the real local API with synthetic authentication:
start the Houston list on Today (its box appears, with no dialog and no Inbox row)
→ check off every item of a second list (its box leaves; Undo brings it back) → a
pin changed outside the page shows or hides a box without a reload → finish a dated
list from its Due row (asked first; Cancel changes nothing; Undo reopens the list
and its items) → open the full Houston list → complete Hayes item → add/reorder →
backend edit while open → close/reopen → one summary → promotion with original IDs.
It also exercises setup answers, preview-before-apply, confirmation, persisted
completion and 390/892px layouts. Existing browser fixtures cover navigation, chat, notes, semantic search,
usage, Batch B source UI and custom planner workflows. Screenshots are local
artifacts; they do not substitute for physical Pixel Fold acceptance.

The catalog now contains **1,051 scenarios across 42 features**. Quick capture and
onboarding each add 25 scenarios. Twelve exact deterministic scenarios are fully
bound, raising the ratchet from 100 to **112**; component coverage stays **224**.
The other new cases retain incomplete/unrun acceptance status. Historical reports
and original outcomes remain unchanged. Existing calendar eval seed fingerprints
ignore new capture metadata only at its defaults, preserving old frozen seeds;
non-default capture state remains in snapshots/fingerprints.

## Migration and rollback

Migration `0020_capture_setup` adds `is_quick_list`, `quick_section` and `quick_order`
to Task with defaults that preserve ordinary tasks. Setup progress uses existing
JSON settings; no provider data or existing task rows are rewritten.

Upgrade the database before running the new app. Downgrading removes capture
metadata, so lists become ordinary parent/subtasks and section/order information
is lost; task rows/IDs remain. Back up before any production downgrade. Retaining
0020 while rolling back app code is preferable for preserving that metadata, but
an older app will display checklist children as normal tasks.

## Still requires acceptance

- Real Eri text/Live conversations: incomplete capture, follow-up edits, suggested
  supplies versus actual commitments, setup clarifications and weekly rule interview.
- A fresh invited person completes or skips/resumes setup without developer help.
- Physical phone/fold keyboard, scrolling, screen reader/focus and installed PWA icon.
- Batch A/B connected-provider, notifications, operations and voice checks in TODO.
- Release-core model reruns, latency measurement and the seven-day pilot remain Batch D.

A merge or green CI alone does not close these acceptance items.
