-- 增量迁移 2026-10-17：文档页（v2 P0 第一项）
-- docs / doc_versions / doc_comments 三表；评论独立于 events（events 绑 req_id，文档评论绑 doc_id + 版本号）

CREATE TABLE IF NOT EXISTS docs (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  title TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','approved')),
  approved_by INTEGER REFERENCES users(id),
  approved_at TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS doc_versions (
  id INTEGER PRIMARY KEY,
  doc_id INTEGER NOT NULL REFERENCES docs(id),
  version INTEGER NOT NULL,
  content_md TEXT NOT NULL,
  change_summary TEXT NOT NULL DEFAULT '',
  author_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (doc_id, version)
);

CREATE TABLE IF NOT EXISTS doc_comments (
  id INTEGER PRIMARY KEY,
  doc_id INTEGER NOT NULL REFERENCES docs(id),
  doc_version INTEGER NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_docs_project ON docs(project_id);
CREATE INDEX IF NOT EXISTS idx_docs_status ON docs(status);
CREATE INDEX IF NOT EXISTS idx_docver_doc ON doc_versions(doc_id);
CREATE INDEX IF NOT EXISTS idx_doccm_doc ON doc_comments(doc_id);
