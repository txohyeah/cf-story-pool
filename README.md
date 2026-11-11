# cf-story-pool 需求池

现场需求与缺陷回流池。CF Pages + D1，附件存 D1 BLOB（**定案 2026-10-08：不开 R2**——用户无国外信用卡无法开通，D1 免费额度 5GB 对本场景充足）。
部署：https://cf-story-pool.pages.dev （全站门禁，登录后可见；站点名与仓库同名）

## 账号
- 账号由管理员在站内发放；密码不入库、不落日志、不进对话，首次登录后右上角「改密码」自助修改
- 自动化测试使用独立测试账号，凭据从本地未入库配置注入（环境变量优先），仓库内不含任何账号表或口令

## 结构
- `schema.sql` — 11 表（users/sessions/login_throttle/projects/tags/requirements/requirement_tags/attachments/attachment_blobs/checklist_items/events）+ requirements_fts（FTS5）+ 触发器同步 + 索引，D1=cf-story-pool-db
- `worker_src/_worker.js` → `dist/_worker.js` — 全站门禁 + API（login/logout/me/me-password/bootstrap/tags/my-work/dedup-suggest/upload/files/requirements CRUD/comment/checklist）
- `dist/` — index.html（列表+筛选+我的工作项+分页）、new.html（提单：项目/类型/紧急度/标签/截图压缩/去重提示）、req.html（详情/状态流转/编辑/标签/工作项清单/附件/评论/流水）、login.html、style.css
- `scripts/cf_d1.py` — D1 桥接（create-bound/exec/query/info）
- `scripts/cf_r2.py` — R2 建桶+绑定（**已废弃不用**：R2 定案不开；脚本保留备查）
- `scripts/seed_users.py` — 用户种子（读本地未入库的账号配置，输出仅含 PBKDF2 哈希；**重跑会使这些账号所有会话失效**）
- `scripts/verify_live.py` — 线上功能自检（带浏览器 UA 否则 CF 403；17 项断言：门禁/登录/建单/去重/流转/清单/评论/标签/附件上传下载/重复关闭/删除清理；结尾自动更新 pw.py 核对用 cookie）

## 运维命令
```bash
python3 scripts/cf_d1.py info                                   # 库与绑定状态
python3 scripts/cf_d1.py exec <file.sql>                        # 执行 SQL
python3 scripts/seed_users.py && python3 scripts/cf_d1.py exec data/seed_users.sql  # 重置密码（会踢所有会话）
python3 scripts/verify_live.py                                  # 线上功能自检
python3 <本地发布工具>/pw.py deploy --name cf-story-pool --dir ./dist \
  --verify-cookie-file <本地 cookie 文件> --note "..."   # 发布（勿裸 wrangler）
```

## 数据口径
- 状态机：submitted(待复现确认)→confirmed(已确认)→scheduled(已排期)→fixed(已修复)→verified(已验证)→closed(已关闭)；重复单 dup_closed 必须指向原单（duplicate_of）
- 附件：仅图片 png/jpg/webp/gif，单张 ≤2MB、每单 ≤3 张；前端 canvas 压缩（>300KB 转 JPEG 长边 1600）；存 attachment_blobs（token=uuid 主键），api/files/<token> 登录后读取
- 去重：提单页标题防抖 400ms → FTS5 全文 MATCH 开放状态单 TOP5；列表搜索同源
- 时间一律 UTC ISO 存储，前端 toLocaleString 展示；事件流水 events 记录 create/status/edit/tag/checklist/comment，评论原文存 events.detail
- 删除需求为硬删（含子表 + 附件 BLOB + 解除重复引用），仅用于误录/清理

## 数据包导出 API（给外部 agent/自动化）

登录后（cookie `storypool_auth`）调用：

```
GET /api/export-package?project=<项目id>
```

返回项目全量上下文 JSON：`requirements`（含 tags/comments 全文）、`releases`（含执行记录与统计）、`testcases`（含 steps_md 全文/版本/执行）、`docs`（含当前 content_md）、`project`。外部 agent 由管理员发放 pool 账号即可调用；页面顶栏「📦 数据包」按钮为同一数据的下载入口。

## 状态快照（迁移自 PROFILE.md 项目矩阵 @2026-10-29）

- 原矩阵行（无损保留）：| **cf-story-pool** (需求池) | v2 v1.1 | 🟢 v1.0+v1.1 published，需求 15 条 closed 归档 | 现场需求回流池→研发过程管理平台（v2 规划 `docs/v2-研发过程管理功能规划.md`，首个业务项目落地、后续项目复用）；代码 `git@github.com:txohyeah/cf-story-pool.git`（main，v1.0+v1.1 系列 commit）；部署 https://cf-story-pool.pages.dev ；全站门禁，4 个账号由管理员发放（凭据本地保管，不入库）；D1 cf-story-pool-db 22 表（+counters）+ FTS5 + 文档页（md+版本快照+评论绑版本+三态）+ releases 版本单 + 用例库（TC 编号 counters 全局递增不复用/快照/批准冻结/按需求分组+related_req 下拉）+ 执行记录（挂 releases 统计）+ 评论类型（普通/验收标准 两档）+ severity 四级/root_cause/ref_code 互指 + 筛选导出 CSV + BlobStorage 抽象+blob_stats.py；顶栏=需求/📄文档/🚀版本/🧪用例/⬇导出（sticky z40）+抽屉↔用例库联动+**全局项目上下文（renderProjectBar+localStorage pool_project）**；**story-pool 自开发项目 id=3：v1.0 published+closed（需求 8 条 verified→closed+基线 25 条 approved+执行 25/25+报告 id=2 批准）；v1.1 published+closed（需求 7 条 verified→closed+全量回归 33/33+报告 id=4 批准+docgen 终态三件归档）+#201 数据包导出（端点/按钮/README 说明）verified**；语雀历史清单已一次性迁入；verify_live **80 项全绿+残留清零（10-18：连续 FAIL 根因实锤=apiReqDelete 缺 related_req 置空（#196 同型缺口第二处）已修，非网络抖动；10-19 复跑全绿）**；**10-19 版本过滤上线：过滤条新增「版本」下拉（release_id 过滤全链路=列表/侧栏/CSV导出/URL深链）+卡片版本改紫色 rel-chip 徽标（release_id 承载，v1.0/v1.1/v1.5 版本号标签已摘除，版本归属只走 release_id）+/api/export 加关联版本列与按版本统计；顺手修存量 bug=导出>100条必500（D1 bind 上限 100，验收标准汇总 IN(ids) 改分批 90）**；挂账=无阻塞项；10-26 前端重构「追踪器控制台」（codex执笔+韩立审核：冷白钴蓝token/状态圆点语义映射/mono机器信息/五入口统一导航，verify_live 80项全绿，flex补丁修零工作项窄栏存量bug）已上线；工作纪律：讨论需求只出方案不动手（10-17 违反一次已认错）+"工具调用被取消"≠"服务端未执行"+站点数据修订先本地确定再一次写入（铁律④）；估时单位用 h；**v1.2 候选：电子签名 A/cron 提醒/保存期限已挂起（10-18 用户拍板暂不做；10-28 复议=估计不会做，先放着）；docgen 数据包导出已上线（export CLI：项目全量上下文 JSON 119KB——需求含评论/releases/用例含步骤全文/执行/文档清单，agent 配模板构建任意个性化文档；页面「📦 数据包」按钮已随 #201 与 /api/export-package 端点同批上线（commit 94bfdf3，10-18 晚，10-28 用户截图核实仍在位——旧注「按钮未做」系 docgen CLI 落地时的过期快照）；⚠️ 站点目前个人维护，后续若转交他人维护，需重审账号体系与凭据归属** |

- **11-08 更新：需求详情抽屉评论/流水分离（commit 2758cea）**——评论独立成完整列表（正序+计数徽标+ctype 徽标+本人编辑删除+「只看类型」筛选联动，徽标计总数不受筛选影响）带 `.cmt` 左边框浅底色样式（主/宽屏双段），流水回归纯审计（排除 comment；comment_edit 只留动作行不重复正文、comment_delete 固定文案）；`comment-body-{id}` 编辑锚点保留、取消编辑与 c-filter 改绑 renderComments、loadReq 清空链补 comments 容器防 #200 同型残留；API/worker 零改动，纯前端（index.html+style.css）；codex 执笔+韩立审核（diff 范围/锚点/CSS 变量/fmtTime 核验）；verify_live 90 项全绿+浏览器实测（发/编/取消/筛选/分离渲染，删除 confirm 属人机确认步骤 SDK 拒绝属预期、API 层已覆盖）
- **11-02 更新：评论编辑/删除上线（commit 6e6ff90）**——作者本人可编辑/删除自己的需求评论（events 流水留痕：comment_edit 存新文本 / comment_delete 固定文案不存原文）与文档评论（doc_comments 硬删无留痕）；管理员账号升 role=admin（迁移已执行，data/migration_admin_20261102.sql），admin 可删不可改他人评论；ctype（普通/验收标准）不可经编辑篡改；审核抓真 bug=先删后插致 events rowid 复用，修为留痕 INSERT 先于 DELETE；verify_live 90 项全绿（CM 断言含 rowid 复用守卫）+ 越权补测 8/8（temp_script/storypool_perm_matrix_test.py）
