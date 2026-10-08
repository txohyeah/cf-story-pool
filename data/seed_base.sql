-- 基础字典种子：研发项目 + 预置标签（幂等，可重跑）
INSERT OR IGNORE INTO projects (name, is_active) VALUES ('be-trial', 1);
INSERT OR IGNORE INTO projects (name, is_active) VALUES ('oncology', 1);
INSERT OR IGNORE INTO tags (name) VALUES ('AI整理');
INSERT OR IGNORE INTO tags (name) VALUES ('语雀迁移');
