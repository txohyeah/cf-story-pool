-- 增量迁移 2026-10-17：R7 评论类型（events.ctype，仅 comment 行有意义；doc_comments 不动）
ALTER TABLE events ADD COLUMN ctype TEXT NOT NULL DEFAULT 'normal';
CREATE INDEX IF NOT EXISTS idx_events_ctype ON events(ctype);
