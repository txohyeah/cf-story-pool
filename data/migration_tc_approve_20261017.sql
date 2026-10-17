-- 增量迁移 2026-10-17：test_cases 批准留痕（用户指出批准未落人，对齐 docs 表模式）
ALTER TABLE test_cases ADD COLUMN approved_by INTEGER REFERENCES users(id);
ALTER TABLE test_cases ADD COLUMN approved_at TEXT;
