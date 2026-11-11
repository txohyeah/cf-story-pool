-- 基础字典种子：研发项目 + 预置标签（幂等，可重跑）
-- 注：真实项目名由管理员在站内配置，以下为占位示例
INSERT OR IGNORE INTO projects (name, is_active) VALUES ('项目一', 1);
INSERT OR IGNORE INTO projects (name, is_active) VALUES ('项目二', 1);
INSERT OR IGNORE INTO tags (name) VALUES ('AI整理');
INSERT OR IGNORE INTO tags (name) VALUES ('语雀迁移');
