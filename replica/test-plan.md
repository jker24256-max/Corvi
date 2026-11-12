# Corvi test plan

## F01 — Start a local coding task

- F01-H1: Open the app, enter a prompt, submit once. Expect a user message, assistant result, and persisted task.
- F01-E1: Submit empty input. Expect no request and no empty task.
- F01-E2: Submit a long prompt with emoji and accents. Expect preserved UTF-8 text.
- F01-E3: Double-click send. Expect one task/message, not duplicates.
- F01-E4: Start with Ollama offline. Expect a clear unavailable state, not a raw traceback.
- F01-E5: Refresh while the model is loading. Expect the app shell to remain usable.
- F01-E6: Use keyboard-only Enter and Shift+Enter. Expect send/newline behavior.

## F02 — Resume a previous task

- F02-H1: Query recent tasks after creating one. Expect the task ordered by update time.
- F02-E1: Query an empty workspace. Expect an empty list, not an error.
- F02-E2: Load a missing task ID. Expect a safe empty/error response.
- F02-E3: Restart the server and query again. Expect persisted task metadata.

## F03 — Review and approve a file edit

- F03-H1: Request an edit through the terminal engine. Expect an approval before mutation.
- F03-N1: Deny the edit. Expect no file mutation.
- F03-E1: Modify the file between read and approval. Expect a conflict/re-read path.
- F03-H2: Seed an edit approval, load the review endpoint, and inspect the returned diff. Expect a unified diff and pending decision.
- F03-N2: Deny the seeded approval with feedback. Expect the decision and feedback to persist without changing a file.

## F04 — Inspect outputs and sources

- F04-H1: Open the outputs/source panel. Expect an empty-state panel when no artifacts exist.
- F04-E1: Open a missing artifact. Expect a recoverable error.

## F05 — Follow work with the pet

- F05-H1: Open the app and observe the crow pet. Expect a visible idle pose.
- F05-E1: Click the pet. Expect a status response without affecting the task.
- F05-E2: Hide/reduce motion. Expect no animation-dependent functionality to break.
- F06-H1: Select a saved task and load Outputs/Sources. Expect stored artifacts to appear and messages/activity to restore.
- F06-E1: Request a task-specific panels URL with a query string. Expect a 200 response rather than a route miss.
- F07-H1: Load integrations. Expect MCP, skills, and plugins collections.
- F07-E1: Reload integrations. Expect a successful reload response.
- F07-N1: Toggle an unknown MCP server. Expect rejection without mutating integration state.
- F07-N2: Load malformed MCP configuration. Expect an empty safe inventory, not a crash.
- F08-H1: Rename, pin, search, and archive a task. Expect each state change to persist and archived tasks to disappear from recent results.
