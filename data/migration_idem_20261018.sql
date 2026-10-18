-- 增量迁移 2026-10-18：#199 提单幂等键（client_token 去重防网络抖动建重）
ALTER TABLE requirements ADD COLUMN client_token TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_req_ctoken ON requirements(client_token) WHERE client_token IS NOT NULL;
