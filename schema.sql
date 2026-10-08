-- cf-story-pool 需求池 schema（D1 = cf-story-pool-db）
-- 用户/会话/限速照抄 zhixidao；业务表见 PRD v0.1

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_throttle (
  ip TEXT PRIMARY KEY,
  fail_count INTEGER NOT NULL DEFAULT 0,
  window_start TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS requirements (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL DEFAULT 'req' CHECK (type IN ('bug','req','opt')),
  urgency TEXT NOT NULL DEFAULT 'normal' CHECK (urgency IN ('normal','urgent')),
  status TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted','confirmed','scheduled','fixed','verified','closed','dup_closed')),
  channel TEXT NOT NULL DEFAULT 'web' CHECK (channel IN ('web','agent','migrate')),
  duplicate_of INTEGER REFERENCES requirements(id),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS requirement_tags (
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  tag_id INTEGER NOT NULL REFERENCES tags(id),
  PRIMARY KEY (req_id, tag_id)
);

CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY,
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  store_key TEXT NOT NULL UNIQUE,       -- 指向 attachment_blobs.token（R2 预留：改为 R2 key）
  orig_name TEXT,
  size INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attachment_blobs (
  token TEXT PRIMARY KEY,               -- uuid，上传时生成；api/files/<token> 门禁内读取
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  data BLOB NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checklist_items (
  id INTEGER PRIMARY KEY,
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  content TEXT NOT NULL,
  assignee_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','doing','done')),
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  actor_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- FTS5 全文索引（外部内容表 + 触发器同步；触发器必须单行书写，cf_d1.py 按 ';\n' 切分）
CREATE VIRTUAL TABLE IF NOT EXISTS requirements_fts USING fts5(title, description, content='requirements', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS requirements_fts_ai AFTER INSERT ON requirements BEGIN INSERT INTO requirements_fts(rowid, title, description) VALUES (new.id, new.title, new.description); END;
CREATE TRIGGER IF NOT EXISTS requirements_fts_ad AFTER DELETE ON requirements BEGIN INSERT INTO requirements_fts(requirements_fts, rowid, title, description) VALUES ('delete', old.id, old.title, old.description); END;
CREATE TRIGGER IF NOT EXISTS requirements_fts_au AFTER UPDATE ON requirements BEGIN INSERT INTO requirements_fts(requirements_fts, rowid, title, description) VALUES ('delete', old.id, old.title, old.description); INSERT INTO requirements_fts(rowid, title, description) VALUES (new.id, new.title, new.description); END;

CREATE INDEX IF NOT EXISTS idx_req_status ON requirements(status);
CREATE INDEX IF NOT EXISTS idx_req_project ON requirements(project_id);
CREATE INDEX IF NOT EXISTS idx_req_updated ON requirements(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_rtag_req ON requirement_tags(req_id);
CREATE INDEX IF NOT EXISTS idx_rtag_tag ON requirement_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_att_req ON attachments(req_id);
CREATE INDEX IF NOT EXISTS idx_chk_req ON checklist_items(req_id);CREATE INDEX IF NOT EXISTS idx_chk_assignee ON checklist_items(assignee_id);
CREATE INDEX IF NOT EXISTS idx_evt_req ON events(req_id);
