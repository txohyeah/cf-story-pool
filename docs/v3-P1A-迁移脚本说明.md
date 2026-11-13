# P1-A 回归模块迁移脚本说明
## CP-1 2026-11-13 18:40:48 CST 已读取 v1.2、既有 DDL 和迁移清单，识别执行顺序及合成数据唯一约束冲突。
## CP-2 2026-11-13 18:41:34 CST 已编写八表、项目约束与两条部分唯一索引。
## CP-3 2026-11-13 18:41:34 CST 已编写执行表事务重建，保留旧字段和记录，新增 diff 及轮次唯一约束。
## CP-4 2026-11-13 18:42:13 CST 已完成本地合成库演练，两脚本均退出 0；行数、外键、完整性及约束负例通过。
## 脚本及范围
- `migration_regression_core_20261113.sql` 新增八表：feature_points（功能点）、tc_feature_points（映射）、regression_baselines（基线）、regression_baseline_items（完整快照及来源版本）、test_runs（轮次）、regression_reports（报告快照）、regression_evidence_refs（证据引用）、regression_events（回归审计）。均有 project_id、创建和更新时间；关联采用项目复合外键及索引。
- `migration_regression_executions_20261113.sql` 事务重建 tc_executions：旧字段及 ID 原样复制，新增项目/轮次/基线/基线项和 DIFF 确认字段，新增索引；旧 tc_version 原样保留。
- result CHECK 新增 diff 并保留 deviation：新结果与既有偏离记录语义不同，不改写历史。
- 基线两条 SQLite 部分唯一索引分别使用 `WHERE release_id IS NOT NULL`、`WHERE release_id IS NULL`；前者包含 release_id，后者不含，均已实际创建并以重复插入验证。普通 UNIQUE 对 NULL 不判重复。
- UNIQUE(run_id, baseline_item_id) 在旧行两列均为 NULL 时形同无效；将旧数据识别为只读 legacy，业务新行必须提供项目/轮次/基线/基线项/版本（脚本 CHECK 已约束），服务端禁止覆盖旧行，并校验同项目、冻结状态和显式确认。不得给未知历史编造基线。
- 复合外键将新执行绑定同项目轮次与同一基线项，数据内容完整性、快照不可改、DIFF 签字门禁、基线与发布版本适配和审计只追加仍须后续应用层实现；当前 SQL 不实现相关 API/页面。
- 核心脚本完成后至执行表重建前，证据表外键引用的父表新字段尚不存在；切换期间应阻断访问，两个脚本完成并通过检查后才恢复。脚本均非幂等，不可盲目重跑。

## 本地演练及偏差
- 使用本地 sqlite3、独立临时库及全合成数据；基线：3 项目、5 用例、5 首版、2 个发布单（版本文本相同，仅 1 种版本值）、6 执行，原先 2 个 tc_version 非空、4 个 NULL、1 个 deviation。
- 必须说明：严格文件名顺序首先在 counters 迁移失败（依赖的 test_cases 尚不存在），因此演练在 schema 后按名称顺序执行其他旧迁移、最后补执行 counters；按名字顺序全绿的原要求客观无法满足，未修改既有脚本。
- 同一个 release_id 配 5 用例最多有 5 条旧执行，旧 `UNIQUE(tc_id,release_id)` 不允许第 6 条；故用第二个合成发布单保存第 6 条。若“1 个 version”要求仅 1 条 releases 行，则该测试数据要求与旧 DDL 矛盾，未完全满足。
- 已启用 SQLite 外键；脚本退出码：`core=0`，`executions=0`；迁移前→后：`tc_executions 6→6；tc_version NULL 4→4；deviation 1→1`。
- `PRAGMA foreign_key_check`：无输出；`PRAGMA integrity_check`：`ok`；通用/专用基线重复、同轮同基线项重复、跨项目证据引用均被拒绝，合法 diff 新行可插入并回滚。
- `PRAGMA index_list(tc_executions)`：`idx_reg_exec_run_result(普通), idx_tce_rel(普通), idx_tce_tc(普通), sqlite_autoindex_tc_executions_2(唯一), sqlite_autoindex_tc_executions_1(唯一)`。
- `PRAGMA index_list(regression_baselines)`：`idx_reg_baseline_state(普通), ux_reg_baseline_common(唯一/partial), ux_reg_baseline_release(唯一/partial), sqlite_autoindex_regression_baselines_1(唯一)`。

## 上云执行前置条件（本轮不上云；脚本待人工审批后才执行）
- 负责人在维护窗口暂停写入，核对目标、迁移顺序、旧库真实 DDL、项目引用、旧行数及所有触发器/索引；审查并验证 D1 对显式事务、表重建及外键行为的实际支持，再决定可执行方案。本地 SQLite 成功不等于 D1 已验证。
- 由有授权的站点负责人执行备份命令（示例，未执行）：`wrangler d1 export <DATABASE_NAME> --remote --output backup-YYYYMMDD-HHMMSS.sql`；文件妥善保管于受控备份位置，不入公开仓库。记录备份时间和哈希。
- 在本地隔离库导入备份，核对业务表数、各关键表行数（尤其 test_cases、test_case_versions、tc_executions）、外键检查和完整性；分别记录前后快照及保留所有原列值。
- 现有 Worker 对 `(tc_id,release_id)` 执行 ON CONFLICT；迁移后该旧唯一键已移除，旧写接口会报错。因此必须先准备并演练兼容 Worker、暂停写入并作为一个维护窗口协调切换；本任务未实现 Worker，不可单独发布 SQL 后恢复旧写入口。
- 两脚本执行后检查退出状态、表数/行数、外键、完整性、索引与新旧路径；任一步失败即保持维护窗口和写入关闭。若失败在事务内先确认回滚，再核对实际库状态；若核心已提交或已发生写入，不盲目重跑、不直接覆盖当前库，由负责人依据已验证备份恢复到隔离的新库并核对，再经审批切换绑定；数据恢复和绑定切换均需单独授权。
- 现存四份历史评审/方案文档在本任务开始前已是未跟踪文件，本次不修改或移除；因此全仓 `git status` 不可能只显示本次三项。仅以本次新增文件集合核对。
## CP-5 2026-11-13 18:42:48 CST 已记录演练偏差、约束验证、切换风险、备份与恢复前置条件。
- 唯一索引列核对：`sqlite_autoindex_tc_executions_1 = run_id,baseline_item_id`；`sqlite_autoindex_tc_executions_2 = project_id,id`。

## 依据
- 本地方案 v1.2 §2–3，读取于 2026-11-13：“完整快照”“执行只读关联基线项的冻结快照”，支撑表结构与引用设计。
- 本地既有迁移，读取于 2026-11-13：`UNIQUE (tc_id, release_id)` 和 `tc_version INTEGER`，支撑两发布单演练和旧值保留。
- 本地 SQLite 合成演练，2026-11-13：`6→6`、`foreign_key_check` 无输出、`integrity_check=ok`；支撑本地迁移结果，不代表线上 D1 实测。
## CP-6 2026-11-13 18:43:01 CST 已核对索引列与本次文件范围；线上执行兼容性仍待后续验证。
