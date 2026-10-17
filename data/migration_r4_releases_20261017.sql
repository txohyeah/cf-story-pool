-- 增量迁移 2026-10-17：R4 releases 版本发布单（CR-V 承载）
CREATE TABLE IF NOT EXISTS releases (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  version TEXT NOT NULL,
  change_scope TEXT NOT NULL DEFAULT '',
  retest_scope TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'planning' CHECK (status IN ('planning','testing','reverify','published','closed')),
  published_by INTEGER REFERENCES users(id),
  published_at TEXT,
  confirmor_id INTEGER REFERENCES users(id),
  confirmor_at TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
ALTER TABLE requirements ADD COLUMN release_id INTEGER REFERENCES releases(id);
CREATE INDEX IF NOT EXISTS idx_rel_project ON releases(project_id);
CREATE INDEX IF NOT EXISTS idx_req_release ON requirements(release_id);
