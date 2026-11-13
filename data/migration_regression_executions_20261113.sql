-- P1-A: rebuild tc_executions; legacy rows keep NULL run/item/project/baseline.
BEGIN;
CREATE TABLE tc_executions_new (
  id INTEGER PRIMARY KEY,
  tc_id INTEGER NOT NULL REFERENCES test_cases(id),
  release_id INTEGER NOT NULL REFERENCES releases(id),
  result TEXT NOT NULL DEFAULT '' CHECK (result IN ('','pass','fail','deviation','diff')),
  conclusion TEXT NOT NULL DEFAULT '', dev_ref TEXT NOT NULL DEFAULT '', ev_ref TEXT NOT NULL DEFAULT '',
  executed_by INTEGER REFERENCES users(id),
  executed_at TEXT NOT NULL DEFAULT (datetime('now')), tc_version INTEGER,
  project_id INTEGER REFERENCES projects(id), run_id INTEGER, baseline_id INTEGER, baseline_item_id INTEGER,
  diff_reason TEXT NOT NULL DEFAULT '', diff_signed_by INTEGER REFERENCES users(id), diff_signed_at TEXT,
  diff_decision TEXT CHECK(diff_decision IS NULL OR diff_decision IN ('accept','reject')),
  UNIQUE (run_id, baseline_item_id), UNIQUE(project_id, id),
  CHECK ((project_id IS NULL AND run_id IS NULL AND baseline_id IS NULL AND baseline_item_id IS NULL)
      OR (project_id IS NOT NULL AND run_id IS NOT NULL AND baseline_id IS NOT NULL AND baseline_item_id IS NOT NULL AND tc_version IS NOT NULL)),
  FOREIGN KEY(project_id, run_id, baseline_id, release_id) REFERENCES test_runs(project_id, id, baseline_id, release_id),
  FOREIGN KEY(project_id, baseline_item_id, baseline_id, tc_id, tc_version) REFERENCES regression_baseline_items(project_id, id, baseline_id, tc_id, tc_version)
);
INSERT INTO tc_executions_new (id,tc_id,release_id,result,conclusion,dev_ref,ev_ref,executed_by,executed_at,tc_version,project_id,run_id,baseline_id,baseline_item_id)
SELECT id,tc_id,release_id,result,conclusion,dev_ref,ev_ref,executed_by,executed_at,tc_version,NULL,NULL,NULL,NULL FROM tc_executions;
DROP TABLE tc_executions;
ALTER TABLE tc_executions_new RENAME TO tc_executions;
CREATE INDEX idx_tce_tc ON tc_executions(tc_id);
CREATE INDEX idx_tce_rel ON tc_executions(release_id);
CREATE INDEX idx_reg_exec_run_result ON tc_executions(project_id, run_id, result);
CREATE UNIQUE INDEX ux_tce_legacy ON tc_executions(tc_id, release_id) WHERE run_id IS NULL;
COMMIT;
