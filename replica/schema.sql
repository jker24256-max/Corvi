-- Corvi local-first schema. SQLite stores timestamps as ISO-8601 UTC text.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL DEFAULT 'local' CHECK (provider IN ('local','cloud')),
  permissions_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','running','needs_input','blocked','error','archived')),
  pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0,1)),
  selected_model TEXT NOT NULL DEFAULT 'auto',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_workspace_updated ON tasks(workspace_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS tasks_workspace_pinned ON tasks(workspace_id, pinned, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
  content TEXT NOT NULL,
  model TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_task_created ON messages(task_id, created_at);

CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','ready','needs_input','blocked','error','interrupted')),
  model TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS agent_runs_task_started ON agent_runs(task_id, started_at DESC);

CREATE TABLE IF NOT EXISTS activity_items (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('read','edit','command','browser','research','message','status')),
  title TEXT NOT NULL,
  detail TEXT,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed','waiting')),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS activity_run_created ON activity_items(run_id, created_at);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  action_type TEXT NOT NULL CHECK (action_type IN ('write_file','edit_file','run_bash','external')),
  target TEXT NOT NULL,
  summary TEXT NOT NULL,
  decision TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','approved','denied')),
  feedback TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS approvals_run_decision ON approvals(run_id, decision);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('file','source','report','diff','terminal')),
  title TEXT NOT NULL,
  path_or_url TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifacts_task_created ON artifacts(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS pets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  sprite_sheet TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'idle' CHECK (state IN ('idle','thinking','coding','waiting','ready','blocked','sleeping')),
  visible INTEGER NOT NULL DEFAULT 1 CHECK (visible IN (0,1)),
  size INTEGER NOT NULL DEFAULT 120,
  position_json TEXT NOT NULL DEFAULT '{"right":24,"bottom":20}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
