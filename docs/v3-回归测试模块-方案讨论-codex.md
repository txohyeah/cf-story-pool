## CP-1 2026-11-13 17:26 CST 已核对基础表与增量迁移；发现执行已有 tc_version，批准已有人员时间字段，后续按实际差异设计。
## CP-2 2026-11-13 17:28 CST 已核对 Worker、用例页面、文档表与附件约束；定位覆盖执行、按需求分组和硬删除风险，未发现独立 reports 表。
# 回归测试模块评审方案（仅设计，待评审）
- 范围：每个项目各有功能点、基线、轮次与报告；不改代码、DDL、线上数据。以下新增字段均为建议，不代表现存。
- 事实边界：仅核对本地仓库；线上迁移是否全部应用、已有报告文档分类与保留策略待核实，不连接 D1。

## 四个决策（推荐做法 + 理由）
1. **复用并扩展 test_cases/test_case_versions/tc_executions**，新增基线、轮次与报告实体；理由：保留现有编号、需求追踪与版本单入口，避免两套用例库漂移。
2. **独立功能点表 + 多对多**，不用 fp_code 字符串列；理由：一个用例可覆盖多个功能点，功能点也是独立维护的业务资产。
3. **报告存储型不可变快照**，实时聚合只做预览；理由：历史结论不能随用例、签字或轮次变化而被重算。
4. **首期仅存用例级结果**，步骤断言放证据包；理由：个人维护成本可控，步骤级明细暂不增加站点模型与编辑负担。

## A. 数据模型与隔离
- 约定：下文 PK=id（除注明复合键）；P=project_id→projects.id；所有 *_by→users.id；时间用现有 TEXT 格式；业务删除默认 RESTRICT。
- 每张新增业务实体有 P；关系表冗余 P，复合 FK 保证同项目；除注明唯一键外均加 P 索引，FK 子列加索引。
- 现有 projects/releases/requirements：保留；为 releases/test_cases 增 UNIQUE(project_id,id) 供复合 FK 使用；不把版本单当测试轮次。
- test_cases：保留 tc_code 全局 UNIQUE、related_req 可空及现有两态 status；新增 retired_at、retired_by、retire_reason、approved_version（最近批准版本号）。
- test_cases 索引新增 (project_id,retired_at,status)；approved_version 以 (id,approved_version) 引用 test_case_versions(tc_id,version)，允许 NULL。
- test_case_versions：保留 UNIQUE(tc_id,version)；新增 P、state(draft/approved/frozen)、snapshot_json、snapshot_hash、snapshot_quality、approved_by/at、frozen_by/at。
- snapshot_json 保存标题、步骤/预期、前置条件、数据引用/哈希、risk/ctype、covers_urs、related_req、功能点映射、R0—R4 分层；理由：steps_md 独自无法还原整版用例。
- 版本表新增 UNIQUE(project_id,tc_id,version)、FK(P,tc_id)→test_cases(project_id,id)；索引 (project_id,state)。旧 steps_md 保留供老页面读取。
- 新 feature_points：P、fp_code、title、description、status(active/pending/retired)、created_by/at；UNIQUE(P,fp_code)、UNIQUE(P,id)、索引(P,status)。
- 新 tc_feature_points：P、tc_id、fp_id；PK(P,tc_id,fp_id)，复合 FK 分别指向同项目用例/功能点，反向索引(P,fp_id)；表示工作副本关系，历史关系在版本快照。
- 新 regression_baselines：P、baseline_code、revision、state(draft/approved/frozen)、data_manifest_json、manifest_hash、created_by/at、approved_by/at、frozen_by/at。
- 基线 UNIQUE(P,baseline_code,revision)、UNIQUE(P,id)，索引(P,state)；data_manifest_json 记录数据集版本、生成脚本引用、预期哈希而非敏感数据原件。
- 新 regression_baseline_items：P、baseline_id、tc_id、tc_version、layer(R0/R1/R2/R3/R4)；PK(P,baseline_id,tc_id)。
- 基线项复合 FK→同项目基线和用例版本；索引(P,tc_id,tc_version)；仅允许批准且完整快照的版本入选，冻结后不能更换。
- 新 test_runs：P、release_id、baseline_id、round_no、build_ref、commit_sha、environment、config_hash、state(planned/running/closed)、comparison_run_id、created_by/at、closed_by/at。
- 轮次 UNIQUE(P,release_id,round_no)、UNIQUE(P,id)、UNIQUE(P,id,release_id)；release/baseline/comparison_run 均为同项目复合 FK，索引(P,release_id,state)。
- tc_executions：重建约束但保留原表名/ID/字段；新增 P、run_id、state(pending/completed/legacy)、diff_reason、diff_signed_by/at、diff_decision、source_execution_id。
- result 改 CHECK('','pass','fail','diff','deviation')；deviation 仅存量兼容，新回归 API 只接受三态；空结果是未执行，不是第四种结果。
- 移除 UNIQUE(tc_id,release_id)，改 UNIQUE(run_id,tc_id)；UNIQUE(source_execution_id) 防重复导入，旧行该列 NULL。
- 执行复合 FK(P,run_id,release_id)→test_runs(P,id,release_id)，FK(P,tc_id,tc_version)→版本表；索引(P,release_id)、(P,tc_id,executed_at)、(run_id,result)。
- run_id/tc_version 仅允许 legacy 行为空；普通执行必须匹配该轮基线项，用事务校验，避免绕过基线选择任意版本。
- 新 regression_reports：P、report_code、revision、run_id、comparison_run_id、state(draft/approved/frozen)、snapshot_json、snapshot_hash、template_version、created_by/at、approved_by/at、frozen_by/at。
- 报告 UNIQUE(P,report_code,revision)、UNIQUE(P,id)，run/comparison_run 同项目复合 FK；索引(P,run_id,state)；报告快照无附件 BLOB。
- 新 regression_evidence_refs：P、execution_id、artifact_key、kind(image/log/assertions/package)、locator、sha256、byte_size、summary、created_by/at。
- 证据 UNIQUE(execution_id,artifact_key)，FK(P,execution_id)→执行新增 UNIQUE(P,id)；索引(P,execution_id)；locator 是受控归档标识，不保存临时签名 URL 或凭据。
- 新 regression_events：P、entity_type、entity_id、action、before_hash、after_hash、detail_json、actor_id、created_at；索引(P,entity_type,entity_id,created_at)。
- 审计多态 entity_id 无物理外键，服务端按类型和 P 验证；只追加，覆盖批准/冻结/退役/签字/迁移/修订操作，理由：现有 events 强制绑定 req_id。
- 原 attachments/attachment_blobs/events/docs/doc_versions/doc_comments 保留原职能；不废弃旧表，不假设 reports 已存在；既有报告文档不静默搬迁或改编号。
- counters 保留 name PK/value：TC 沿用全局序列；报告/基线按 P 组合 name 原子递增，首次创建并发用唯一约束与重试；禁止 MAX+1、禁止复用编号。
- 隔离：所有读写/导出/对比显式携带并校验 P；不可只信 localStorage；新项目仅初始化数据，不增加项目专属表/分支。
- 理由：复合外键防止跨项目引用；项目筛选是数据隔离，现有门禁是否需要项目成员权限待核实，不能宣称已有独立租户权限。

## B. 用例版本维护
- 身份：tc_id 是稳定技术主键，功能点是业务组织维度；related_req 继续作为可选追溯，不作为用例身份或唯一分组依据。
- 改版：编辑复制出新修订，沿用 expected_version 乐观锁；每次保存形成追加快照，默认 draft，任何正文/映射/数据预期变化均推进版本。
- 批准→冻结：批准记录版本级人员、时间、哈希并禁止改正文；冻结用于正式基线，追加冻结事件，不撤销历史批准。批准/冻结后修改只另开草稿。
- test_cases.status/current_version 继续表示工作副本；approved_version 指向可选批准版，新草稿不会阻止旧批准版被基线引用；理由：兼容现有编辑回草稿行为。
- 执行版本：创建轮次时锁定冻结基线；写执行时取 baseline_items.tc_version，禁止从 current_version 随执行时点漂移。
- 退役：仅设置 retired_*，不能进入新基线；旧冻结基线与旧报告仍可查。需要继续重跑旧基线时显式批准并留事件；禁止硬删历史用例。
- 编号：沿用 TC-全局递增且不复用；功能点使用项目内 FP 编码，退役也占号；理由：无需破坏 tc_code 的现有全局唯一约束。
- 首批分层按已给口径 R0约26/R1七链/R2约90/R3约15/R4约25 配置；115个功能点与9个 PENDING 为待人工映射资产，不推断一对一或直接全批准。

## C. 执行、三态与逐版对比
- 一 release 可建多轮 test_runs；每轮固定 build/commit/环境/数据清单，按冻结基线预建 pending 执行项；重跑新增轮，禁止覆盖上一轮。
- 结果写入 tc_executions.result；同轮完成行不能被普通 PUT 覆盖，修正或重试建新轮；轮次关闭后结果与签字只读，理由：结果必须能复现。
- PASS=断言满足，FAIL=不满足，DIFF=预期差异待处置；DIFF 必须记录原因、签字人/时间和 accept/reject。
- 报告同时展示原始三态及门禁：未签/拒签 DIFF 按 FAIL 计，已接受 DIFF 单列可放行但不改写为 PASS；pending 阻止关闭与发布报告。
- deviation 保持原 GxP 偏离语义，dev_ref 原样保留；不批量改成 DIFF；历史未知结果/未知版本仅列 legacy，理由：不能伪造可比记录。
- 对比明确指定同项目两份 closed run，不自动挑“最新”；以 tc_id 配对，要求同用例版本、数据预期哈希、可比环境及配置。
- 可比集合中：旧非失败→新有效失败=新失败；旧有效失败→新有效失败=老失败；旧有效失败→新 PASS=已修复。
- 旧失败→已接受 DIFF 单列“差异获批”，不记已修复；增删用例、版本/预期变化、legacy/缺失/未执行单列“新增/移出/不可比”，不掺入修复率。
- 跨用例修订的比较可人工批准可比映射并存对比快照/理由，否则只并排展示；理由：新预期不能把旧缺陷自动洗成修复。

## D. 测试报告
- 聚合预览实时计算且标“非正式”；关闭轮次时生成报告草稿快照，固化用例全文/版本/基线/数据哈希/执行/三态/门禁/对比算法版本/证据清单/人员。
- 报告号推荐项目内 RPT-递增，revision 从1递增；同号修订保留前版，批准只签当前快照哈希，冻结后不可改正文或删除。
- 批准后冻结，签署元数据与审计事件独立追加，正文 hash 不受状态流转影响；更正用新 revision 并注明替代关系（存快照），理由：避免回写历史结论。
- 首期 HTML 页面+规范 JSON 导出；PDF 由同快照打印样式生成并显示 report_code/revision/hash，复杂 PDF 引擎后置；理由：JSON 可核验，页面/PDF 供评审归档。
- 账号批准可提供留痕，不等同合规电子签名；法规适用与身份核验另行评审，不把本次方案当作 GxP 认证承诺。

## E. 证据与容量
- 截图/日志/完整断言 JSON 放现有本地或受控文件归档目录，按项目/轮次/用例版本组织不可变证据包，生成 manifest+SHA-256；不开 R2、不塞 D1 BLOB。
- 站点仅存归档标识、哈希、大小、类型、脱敏摘要、签字与证据关联；ev_ref 保留兼容文本入口，新清单走 evidence_refs；理由：现有60字符截断不足以承载清单。
- 原需求附件仍仅图片≤2MB且每单≤3张；不借造需求单绕过限制，不把日志改扩展名上传。首期测试截图在站点只显示引用与摘要，不承诺内嵌浏览。
- 本地 locator 在浏览器不能直接下载：导出 manifest 后由维护者取包；权限可控的已有归档链接可选，不新建存储服务、不传出本地证据。
- 冻结前校验证据清单/哈希，定期归档备份与抽验；证据保留期、归档位置、备份责任人待评审确定，理由：哈希只能证明一致性，不能保证可取回。

## F. 建议迁移顺序（后续实施，本轮不执行）
1. 只读盘点线上 schema/迁移应用情况、执行数/NULL版本/deviation/报告文档；授权实施后先备份并校验可恢复，理由：本地脚本不能证明线上状态。
2. 增量建功能点/基线/轮次/报告/证据/审计表，扩展用例版本与唯一父键；默认关闭回归入口，保留全部旧数据与ID。
3. P 从用例/版本单关联回填，检查跨项目不一致并阻断迁移；旧版本只认原 steps_md，其他缺失字段标 snapshot_quality=legacy，不拿当前标题伪造历史。
4. 人工映射功能点，保留 related_req；仅对当前可核实版本重建完整快照并重新批准/冻结，历史批准人时间只保留原事实，不回填未知版本批准。
5. 短暂停旧执行写入口；本地演练重建 tc_executions 约束并原ID搬迁，逐 release 建 legacy 轮导入原行，NULL tc_version 不回填、deviation 不改义。
6. 对账总数、主键、原字段、外键及分项目校验和；原非空 tc_version 若无对应版本则隔离待核实，不造快照；不通过则恢复旧表与入口。
7. 发布兼容读写协议：老列表仍可读 legacy；老写接口对历史覆盖返回409，对多轮要求明确 run_id，绝不默选最后一轮；新入口严格锁基线。
8. 页面默认功能点/分层分组，保留需求分组；版本单新增轮次列表/对比/报告，原统计标“历史单次”避免与新轮混算；导出包增加 schema_version。
9. 验收两项目全链路隔离、并发编号、批准冻结防改、同版多轮、DIFF签字、legacy展示、报告哈希与证据离线取回；验收后逐项目启用。
- 回滚：保留迁移备份与旧协议读路径；产生新轮后故障只关闭新写入口，不强行压回旧唯一键，理由：降维回写会丢多轮记录。

## G. 风险与小时估时
- 历史不完整：tc_version NULL、旧快照仅步骤、报告分类不明；应对=明确 legacy 与待核实，不补造历史。
- 绕过冻结：旧用例/项目删除及旧PUT仍可删除或覆盖；应对=所有写路径统一状态守卫，已留痕资产只退役/归档。
- 跨项目泄漏：仅页面项目筛选不足；应对=服务端逐资源校验+复合外键+跨项目负例。
- DIFF 滥签与单人自批：应对=理由必填、权限控制、签字审计；是否需独立复核人由评审决定，不默认为已有能力。
- 证据失联/敏感信息：应对=脱敏、离线备份、哈希抽验、引用中禁存凭据；保留期未定会阻塞正式冻结。
- D1 迁移/快照增长：应对=本地演练、分批对账、应用层快照大小限额、容量监控；不把证据正文塞进 snapshot_json。
- 工时（个人维护、首期实现，含独立验证）：线上只读盘点与迁移演练4h；数据模型与回填6h；版本/基线/隔离API8h；轮次/三态/对比8h。
- 页面用例/功能点/执行交互8h；报告快照/批准冻结/HTML+JSON+打印6h；证据manifest与审计3h；兼容接口/导出3h；独立测试与授权真网验收6h。
- 合计52h，另预留历史数据问题8h（总预算60h）；不含人工编写/映射全部用例、专用PDF引擎、电子签名、外部归档建设。理由：数据清理规模目前待核实。

## 依据
- 本地源码，核对2026-11-13：migration_tc_version_20261023.sql:1-2 原文“NULL 保留存量含义，不回填”；支撑保留未知历史、不宣称缺少版本字段。
- 本地源码，核对2026-11-13：migration_tc_approve_20261017.sql:2-3 原文“ADD COLUMN approved_by”“ADD COLUMN approved_at”；支撑复用现有批准人时间。
- 本地源码，核对2026-11-13：Worker:1441 原文“ON CONFLICT (tc_id, release_id) DO UPDATE”；支撑拆轮并停止覆盖。
- 本地源码，核对2026-11-13：schema.sql:68/94 原文“req_id INTEGER NOT NULL REFERENCES requirements(id)”；支撑附件/事件不能直接挂回归资产。
- 本地说明，核对2026-11-13：README.md:31 原文“仅图片 png/jpg/webp/gif，单张 ≤2MB、每单 ≤3 张”；支撑站点仅保存大证据引用。
- 用户预核口径，接收2026-11-13：原文“DIFF 必须签字确认，否则算 FAIL”“用例主键是功能点不是需求号”；支撑门禁及功能点设计；业务文档未重复读取，线上状态未取到。

## 与现有实现的冲突点清单（file:line，相对项目根目录）
- data/migration_r5r6_testcases_20261017.sql:8；dist/testcases.html:121：related_req 单关联且页面按需求分组→保留追溯，主入口改功能点多对多。
- data/migration_r5r6_testcases_20261017.sql:24：版本只存 steps_md→新增整版快照，历史缺失明确标记。
- data/migration_r5r6_testcases_20261017.sql:34、40；worker_src/_worker.js:1273、1441：无 diff、单次唯一且 upsert→扩三态、轮次唯一、历史不可覆盖。
- data/migration_tc_version_20261023.sql:2；worker_src/_worker.js:1440：已有 tc_version 但执行取当前版→改为锁定基线版，旧 NULL 不补造。
- data/migration_tc_approve_20261017.sql:2；worker_src/_worker.js:1374、1404：批准仅在用例表且编辑清空→版本级批准另存，旧字段继续表示工作副本。
- worker_src/_worker.js:1417、308、1252：用例/项目可级联删执行，版本删除只查旧执行→新增资产引用保护，归档替代硬删除。
- schema.sql:68、94；worker_src/_worker.js:1436：附件/事件绑需求、ev_ref 截60字符→保留旧职能，增加独立证据引用与审计表。
- data/migration_docs_20261017.sql:4、17；README.md:48：有 docs/doc_versions 且说明出现报告ID，本地未见 reports 建表/API→新增 regression_reports，既有报告身份与线上状态待核实。
## CP-3 2026-11-13 17:32 CST 已追加完整A—G方案、四项决策、迁移顺序与逐行冲突依据；未执行任何实现或线上操作。
## CP-4 2026-11-13 17:29:22 CST 已检查A—G覆盖与文件范围，全文123行（≤200）；git状态仅新增指定文档。CP-3手填17:32有误，其实际完成时间早于本检查，以本行实测时间为准。
