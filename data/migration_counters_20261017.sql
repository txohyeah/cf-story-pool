-- 增量迁移 2026-10-17：持久计数器（TC 编号一经分配不复用——MAX 法删除尾部编号后复用，TC-015 执行实证）
CREATE TABLE IF NOT EXISTS counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
INSERT OR IGNORE INTO counters (name, value) VALUES ('tc_code', (SELECT MAX(CAST(SUBSTR(tc_code, 4) AS INTEGER)) FROM test_cases));
