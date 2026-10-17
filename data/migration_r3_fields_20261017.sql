-- 增量迁移 2026-10-17：R3 单据字段增强（severity 四级/root_cause 六分类/ref_code 互指）
-- 英文码入库（与 status/type 口径一致），前端映射中文；存量行默认空值零影响
ALTER TABLE requirements ADD COLUMN severity TEXT NOT NULL DEFAULT '';
ALTER TABLE requirements ADD COLUMN root_cause TEXT NOT NULL DEFAULT '';
ALTER TABLE requirements ADD COLUMN ref_code TEXT NOT NULL DEFAULT '';
ALTER TABLE requirements ADD COLUMN related_codes TEXT NOT NULL DEFAULT '[]';
CREATE INDEX IF NOT EXISTS idx_req_severity ON requirements(severity);
CREATE INDEX IF NOT EXISTS idx_req_refcode ON requirements(ref_code);
