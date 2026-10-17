-- 增量迁移 2026-10-17：R5+R6 用例库 test_cases + 执行记录 tc_executions
CREATE TABLE IF NOT EXISTS test_cases (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  tc_code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  steps_md TEXT NOT NULL DEFAULT '',
  related_req INTEGER REFERENCES requirements(id),
  covers_urs TEXT NOT NULL DEFAULT '',
  risk TEXT NOT NULL DEFAULT 'middle' CHECK (risk IN ('high','middle','low','external')),
  ctype TEXT NOT NULL DEFAULT 'positive' CHECK (ctype IN ('positive','negative','boundary')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
  current_version INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_case_versions (
  id INTEGER PRIMARY KEY,
  tc_id INTEGER NOT NULL REFERENCES test_cases(id),
  version INTEGER NOT NULL,
  steps_md TEXT NOT NULL,
  change_summary TEXT NOT NULL DEFAULT '',
  author_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (tc_id, version)
);

CREATE TABLE IF NOT EXISTS tc_executions (
  id INTEGER PRIMARY KEY,
  tc_id INTEGER NOT NULL REFERENCES test_cases(id),
  release_id INTEGER NOT NULL REFERENCES releases(id),
  result TEXT NOT NULL DEFAULT '' CHECK (result IN ('','pass','fail','deviation')),
  conclusion TEXT NOT NULL DEFAULT '',
  dev_ref TEXT NOT NULL DEFAULT '',
  ev_ref TEXT NOT NULL DEFAULT '',
  executed_by INTEGER REFERENCES users(id),
  executed_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (tc_id, release_id)
);

CREATE INDEX IF NOT EXISTS idx_tc_project ON test_cases(project_id);
CREATE INDEX IF NOT EXISTS idx_tc_req ON test_cases(related_req);
CREATE INDEX IF NOT EXISTS idx_tcv_tc ON test_case_versions(tc_id);
CREATE INDEX IF NOT EXISTS idx_tce_tc ON tc_executions(tc_id);
CREATE INDEX IF NOT EXISTS idx_tce_rel ON tc_executions(release_id);
