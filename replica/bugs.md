# Corvi bug report

## Reproduced bugs

None currently open in the automated local checks. The test pass covers navigation actions, MCP discovery/reload/unknown-server rejection, invalid config handling, review execution/retries, artifact panels, and task restoration. It also fixed a task-search route collision.

## To check manually

- S3: WebKit command/tool execution still uses the review API as a completed-action path rather than a live command-output stream.
- S3: Source entries are stored and returned, but the right-panel source presentation remains basic text.
- S3: Sprite state positions are wired, but the current sheet may not contain visually distinct artwork for every state.
- S4: Native WebKit visual focus and screen-reader behavior still need a click-through pass.
