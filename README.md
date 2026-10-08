# cf-story-pool 需求池

现场需求与缺陷回流池。CF Pages + D1，附件存 D1 BLOB（**定案 2026-10-08：不开 R2**——用户无国外信用卡无法开通，D1 免费额度 5GB 对本场景充足）。
部署：https://cf-story-pool.pages.dev （全站门禁，登录后可见；站点名与仓库同名）

## 账号
- `xiao` / `zhoubin` / `chenhaiyan`：初始密码在 workspace `.secrets/story_pool_pass_*`（600 权限，明文不进对话/源码/日志），登录后右上角「改密码」自助修改
- `qwenpaw`（助理，**测试专用**）：密码在 `.secrets/story_pool_qwenpaw`；verify_live.py 全部用它，不碰真实账号

## 结构
- `schema.sql` — 11 表（users/sessions/login_throttle/projects/tags/requirements/requirement_tags/attachments/attachment_blobs/checklist_items/events）+ requirements_fts（FTS5）+ 触发器同步 + 索引，D1=cf-story-pool-db
- `worker_src/_worker.js` → `dist/_worker.js` — 全站门禁 + API（login/logout/me/me-password/bootstrap/tags/my-work/dedup-suggest/upload/files/requirements CRUD/comment/checklist）
- `dist/` — index.html（列表+筛选+我的工作项+分页）、new.html（提单：项目/类型/紧急度/标签/截图压缩/去重提示）、req.html（详情/状态流转/编辑/标签/工作项清单/附件/评论/流水）、login.html、style.css
- `scripts/cf_d1.py` — D1 桥接（create-bound/exec/query/info）
- `scripts/cf_r2.py` — R2 建桶+绑定（**已废弃不用**：R2 定案不开；脚本保留备查）
- `scripts/seed_users.py` — 用户种子（读 .secrets，输出仅含 PBKDF2 哈希；**重跑会使这些账号所有会话失效**）
- `scripts/verify_live.py` — 线上功能自检（带浏览器 UA 否则 CF 403；17 项断言：门禁/登录/建单/去重/流转/清单/评论/标签/附件上传下载/重复关闭/删除清理；结尾自动更新 pw.py 核对用 cookie）

## 运维命令
```bash
python3 scripts/cf_d1.py info                                   # 库与绑定状态
python3 scripts/cf_d1.py exec <file.sql>                        # 执行 SQL
python3 scripts/seed_users.py && python3 scripts/cf_d1.py exec data/seed_users.sql  # 重置密码（会踢所有会话）
python3 scripts/verify_live.py                                  # 线上功能自检
python3 tools/publish-web/pw.py deploy --name cf-story-pool --dir projects/cf-story-pool/dist \
  --verify-cookie-file .secrets/verify-cookie-cf-story-pool.txt --note "..."   # 发布（勿裸 wrangler）
```

## 数据口径
- 状态机：submitted(待复现确认)→confirmed(已确认)→scheduled(已排期)→fixed(已修复)→verified(已验证)→closed(已关闭)；重复单 dup_closed 必须指向原单（duplicate_of）
- 附件：仅图片 png/jpg/webp/gif，单张 ≤2MB、每单 ≤3 张；前端 canvas 压缩（>300KB 转 JPEG 长边 1600）；存 attachment_blobs（token=uuid 主键），api/files/<token> 登录后读取
- 去重：提单页标题防抖 400ms → FTS5 全文 MATCH 开放状态单 TOP5；列表搜索同源
- 时间一律 UTC ISO 存储，前端 toLocaleString 展示；事件流水 events 记录 create/status/edit/tag/checklist/comment，评论原文存 events.detail
- 删除需求为硬删（含子表 + 附件 BLOB + 解除重复引用），仅用于误录/清理
