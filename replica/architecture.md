# Architecture: Corvi (a local rebuild of Codex's core features)

## Stack

| layer | choice | why |
| --- | --- | --- |
| desktop shell | Swift + WebKit | Native macOS window with a polished HTML/CSS UI and no browser chrome. |
| web UI | Local HTML/CSS/JavaScript | Keeps the current UI dependency-light and easy to iterate. |
| backend | Python 3.15 standard-library HTTP server | Reuses Corvi's existing Ollama, council, tools, and permission code. |
| database | SQLite in `.corvi/corvi.db` | Local-first persistence without a remote service. |
| ORM | Python `sqlite3` data layer | Small schema and no extra dependency. |
| auth | None for local mode | The user owns the machine and workspace. |
| model provider | Ollama on `localhost:11434` | Keeps models on the HDD and supports automatic model selection. |
| files | Local project folders | Corvi operates only on the selected workspace. |
| jobs | Python background threads with persisted run state | Supports council work, model warmup, and long-running tasks. |
| hosting | macOS `.app` bundle | Personal desktop deployment; no hosted clone. |

No payments, email, or cloud hosting are part of this local target. No microservices.

## Schema

Tables: 8. Access rules: data-layer checks plus workspace path validation.

See [schema.sql](schema.sql). The schema stores task metadata and activity, not model weights or secrets.

## API

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| GET `/` | Serve the desktop UI | local app | none | HTML | F01 |
| GET `/api/models` | List installed Ollama models | local app | none | model IDs and availability | F01 |
| POST `/api/chat` | Run a normal Corvi turn | local app | prompt, model, workspace, tools | streamed/final assistant response | F01 |
| POST `/api/council` | Consult configured local models | local app | prompt, model set | panel answers and synthesis | F01 |
| GET `/api/tasks` | List recent and pinned tasks | local app | workspace, filter | task rows | F02 |
| POST `/api/tasks` | Create a task | local app | title, prompt, workspace | task record | F01 |
| GET `/api/tasks/:id` | Load a task transcript | local app | task ID | messages and activity | F02 |
| POST `/api/tasks/:id/messages` | Continue a task | local app | prompt | message and run ID | F01 |
| POST `/api/tasks/:id/pin` | Pin or unpin a task | local app | pinned boolean | updated task | F02 |
| GET `/api/runs/:id` | Read agent activity | local app | run ID | status and activity items | F03 |
| POST `/api/approvals/:id` | Approve or deny an action | local app | decision, feedback | updated approval | F03 |
| GET `/api/artifacts` | List outputs and sources | local app | task ID | artifact rows | F04 |
| GET `/api/pets` | List local pets and states | local app | none | pet metadata | F05 |
| POST `/api/pets/:id/state` | Update pet visibility/state | local app | state, position, size | updated pet | F05 |

Webhooks in: none. Webhooks out: none.

Jobs:

- `model_warmup`: start Ollama and refresh model availability at app launch.
- `task_runner`: execute a model/tool turn and persist activity.
- `council_runner`: run sequential HDD-friendly model consultation and synthesis.
- `session_cleanup`: mark abandoned runs blocked after restart.

## The parts that bite

- model lifecycle: HDD-backed models must be loaded sequentially, unloaded after council turns, and retried after transient EOF failures.
- streaming: UI updates must be serialized so background council/activity messages do not corrupt the composer.
- approvals: every write/edit/command needs a durable pending approval and safe retry path.
- workspace safety: normalize paths and reject access outside the selected workspace unless explicitly allowed.
- races: only one writer should mutate a task transcript at a time; use SQLite transactions and a per-task lock.
- crash recovery: a run left in `running` must become `blocked` or `interrupted` on next launch.
- pet state: activity states must be driven by persisted run status, with a still frame for reduced motion.
- file conflicts: re-read before edits and show a diff when the target changed since approval.

## Build order

1. Vertical slice: S01 → S02 with SQLite `workspaces`, `tasks`, `messages`, and `agent_runs`; routes `/`, `/api/models`, `/api/tasks`, and `/api/chat`.
2. Must-haves: persistence, project selection, model selection, streaming, activity cards, approvals, terminal output, and workspace-safe file tools.
3. Should-haves: council mode, outputs/sources, pinned tasks, pet overlay, pet state mapping, MCP and plugin management.
4. Could-haves: search, archive, custom pet picker, reduced-motion settings, and richer artifact previews.
5. Run `/replica-skill:replica-test` after the vertical slice, then `/replica-skill:replica-design` for token/component refinement.
