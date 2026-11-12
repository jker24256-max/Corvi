# Corvi build log

| screen | date | status | notes |
| --- | --- | --- | --- |
| S01 Home / new task | 2026-11-12 | partial | Greeting composer, model selector, council toggle, and local server are implemented. |
| S02 Task workspace | 2026-11-12 | partial | Chat response path works; SQLite now persists tasks and messages. Activity cards and approvals remain. |
| S03 Recent tasks | 2026-11-12 | partial | Recent-task API exists; sidebar task rendering still needs wiring. |
| S04 Pinned tasks | 2026-11-12 | not started | Schema supports pinning; UI action remains. |
| S05 Project view | 2026-11-12 | partial | Current workspace path is available; project picker remains limited. |
| S06 Agent activity | 2026-11-12 | not started | Existing terminal activity is not yet represented in the desktop UI. |
| S07 Approval view | 2026-11-12 | partial | Existing Corvi permission engine remains available; desktop approval cards remain. |
| S08 Output/source panel | 2026-11-12 | partial | Panel shell exists; artifact persistence and previews remain. |
| S06 Agent activity | 2026-11-12 | partial | Added persisted agent runs and activity items; WebKit now renders started/completed/failed status cards. Detailed tool cards and terminal output remain. |
| S07 Approval view | 2026-11-12 | partial | Added a review panel and approval decision API backed by the local store. Real tool-generated approvals and file diff content still need wiring. |
| S07 Approval view | 2026-11-12 | partial | Connected coding tool calls to persisted approval records, added unified previews for edit/write requests, and wired approve/deny actions. Approved execution and retry remain. |
| S07 Approval view | 2026-11-12 | partial | Approved edits and commands now execute through Corvi's tool functions, results are persisted as activity/tool messages, denial blocks the run, and retry creates a new approval. |
| S05 Project view | 2026-11-12 | partial | Added workspace read/select endpoints and a folder-path chooser hook, plus permissions settings read/update UI for edit, write, and command policies. Progressive WebKit streaming remains. |
| S02 Task workspace | 2026-11-12 | partial | Added newline-delimited WebKit streaming, live token rendering, cancel-on-send behavior, interrupted run persistence, and streamed error handling. Council/tool-call streaming remains separate. |
| S06 Agent activity | 2026-11-12 | partial | Replaced plain activity lines with expandable cards carrying tool arguments, command/edit results, statuses, and failure details. Live terminal chunks and specialized test cards remain. |
| S01/S05/S08 GUI shell | 2026-11-12 | partial | Added active workspace switching in the local API, native directory-picker hook with fallback, artifact-backed Outputs data, and mascot reactions for run states. Full native path bridging and sprite pose mapping remain. |
| S05/S08 GUI shell | 2026-11-12 | partial | Added a real macOS NSOpenPanel bridge, workspace rebinding, research-to-source artifact storage, and source/output panel data endpoints. Source rendering and per-state sprite sheets remain. |
| S01/S05/S08 GUI shell | 2026-11-12 | partial | Rendered Outputs and Sources entries, added persistent pet hide/reduced-motion behavior and distinct state positions, and completed native folder selection wiring. Final sprite artwork and richer artifact actions remain. |
| QA GUI flow | 2026-11-12 | done | Full local GUI API checks pass, including review execution/retry, task restoration, Outputs/Sources artifacts, permissions, workspace APIs, pet asset, and native Swift syntax. Fixed query-string routing for task panels. |
| S09 Integrations | 2026-11-12 | partial | Added MCP server/tool discovery, safe enable/disable endpoints, reload action, and local skill/plugin inventory for the GUI. Dedicated integration screen remains. |
| S06/S07 Activity and review | 2026-11-12 | partial | Added live command NDJSON output with exit codes and summaries, current-file diff comparison, and expanded read/edit/command/test activity coverage. Full permissions form remains. |
| S05/S07 Workspace and settings | 2026-11-12 | partial | Workspace changes now reset the active task and reload the new workspace list; permissions now cover edit, write, bash, and MCP policies through the settings flow. Dedicated visual settings styling remains. |
| S05/S07 Workspace and settings | 2026-11-12 | done | Added saved-workspace switcher, full active-workspace rebinding, native folder reset behavior, and a dedicated in-app permissions form for edit/write/bash/MCP policies. |
| S03/S04 Navigation polish | 2026-11-12 | partial | Added task search, rename, archive, pin actions, and local task update APIs. A dedicated pinned section remains. |
| S08/S09 Optional polish | 2026-11-12 | partial | Added integrations inventory panel, pet settings entry point, richer source/output refresh behavior, and persisted pet customization hooks. |
| Desktop packaging | 2026-11-12 | done | Wired the sidebar Integrations action to the visual panel and rebuilt Corvi.app with the latest WebKit UI, Python server, mascot asset, and native macOS shell. |
| S09 Settings | 2026-11-12 | partial | Model/council controls exist; full settings screen remains. |
| S10 Pet overlay | 2026-11-12 | partial | Crow sprite is displayed; state-driven animation and picker remain. |

Next build target: wire recent tasks into the sidebar, then implement activity and approval cards.

## Test pass — 2026-11-12

The local HTTP smoke suite passed the app shell, model endpoint, recent-task endpoint, and crow asset endpoint. The existing four compatibility tests also passed. Manual browser/WebKit checks remain for keyboard focus, native clicks, activity cards, and approval flows.
2026-11-12 — Core workflow vertical slice — partial — Wired the WebKit app to render recent SQLite tasks, restore saved conversations, retain task IDs across sends, show running/completed/error activity, and remove the misleading HDD setup title. Approval/diff surfaces and incremental WebKit streaming remain.
