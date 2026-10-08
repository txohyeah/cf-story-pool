# cf-story-pool 需求池 PRD v0.1

> 2026-10-08 初稿，待用户审定后开发。
> 定位：三人小团队（晓/周斌/陈海燕）的需求与缺陷回流池，托管 CF Pages，AI 深度介入。
> 语雀继续放文档（PRD/用户手册），本站只管需求流水。

## 1. 背景

be-trial v1 上线后现场需求回流，原语雀周会文档模式四个痛点：无结构（无法按模块/状态筛选）、易重复（靠记忆去重）、复现确认难跟踪（状态只在 checkbox 里）、与 AI 断连（语雀无结构化 API）。

已排除路线：Jira/开源自部署（重、占服务器、AI 弱）、纯 SaaS（定制天花板低）。选定自研 CF Pages，照抄 stocks-site / cf-crypto-site / zhixidao / paper-sim 四站成熟骨架。

## 2. 用户与权限

| 用户 | 分工 |
|---|---|
| 晓 | 产品设计 + 后端开发（创建人） |
| 周斌 | 前端开发 |
| 陈海燕 | — |

- 三人全权限，无角色、无状态流转权限约束
- 加人 = users 表插一行
- 第 4 个账号 `qwenpaw`：verify 自检与 agent web 动作专用，不碰真实账号（zhixidao 教训）
- 认证照抄 zhixidao：PBKDF2 + 登录限速（每 IP 每小时 10 次失败）+ session cookie
- 口令落 `.secrets/story_pool_pass_*`（600 权限，不落对话）

## 3. 数据模型（DDL 草稿）

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  pass_hash TEXT NOT NULL,              -- PBKDF2
  salt TEXT NOT NULL,
  is_active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE projects (                 -- 研发项目字典
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,            -- be-trial / oncology
  is_active INTEGER DEFAULT 1
);

CREATE TABLE tags (                     -- 自由标签字典（来源/主题/标记都往这送）
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

CREATE TABLE requirements (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  type TEXT NOT NULL DEFAULT 'req',     -- bug / req(需求) / opt(优化)
  urgency TEXT NOT NULL DEFAULT 'normal',   -- normal / urgent
  status TEXT NOT NULL DEFAULT 'submitted',
  channel TEXT NOT NULL DEFAULT 'web',  -- web / agent / migrate
  duplicate_of INTEGER REFERENCES requirements(id),  -- 重复关闭时指向原单
  created_by INTEGER REFERENCES users(id),
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE requirement_tags (
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  tag_id INTEGER NOT NULL REFERENCES tags(id),
  PRIMARY KEY (req_id, tag_id)
);

CREATE TABLE attachments (
  id INTEGER PRIMARY KEY,
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  r2_key TEXT NOT NULL,
  orig_name TEXT,
  size INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE checklist_items (          -- 工作项清单（方案B，非真 subtask）
  id INTEGER PRIMARY KEY,
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  content TEXT NOT NULL,                -- 如：产品设计 / 前端开发 / 后端开发
  assignee_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'todo',  -- todo / doing / done
  sort_order INTEGER DEFAULT 0          -- 行顺序即接力顺序
);

CREATE TABLE events (                   -- 事件流水：状态/评论/确认复现/清单变更全留痕
  id INTEGER PRIMARY KEY,
  req_id INTEGER NOT NULL REFERENCES requirements(id),
  actor_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,                 -- create/status/comment/checklist/tag/edit
  detail TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);

-- FTS5 全文索引（去重提示 + 搜索）
CREATE VIRTUAL TABLE requirements_fts USING fts5(
  title, description, content='requirements', content_rowid='id'
);
-- 触发器同步 requirements → requirements_fts（INSERT/UPDATE/DELETE 三个）
```

## 4. 状态机

```
submitted(待复现确认) → confirmed(已确认) → scheduled(已排期)
  → fixed(已修复) → verified(已验证) → closed(已关闭)
任意状态 → dup_closed(重复关闭)，必须填 duplicate_of 指向原单
```

- 全员可点任意流转，按钮给"建议下一步"但不强制（三人团队，不设权限矩阵）
- 复现确认 = 在 `submitted` 上点"已确认"，事件流水自动记 actor + 时间

## 5. 页面清单（移动端优先，plain HTML+JS 照抄 zhixidao 模式）

| 页面 | 内容 |
|---|---|
| `/login` | 登录（点标题 5 次出 admin 表单的彩蛋不需要，三人都是普通登录） |
| `/` 列表 | 筛选：项目/状态/类型/标签/搜索(FTS5)；**顶部"我的工作项"区**：当前用户 checklist 未完成行跨单聚合（周斌打开就看到自己压着的活）；分页 50/页，数据库端做 |
| `/new` 提交表单 | 项目(必选)、类型、紧急度、标题(必填)、描述、标签(可输可选、create-if-missing)、截图(≤3 张，可选)；**输入标题时实时调 dedup-suggest 显示疑似重复 top5**，可一键跳转查看 |
| `/req/:id` 详情 | 基本信息卡、状态流转按钮、工作项清单（增删改/换负责人/勾完成）、附件查看、标签编辑、重复关联显示、事件流水时间线 |

## 6. API（worker 路由）

```
POST /api/login | /api/logout
GET  /api/me
GET  /api/requirements?status=&project=&type=&tag=&q=&assignee=&page=
POST /api/requirements            -- 建（tags 数组、attachment keys 预传）
GET  /api/requirements/:id        -- 全量：含 tags/attachments/checklist/events
PATCH /api/requirements/:id       -- 状态流转 / 编辑 / duplicate_of
POST /api/requirements/:id/comment
POST /api/requirements/:id/checklist
PATCH/DELETE /api/checklist/:id
POST /api/upload                  -- multipart 图片，鉴权后写 R2，≤3 张/单，单张≤1MB
GET  /api/files/:key              -- R2 受门禁读取（桶不公开）
GET  /api/tags?q=
GET  /api/dedup-suggest?q=        -- FTS5 top5 疑似重复
```

## 7. AI 融入点

- **P0 通道**：agent 直连 D1 建单（channel=agent，自动打 `AI整理` 标签），讨论结论写事件流水；周斌等现场人员走 web 表单
- **P0 去重提示**：提交表单 FTS5 实时疑似重复（零成本、无外部依赖）
- **P1 LLM-in-worker**（等用户提供 API key 放 CF Secret 再做）：语义去重重排、标签建议、截图 OCR 预填模块/类型/复现步骤草稿
- **零开发常驻能力**：周汇总、重复聚类分析、按需查询、起草开发任务——agent 直连 D1 天然具备

## 8. 存储与配额

- D1：`cf-story-pool-db`；一年几百单，免费额度富余；写额度纪律照旧（写后 SELECT 读回对账）
- R2：`story-pool-assets` 桶（不公开）；截图前端 canvas 压缩（长边 1600px / JPEG 0.8）后上传
- robots 全站禁止收录（内部工具）

## 9. 部署与纪律

- 仓库 `git@github.com:txohyeah/cf-story-pool.git`（已建）
- Pages 项目名 `cf-story-pool` → https://cf-story-pool.pages.dev
- 发布链：worker_src → cp dist → git push → pw.py deploy（照 runbook；_worker.js 必须在 dist 根）
- 自检 `scripts/verify_live.py`：登录/建单/流转/清单/去重/附件全链路断言，用 qwenpaw 账号
- 数据备份：backup_d1.py 定期导出
- 上线顺序：先 D1 建表 + seed（users/projects/tags + qwenpaw 账号），再部署 worker

## 10. MVP 边界

**做**：上述 P0 全部。
**不做（先）**：飞书推送、拖拽看板、权限矩阵、邮件通知、LLM-in-worker（P1，等 key）、多项目工作流差异。
**存量迁移**：语雀未闭环条目，站点可用后解析入库（channel=migrate，自动打 `语雀迁移` 标签）。

## 11. 里程碑估算

- D1+R2+骨架+登录：照抄现成 runbook，约半个晚上
- 提交表单+列表+详情+状态机+清单：约一个晚上
- 去重提示+附件链路+verify 脚本：约半个晚上
- 存量迁移：迁移脚本半个晚上
