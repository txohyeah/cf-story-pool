#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入《BE数据采集智能化功能设计》（甲方 docx）对账结论到 cf-story-pool。

映射规则（2026-10-13 与用户对齐）：
- 按功能点拆条：14 条 confirmed + 3 条评审不采纳（closed 留痕）
- 来源标签：智能设计v1（新建，性质同"语雀迁移"）；全部加 智能化 + 阶段标签（系统配置/筛选期/研究期/结题期）
- 端标签：PC端 / PDA端（已有）；外部对接（新建，LIS 条目用）；硬件依赖暂不建（身份证读卡已实现，无落点条目）
- 不重叠处理：复测次数上限已在 #39 不重导；筛败语音在描述关联 #11/#111；入排自动判别关联 #33
- 工作项：confirmed 条目统一挂 后端任务(@xiao) / 前端任务(@zhoubin)，todo
- 项目 = be-trial；提单人 = xiao；channel 由 API 默认
用法：python3 scripts/import_smart_design_v1.py [--dry-run]
"""
import json
import os
import sys
import time

import import_yuque_v15 as base

BASE = base.BASE
http = base.http
COOKIE_NAME = base.COOKIE_NAME
PASS_FILE = base.PASS_FILE
# 2026-10-09 xiao 启用自助改密码后，新密码存于 story_pool_pass_xiao_custom，优先使用
_PASS_CUSTOM = os.path.join(os.path.dirname(PASS_FILE), 'story_pool_pass_xiao_custom')
if os.path.exists(_PASS_CUSTOM):
    PASS_FILE = _PASS_CUSTOM
STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'import_smart_design_v1_state.json')
XIAO, ZHOUBIN = base.XIAO, base.ZHOUBIN
T_CONF, T_CLOSED = 'confirmed', 'closed'

NOTE_CONF = '导入自《BE数据采集智能化功能设计》（2026-10-13 评审对齐）'
NOTE_CLOSED = '评审不采纳（2026-10-13 对齐，理由见描述）'


def I(t, tg, d, st=T_CONF, ck=True):
    return {'t': t, 'tg': tg, 'd': d, 'st': st,
            'ck': [('后端任务', XIAO, False), ('前端任务', ZHOUBIN, False)] if ck else []}


SRC = ['智能化', '智能设计v1']

ITEMS = [
    # ================= confirmed（14 条） =================
    I('研究团队人员档案管理（按专业岗位建档：简历/学历/职称/职务/联系方式）+ 电子签名留样',
      SRC + ['系统配置', 'PC端'],
      '文档原文：按专业设置研究医生、研究护士、药师、医技人员、营养师、CRC、CRA 等角色；为所有人员建立人员档案，'
      '内容包括简历、姓名、出生年月、专业、学历、职称、职务、电话、邮箱等；建立人员电子签名留样。\n\n'
      '现状（2026-10-13 对账）：现有系统管理仅用户账号与角色，无专业岗位档案字段，无电子签名留样。'
      '与池内「受试者档案信息关联」条目不同：本条是研究团队成员档案，非受试者档案。\n\n'
      '验收要点：人员档案维护（上述字段）+ 电子签名留样采集/更换；与项目人员授权联动。'),
    I('岗位权限矩阵细化：12 类角色操作权限逐项落地（PI/SubI/QA/研究医生/护士/药师/药物管理员/质控员/资料管理员/CRC/CRA/系统管理员）',
      SRC + ['系统配置', 'PC端', 'PDA端'],
      '文档原文：权限管理覆盖系统管理员、PI、质量保证员、SubI、研究医生、研究护士、研究药师、药物管理员、'
      '质量控制员、资料管理员、CRC、CRA 十二类角色的操作权限矩阵。\n\n'
      '现状：Sa-Token+动态路由+项目成员角色框架已有，按钮级权限在做（池内已有相关条目）；12 岗位矩阵未逐项对照落地。\n\n'
      '验收要点：按文档矩阵逐项核对角色-权限点，PC/PDA 端均按角色生效。'),
    I('设备台账：设备清单（名称/规格/型号/编号/位置/校准时间/校准有效期）+ 设备档案 + 校准到期前 3 个月自动提醒',
      SRC + ['系统配置', 'PC端'],
      '文档原文：设备出入库指定专人管理；设备清单一览表（名称、规格、型号、编号、部门位置、校准时间、校准有效期，'
      '到期前 3 个月自动提醒）；每个设备建立设备档案。\n\n'
      '现状（2026-10-13 对账）：后端仅有设备操作记录（出入库/开关门留痕）与 PC 端操作记录页；'
      '无设备清单实体、无校准字段、无到期提醒。PDA 设备页为蓝牙血压计/体重秤连接管理，非台账。\n\n'
      '验收要点：设备台账维护 + 校准有效期到期前 3 个月提醒（列表高亮/站内提醒）。'),
    I('系统配置：管理员上传系统验证报告',
      SRC + ['系统配置', 'PC端'],
      '文档原文：系统管理员可上传系统验证报告。\n\n'
      '现状：无对应入口（系统内记录完整性证明非验证报告）。\n\n'
      '验收要点：管理员上传/查看/下载验证报告附件。'),
    I('筛选号按知情同意最后签署时间先后自动生成',
      SRC + ['筛选期', 'PC端', 'PDA端'],
      '文档原文：筛选号应严格按照知情同意时间（医生与参与者最后签署时间）的先后顺序自动生成。\n\n'
      '现状：筛选号体系已在（筛选/签到/入组链路）；按最后签署时间排序生成的规则未见显式实现，需确证/补齐。'
      '关联：池内已有「知情同意签字时间-受试者与研究人员需有时间差」。\n\n'
      '验收要点：同批多人签署时，筛选号严格按最后签署时间升序分配，可追溯。'),
    I('筛选期流程门禁：前序流程未完成禁止进入下一流程（同环节内不限先后）',
      SRC + ['筛选期', 'PC端', 'PDA端'],
      '文档原文：系统需要严格的流程控制，不允许越流程开展，如前一流程未完成应无法进入下一流程；'
      '同一流程中不同环节可不受先后限制。\n\n'
      '现状：签到签离/查重等环节已有；未见通用的环节依赖门禁。设计注意：需防「过死」，异常解锁须留痕。\n\n'
      '验收要点：配置环节依赖后，未完成前序时后续环节不可开始并有明确提示；同环节内不限制先后。'),
    I('筛选失败 PDA 文字+语音双重提醒（任一环节判不通过时同步提示）',
      SRC + ['筛选期', 'PDA端'],
      '文档原文：筛选期任一流程不通过需同步文字和语音双重提醒「筛选失败」；问诊/体格检查触出入排标准时即提醒。\n\n'
      '现状（2026-10-13 对账）：PDA 语音基建已有（预生成音频片段方案，PDA 无 TTS 引擎）；'
      'PDA 已支持手动判定筛选失败（池内「采集事件 PDA 端可手动判定筛选失败原因」）、筛败红标；'
      '「筛选失败」固定短语语音片段需新增；入排自动判不通过联动池内「入排标准关联采集事件自动判断」。\n\n'
      '验收要点：任一环节判定不通过时，PDA 弹字+语音同步播报「筛选失败」。'),
    I('检验检查结果自动获取（LIS 对接，按医院条件可选）+ 初审结果自动汇总',
      SRC + ['筛选期', 'PC端', '外部对接'],
      '文档原文：入排初审自动获取检验检查结果数据，并自动生成初审结果。\n\n'
      '现状：无 LIS/仪器对接；实验室检查走 basic 事件人工录入；医院内网接口审批周期长。\n\n'
      '建议口径（2026-10-13 对齐）：LIS 自动对接按医院实施条件做可选项；'
      '先行做「初审结果自动汇总」（基于已录入数据自动生成初审视图）；检验单拍照附件已具备作为兜底。'),
    I('鉴认代码表自动生成 + PI 电子签名导出（真名与代码对照，GCP 必备文件）',
      SRC + ['筛选期', 'PC端'],
      '文档原文：参与者鉴认代码表（自动生成）。\n\n'
      '现状（2026-10-13 对账）：筛选号/随机号/受试者身份信息与随机号记录表全有，'
      '缺「生成鉴认代码表（姓名、身份证号与筛选号/随机号/鉴认代码对照）+ PI 电子签名 + 导出/打印」。\n\n'
      '验收要点：随机完成后一键生成，PI 电子签名后归档导出；仅授权角色可见。'),
    I('给药/密采轮次收尾：语音提醒 + 批量指纹电子签名（一次签署本轮本人全部记录）',
      SRC + ['研究期', 'PDA端'],
      '文档原文：给药全部结束，语音提醒确认指纹电子签名；一轮采血结束，语音提醒确认指纹电子签名。\n\n'
      '现状：给药/密采倒计时语音读秒已上线；指纹组件+采集签名鉴权+签名审计已有；'
      '缺「轮次收尾聚合本轮未签名记录，一次指纹绑定 N 条」的收尾交互。\n\n'
      '验收要点：一轮给药/密采结束语音提醒，执行人按指纹即批量签署本轮本人记录，签名审计可查。'),
    I('违背方案自动列表：超时间窗/时间逻辑/超权限/禁用药品食品自动识别',
      SRC + ['研究期', 'PC端'],
      '文档原文：对给药、采血、生命体征等操作错误或超时间窗、不符合时间逻辑关系、超权限操作、'
      '服用禁用药品或食物等自动识别生成违背方案列表。\n\n'
      '现状（2026-10-13 对账）：全库无违背方案模块；项目时间轴配置（判超窗）与权限体系（判超权限）已有基础。'
      '原「同一人并发 2 操作实时提醒」经评审不做，其时间戳重叠检查并入本条作为事后核查项。\n\n'
      '验收要点：按项目配置自动检测并生成违背列表，可筛选/导出/标注说明。'),
    I('AE 相关性判定辅助提示（时间关系等规则提示，不自动判定、不引导措辞）',
      SRC + ['研究期', 'PC端'],
      '文档原文：自动生成 AE/SAE 列表，并对 AE 相关性判定智能化建议。\n\n'
      '现状：AE/SAE 全生命周期+列表+线索机制已有，无需重做；相关性为人工录入字段。\n\n'
      '建议口径（2026-10-13 对齐）：只做规则提示（如与给药的时间关系、合并用药情况），供判定人参考；'
      '不自动填写、不引导措辞（核查责任考虑）。'),
    I('结题智能质控报告：按模板自动生成 9 维核查结果 + 质控人指纹签名',
      SRC + ['结题期', 'PC端'],
      '文档原文：按模板自动生成质控报告：核查数据准确性、完整性、及时性、一致性、合理性、操作时间逻辑、'
      '操作权限、访视完整性、设备时效性；质控人员全面审核后指纹电子签名。\n\n'
      '现状（2026-10-13 对账）：全库无质控模块；数据基础（记录/轨迹/权限/设备记录/时间轴）齐备。'
      '本质为规则引擎+报告模板，非 AI。\n\n'
      '验收要点：一键生成质控报告（9 维核查结果+明细），质控人确认后指纹签名归档。'),
    I('eCRF 分级批量签：SubI/QA 审核签 + PI 复审签（支持批量指纹）',
      SRC + ['结题期', 'PC端'],
      '文档原文：SubI 或 QA 对自动生成的 eCRF 审核确认后指纹电子签名（可批量）；PI 复审后指纹电子签名（可批量）。\n\n'
      '现状：eCRF 自动生成/导出/交付已建成（含批量 check 与指纹）；未见两级审核+批量签的角色化工作流。\n\n'
      '验收要点：两级角色流转，两级均支持批量指纹签署，签名记录可审计。'),
    I('PDA 单设备登录互踢：同一账号同时仅允许登录一台 PDA（文档规则 a）',
      SRC + ['研究期', 'PDA端'],
      '文档原文：同 1 个人不能同时登录 2 台 PDA。\n\n'
      '现状（2026-10-13 对账）：鉴权配置 is-concurrent=true，同一账号可同时在多台 PDA 登录'
      '（Sa-Token 按客户端类型区分 token，不互踢）；PDA 指纹录入已有「同一枚指纹被其他设备录入」的跨设备冲突检测可参考。\n\n'
      '验收要点：同一账号在新 PDA 登录时，旧 PDA 会话失效并给出明确提示；不影响同一账号 PC 端同时在线；'
      '断网重连/离线补录场景不误踢。'),
    # ================= closed（3 条，评审不采纳留痕） =================
    I('医生每日查房记录 + 护士每日 2 次交接班记录（建专门模块）',
      SRC + ['研究期', 'PC端', 'PDA端'],
      '文档原文：研究期医生每日 1 次查房记录；护理人员每日 2 次交接班记录。\n\n'
      '评审结论（2026-10-13 与开发负责人对齐）：不采纳，不建专门模块。理由：查房记录由医生病历记录（可加当日未写提醒）覆盖；'
      '交接班由登录/操作日志覆盖（谁在班、谁做了什么可完整追溯）；'
      '如医院 SOP 硬性要求纸质以外的交班记录，再评估轻量「交班小结」。',
      st=T_CLOSED, ck=False),
    I('同一人同步进行 2 个操作的实时文字+语音提醒确认（文档规则 b）',
      SRC + ['研究期', 'PDA端'],
      '文档原文：同 1 个人如出现同步进行 2 个操作时，需自动文字和语音提醒确认。\n\n'
      '评审结论（2026-10-13）：不采纳实时提醒。理由：并发场景主要源于同机多任务与离线补录，实时提醒价值有限且实现复杂；'
      '时间戳重叠检查并入「违背方案自动列表」作为事后核查。'
      '注意：当前鉴权配置 is-concurrent=true，同一账号可同时在两台 PDA 登录（文档规则 a 未实现），'
      '是否立项「PDA 单设备登录互踢」另行确认。',
      st=T_CLOSED, ck=False),
    I('给餐/饮水/如厕等 basic 事件专项扫码核对+语音播报',
      SRC + ['研究期', 'PDA端'],
      '文档原文：生命体征测量、饮水、如厕、活动、用餐等操作「要求同上」（PDA 扫码核对身份+文字语音提醒）。\n\n'
      '评审结论（2026-10-13）：不做专项开发。理由：给餐/饮水/如厕属 basic 可配置事件，事件与频次本身可配置；'
      '当前 basic 事件语音为固定行为（读秒播报），无项目级语音/扫码开关，如现场确需开关，走常规需求评估。',
      st=T_CLOSED, ck=False),
]


def main():
    dry = '--dry-run' in sys.argv
    n_conf = sum(1 for x in ITEMS if x['st'] == T_CONF)
    n_closed = sum(1 for x in ITEMS if x['st'] == T_CLOSED)
    print('条目 %d 条（confirmed %d / closed 不采纳 %d），工作项 %d 项' % (
        len(ITEMS), n_conf, n_closed, sum(len(x['ck']) for x in ITEMS)))
    if dry:
        for x in ITEMS:
            print('[%s] %-9s | %s' % (x['st'], '/'.join(x['tg']), x['t']))
        return

    password = open(PASS_FILE).read().strip()
    s, h, raw = http('POST', '/api/login', {'username': XIAO, 'password': password})
    if s != 200:
        print('登录失败 HTTP %s: %s' % (s, raw[:200])); sys.exit(1)
    m = __import__('re').search(COOKIE_NAME + '=([^;]+)', h.get('Set-Cookie', ''))
    if not m:
        print('登录响应无 cookie'); sys.exit(1)
    cookie = COOKIE_NAME + '=' + m.group(1)

    s, _h, raw = http('GET', '/api/bootstrap', cookie=cookie)
    b = json.loads(raw)
    users = {u['username']: u['id'] for u in b['users']}
    proj = next(p for p in b['projects'] if p['name'] == 'be-trial')
    uid = {XIAO: users[XIAO], ZHOUBIN: users[ZHOUBIN]}
    print('项目 be-trial #%s | xiao#%s zhoubin#%s' % (proj['id'], uid[XIAO], uid[ZHOUBIN]))

    state = {}
    if os.path.exists(STATE_FILE):
        state = json.load(open(STATE_FILE))
    ok_cnt = skip_cnt = 0

    for x in ITEMS:
        title = x['t']
        st = state.get(title)
        if st and st.get('ck', 0) >= len(x['ck']):
            skip_cnt += 1
            continue
        try:
            if not st:
                s, _h, raw = http('POST', '/api/requirements', {
                    'project_id': proj['id'], 'title': title,
                    'description': x['d'], 'type': 'req',
                    'urgency': 'normal', 'tags': x['tg']}, cookie)
                if s != 200:
                    print('!! 创建失败 HTTP %s：%s | %s' % (s, title, raw[:120]))
                    break
                rid = json.loads(raw)['id']
                note = NOTE_CONF if x['st'] == T_CONF else NOTE_CLOSED
                s, _h, raw = http('PATCH', '/api/requirements/%d' % rid,
                                  {'op': 'status', 'status': x['st'], 'note': note}, cookie)
                if s != 200:
                    print('!! 状态流转失败 HTTP %s：#%s %s' % (s, rid, title))
                st = state[title] = {'id': rid, 'ck': 0}
            rid = st['id']
            for content, assignee, done in x['ck'][st.get('ck', 0):]:
                body = {'content': content[:200]}
                if assignee:
                    body['assignee_id'] = uid[assignee]
                s, _h, raw = http('POST', '/api/requirements/%d/checklist' % rid, body, cookie)
                if s != 200:
                    print('!! 工作项创建失败 HTTP %s：#%s %s' % (s, rid, content[:40]))
                    break
                cid = json.loads(raw)['id']
                if done:
                    s, _h, raw = http('PATCH', '/api/checklist/%d' % cid, {'status': 'done'}, cookie)
                    if s != 200:
                        print('!! 工作项勾选失败 HTTP %s：#%s %s' % (s, rid, content[:40]))
                st['ck'] = st.get('ck', 0) + 1
        except RuntimeError as e:
            print('!! 网络异常，中断：%s | %s' % (title, e))
            break
        ok_cnt += 1
        time.sleep(0.12)

    json.dump(state, open(STATE_FILE, 'w'), ensure_ascii=False, indent=1)
    print('\n本轮导入 %d 条，续传跳过 %d 条；状态文件：%s' % (ok_cnt, skip_cnt, STATE_FILE))


if __name__ == '__main__':
    main()
