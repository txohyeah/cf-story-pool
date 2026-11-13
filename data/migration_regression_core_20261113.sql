-- P1-A: regression entities. Apply once, before the executions rebuild.
BEGIN;
CREATE UNIQUE INDEX ux_reg_tc_project_id ON test_cases(project_id, id);
CREATE UNIQUE INDEX ux_reg_release_project_id ON releases(project_id, id);

CREATE TABLE feature_points (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
  fp_code TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','pending','retired')),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, id), UNIQUE(project_id, fp_code)
);
CREATE TABLE tc_feature_points (
  project_id INTEGER NOT NULL REFERENCES projects(id), tc_id INTEGER NOT NULL, fp_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY(project_id, tc_id, fp_id),
  FOREIGN KEY(project_id, tc_id) REFERENCES test_cases(project_id, id),
  FOREIGN KEY(project_id, fp_id) REFERENCES feature_points(project_id, id)
);
CREATE INDEX idx_reg_tc_fp_reverse ON tc_feature_points(project_id, fp_id);
CREATE TABLE regression_baselines (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
  release_id INTEGER, baseline_code TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0),
  state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','approved','frozen')),
  data_manifest_json TEXT NOT NULL DEFAULT '{}', manifest_hash TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id), approved_by INTEGER REFERENCES users(id), approved_at TEXT,
  frozen_by INTEGER REFERENCES users(id), frozen_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, id), FOREIGN KEY(project_id, release_id) REFERENCES releases(project_id, id)
);
CREATE UNIQUE INDEX ux_reg_baseline_release ON regression_baselines(project_id, release_id, baseline_code, revision) WHERE release_id IS NOT NULL;
CREATE UNIQUE INDEX ux_reg_baseline_common ON regression_baselines(project_id, baseline_code, revision) WHERE release_id IS NULL;
CREATE INDEX idx_reg_baseline_state ON regression_baselines(project_id, state);
CREATE TABLE regression_baseline_items (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), baseline_id INTEGER NOT NULL,
  tc_id INTEGER NOT NULL, tc_version INTEGER NOT NULL, layer TEXT NOT NULL CHECK(layer IN ('R0','R1','R2','R3','R4')),
  snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, id), UNIQUE(project_id, id, baseline_id, tc_id, tc_version), UNIQUE(baseline_id, tc_id),
  FOREIGN KEY(project_id, baseline_id) REFERENCES regression_baselines(project_id, id),
  FOREIGN KEY(project_id, tc_id) REFERENCES test_cases(project_id, id),
  FOREIGN KEY(tc_id, tc_version) REFERENCES test_case_versions(tc_id, version)
);
CREATE INDEX idx_reg_item_tc ON regression_baseline_items(project_id, tc_id, tc_version);
CREATE TABLE test_runs (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), release_id INTEGER NOT NULL,
  baseline_id INTEGER NOT NULL, round_no INTEGER NOT NULL CHECK(round_no > 0),
  build_ref TEXT NOT NULL DEFAULT '', commit_sha TEXT NOT NULL DEFAULT '', environment TEXT NOT NULL DEFAULT '',
  config_hash TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'planned' CHECK(state IN ('planned','running','closed')),
  created_by INTEGER REFERENCES users(id), closed_by INTEGER REFERENCES users(id), closed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, id), UNIQUE(project_id, id, baseline_id, release_id), UNIQUE(project_id, release_id, round_no),
  FOREIGN KEY(project_id, release_id) REFERENCES releases(project_id, id),
  FOREIGN KEY(project_id, baseline_id) REFERENCES regression_baselines(project_id, id)
);
CREATE INDEX idx_reg_runs_baseline ON test_runs(project_id, baseline_id);
CREATE TABLE regression_reports (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), run_id INTEGER NOT NULL,
  comparison_run_id INTEGER, report_code TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0),
  state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','approved','frozen')),
  snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, template_version TEXT NOT NULL DEFAULT '',
  created_by INTEGER REFERENCES users(id), approved_by INTEGER REFERENCES users(id), approved_at TEXT,
  frozen_by INTEGER REFERENCES users(id), frozen_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, id), UNIQUE(project_id, report_code, revision),
  FOREIGN KEY(project_id, run_id) REFERENCES test_runs(project_id, id),
  FOREIGN KEY(project_id, comparison_run_id) REFERENCES test_runs(project_id, id)
);
CREATE INDEX idx_reg_reports_run ON regression_reports(project_id, run_id);
CREATE TABLE regression_evidence_refs (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), execution_id INTEGER NOT NULL,
  artifact_key TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('image','log','assertions','package')),
  locator TEXT NOT NULL, sha256 TEXT NOT NULL, byte_size INTEGER CHECK(byte_size IS NULL OR byte_size >= 0),
  summary TEXT NOT NULL DEFAULT '', created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(execution_id, artifact_key), FOREIGN KEY(project_id, execution_id) REFERENCES tc_executions(project_id, id)
);
CREATE INDEX idx_reg_evidence_execution ON regression_evidence_refs(project_id, execution_id);
CREATE TABLE regression_events (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL, action TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}',
  before_hash TEXT, after_hash TEXT, actor_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_reg_events_entity ON regression_events(project_id, entity_type, entity_id, created_at);
COMMIT;
