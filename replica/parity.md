# Corvi parity report

Generated from `replica/features.csv` using the replica-diff parity checker.

## Score

- Overall feature parity: **90.4 / 100**
- Must-have features complete: **14 of 14**
- Layout parity: **Not scored** — no reference or clone screenshots are stored in `replica/screens/` and `replica/clone-screens/`.
- Verdict: **Feature must-haves complete**. Visual polish and optional features remain.

The matrix now reflects the current implementation rather than treating already-working model features as missing. Models score 100%: automatic selection, manual selection, and council mode are represented in the current build. Recent-task rendering, task selection, conversation restoration, local session persistence, and persisted run activity are now wired. The remaining score is limited mainly by missing review surfaces and incomplete WebKit streaming.

## Behavior differences

The GUI test pass verified the review flow, task restoration, artifact panels, permissions, workspace API, and pet asset. The task-specific panels route was fixed after testing and now handles query parameters correctly.

The integration QA pass also verified MCP inventory/reload behavior, malformed configuration safety, unknown-server rejection, and local skills/plugins inventory.

The latest build adds live command output events with exit codes and summaries, current-file post-edit comparison, and complete persisted activity details for reads, edits, commands, and tests.

1. Activity is now represented as expandable first-class cards with tool arguments, results, and statuses. Blocked/needs-input states are persisted, while live terminal chunks and specialized test cards remain.
2. The local SQLite store and API persist tasks and messages, and the desktop sidebar now renders recent tasks and restores selected conversations.
3. Folder selection exists in the Tk front end, while the WebKit desktop flow still lacks a complete workspace/project picker.
4. WebKit consumes newline-delimited Ollama events and appends tokens live; cancellation records an interrupted run. Council and tool-call streaming remain separate paths.
5. The crow asset now has distinct state positions, persistent hide behavior, reduced-motion handling, and a customization entry point. Outputs/Sources refresh from stored artifacts, while richer artifact rendering remains optional polish.
6. Coding tool calls now create persisted approval records, expose unified previews, execute after approval, record results, block after denial, and support retry. Permission settings and workspace selection now have local API/UI hooks; outputs and sources remain incomplete.

## Missing features in build order

### 1. Activity and execution transparency

Implement a shared event stream for model status, terminal output, tool calls, reads, edits, commands, and research. Render these as stable activity cards without mixing them into assistant text.

### 2. Workspace and task navigation

Wire the recent-task sidebar to the SQLite API, restore conversations on selection, add task rename/archive/search, and add a WebKit workspace/project picker.

### 3. Connect the review and safety workflow

Connect the existing permission engine to approval records, populate the review panel for edits and commands, add a file-diff viewer, permissions settings, and reject/retry with user feedback.

### 4. WebKit streaming

Expose incremental response events to the WebKit client so long coding tasks render progressively instead of appearing only after completion.

### 5. Outputs, sources, and pet state

Populate Outputs and Sources panels, then map execution states to the crow's poses and add persistent show/hide and reduced-motion controls.

## Next step

Proceed with `/replica-build`, starting with the activity event stream and approval/diff surfaces. Re-run `/replica-diff` after those features are wired and capture reference/clone screenshots so layout parity can be measured.
