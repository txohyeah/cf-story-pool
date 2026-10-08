#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入语雀 v1.5 清单（20260831.md）到 cf-story-pool。

映射规则（2026-10-08 与用户对齐）：
- 打勾 ✓ → 状态 fixed（已开发完成，未测试）；没打勾 → confirmed（已确认）
- 子任务勾选 → 工作项清单 checklist（@童晓→xiao，@周斌→zhoubin；勾=done）
- 性质标签 → tags；"紧急" → urgency=urgent；全部加 v1.5 + PC端/PDA端 标签
- 项目 = be-trial；提单人 = xiao（登录账号）；划掉的条目不导入；图片不处理
用法：python3 scripts/import_yuque_v15.py [--dry-run]
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    import certifi
    OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(
        context=urllib.request.create_default_context(cafile=certifi.where())))
except Exception:  # pragma: no cover
    OPENER = urllib.request.build_opener()

BASE = 'https://cf-story-pool.pages.dev'
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(PROJ))  # workspace 根（.secrets 所在）
PASS_FILE = os.path.join(ROOT, '.secrets', 'story_pool_pass_xiao')
STATE_FILE = os.path.join(PROJ, 'data', 'import_v15_state.json')
COOKIE_NAME = 'storypool_auth'
UA = {'User-Agent': 'storypool-import/1.0'}

XIAO, ZHOUBIN = 'xiao', 'zhoubin'
T_FIXED, T_CONF = 'fixed', 'confirmed'


def http(method, path, body=None, cookie=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(UA)
    if data is not None:
        headers['Content-Type'] = 'application/json'
    if cookie:
        headers['Cookie'] = cookie
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    last_err = None
    for attempt in range(3):
        try:
            with OPENER.open(req, timeout=40) as resp:
                return resp.status, dict(resp.headers), resp.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode('utf-8', 'replace')
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError('HTTP %s %s 失败: %s' % (method, path, last_err))


def I(t, ty='req', tg=(), st=T_CONF, u=None, d='', ck=()):
    return {'t': t, 'ty': ty, 'tg': list(tg), 'st': st, 'u': u, 'd': d, 'ck': list(ck)}


P, Z = XIAO, ZHOUBIN

# ================= PC Web（PC端） =================
PC_ITEMS = [
    I('项目配置 - 申办方 改成 申办者', tg=['政策要求'], st=T_FIXED, d='跟进：周斌。'),
    I('受试者 -> 试验参与者', tg=['政策要求'], st=T_FIXED, d='跟进：周斌。'),
    I('错误提示不友好，需维护一套 error code，由前端对照 code 输出对应提示', ty='opt', tg=['其他'],
      d='维护一套 error code，前端对照 code 输出对应的提示文案。',
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('菜单可以支持移动到某个目录下面', tg=['其他'], d='提出/跟进：周斌。'),
    I('PDA 重要节点判断出错需进行错误语音提示', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('模拟的项目可以删除，开始的项目只能作废', tg=['采集完善'], st=T_FIXED, d='跟进：童晓。'),
    I('项目配置：餐后和空腹可能是两个时间线，需要考虑下设计', u='urgent', tg=['采集完善'],
      ck=[('后端代码', P, True), ('周斌侧', Z, True), ('迁移脚本与验证', P, True)]),
    I('申办方可以创建字典，下次直接选择', tg=['采集完善'],
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('修改给药时间之后，依赖给药时间的后续数据一起改变', tg=['采集完善'],
      d='原文："我配好了，但是给药排期提前了"，希望修改给药时间之后，后面的数据一起改变（依赖给药时间的部分）。',
      ck=[('童晓侧（待测试，应该已经完成）', P, True), ('可能需要前端刷新下数据', Z, False)]),
    I('批次可以批量删除', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('受试者档案信息可以直接关联出来（等王鑫老师提供）', tg=['智能化'],
      d='等王鑫老师提供，后面的项目，受试者档案信息，可以直接关联出来。',
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('从模板创建事件，需要可以选择覆盖 or 追加（用于加一些小的事件模块）', u='urgent', tg=['采集完善'],
      d='提出/跟进：周斌。'),
    I('事件配置：问题输入框可否显示完整（对照模板中的问题，看不清当前对的是哪个问题）', u='urgent', tg=['采集完善'],
      d='提出/跟进：周斌。'),
    I('事件配置：表单中的问题需要可以上下移动位置（最好通过拖拉的方式）', u='urgent', tg=['采集完善'],
      d='提出/跟进：周斌。'),
    I('事件配置：拖拉调整事件顺序', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('事件配置：字段可以复制上面的题目（如体格检查，复制下来只需改字段名称），或者每个事件做一个模板？', tg=['采集完善'],
      d='提出/跟进：周斌。'),
    I('事件配置：可以选择显示时间的精度，默认秒', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('事件配置：问题需要可以配置为必填项', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('入排标准：提供文本框输入入排标准，按回车/换行符拆分自动生成记录', u='urgent', tg=['采集完善'],
      d='原文：需要一个模板（就少量需要改造下）—— 可改成提供一个文本框供输入入排标准，按回车或换行符来拆分，自动生成对应的入排标准记录。',
      ck=[('周斌侧', Z, True), ('童晓侧', P, True)]),
    I('入排标准：可以拖拽调整顺序，序号自动变动', u='urgent', tg=['采集完善'],
      ck=[('周斌侧', Z, True), ('童晓侧', P, True)]),
    I('入排标准：默认值可以不输入，即必须医生选择', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('入排标准：可以关联采集事件，自动判断是否符合', tg=['智能化'],
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('入排标准：两个排序输入删除，直接在列表处完成排序', u='urgent', tg=['采集完善'],
      d='（原语雀条目附截图，指代入排标准的两个排序输入框）',
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('电脑端的表单配置可以支持表格：疾病、用药', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('项目绑定人员（不一定需要了？？）', tg=['采集完善'],
      d='原文：似乎有下面的功能就可以快速的添加人员了。',
      ck=[('增加一个excel的模板下载和导入功能，若人员不存在，则需要提示一下哪些人不存在', None, False),
          ('可以按照担任角色进行排序', None, False)]),
    I('项目配置 - 人员绑定添加弹框加角色过滤条件，支持按角色多选批量添加', tg=['采集完善'],
      d='🚩 原文备注：好像有问题，QC 角色加载不出来。原文：在人员绑定列表那边的那个添加弹框，可以就是加一个过滤条件，'
        '就把这个弹框改复杂一点。比如说根据角色，然后一下子把护士全列出来，然后根据护士去多选，多选之后几个人一起添加进去。提出/跟进：周斌。'),
    I('核对登记加年龄筛选规则 + PDA 端显示', tg=['智能化'],
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('体征/基础事件规则支持复测次数与筛选通过判定 + PDA 显示（合并为可人为判定筛选失败）', tg=['智能化'],
      d='原文：体征事件 - 规则里面还需要加一个就是需复测的次数。比如说，血压高，三次复测失败，也要变成未通过 '
        '+ 基础事件，也需要判断是否筛选通过的规则 + PDA 端显示 ==> 合并为，可以人为判定为筛选失败。',
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('事件模板里面现在不可以改权限信息', tg=['其他'], d='提出/跟进：周斌。'),
    I('样本管理的冻存盒需要关联到具体的项目（不然冰箱里都是 DCH_001）', u='urgent', tg=['采集完善'],
      st=T_FIXED, d='跟进：童晓。'),
    I('样本管理覆盖导入时做全量覆盖导入', u='urgent', tg=['采集完善'], st=T_FIXED, d='跟进：童晓。'),
    I('保存批次时按已存在采样管/冻存管标签判断，导入过则提醒"需要重新导入标签"', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('项目配置 - 周期批次计划列表支持排序（低优先级）', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('两个组的开始给药时间可能不是同一天（9.5 与 9.10），两个项目可以关联同一个项目编号？', tg=['edc导出']),
    I('EDC 对接（excel 方式，每次对应列进行映射）', tg=['edc导出']),
    I('项目完成之后，导出需要 PI 进行一个签字'),
    I('密码强校验配置开关：数字、大写字母、小写字母、特殊字符、最短几位', tg=['政策要求'],
      d='（原文"不满足是否需要强制修改的开关"部分已划掉，不纳入范围）',
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('项目配置时按用户角色选定本次项目中的真正权限', u='urgent', tg=['采集完善'], st=T_FIXED, d='跟进：童晓。'),
    I('用户管理 - 增加角色、公司字段的显示和筛选', tg=['其他'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('按钮级别权限（PC + PDA）', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('采集事件 PC 端显示 + 采集权限管理', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('药杯条码修改', tg=['采集完善'], st=T_FIXED, d='跟进：童晓。'),
    I('药杯打印加条件，可按周期筛选', tg=['采集完善'],
      d='（原文"和研究组"部分已划掉）',
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('打印预览无法回调用户点的是取消还是打印，暂默认按打印处理，需再确认优化', ty='opt', tg=['采集完善'],
      d='提出/跟进：周斌。'),
    I('bug：从模板创建周期失败，groupIds cannot be empty', ty='bug', st=T_FIXED),
    I('bug：重新模拟出现了一个 sql 报错', ty='bug', st=T_FIXED, d='跟进：童晓。'),
    I('bug：配置项目批次时重新切回页面再点下一步会提示没有配置完全（须重点第二周期）', ty='bug', st=T_FIXED,
      d='跟进：周斌。原文：点第一个已经配好的，重新切到这个页面，再点下一步，会提示没有配置完全。'
        '但是其实第二周期已经配置完全，现在必须得点一下第二周期。\n\n'
        '已修复明细（原文表格）：\n\n'
        '| 页面场景 | 修复前 | 修复后 |\n| --- | --- | --- |\n'
        '| 批次全部配好后点「下一步」 | 恒报「请维护所有周期组的批次计划」，被卡死在本步 | 配置完整即正常进入下一步 |\n'
        '| 事件只关联部分周期（如禁食禁水仅第一周期） | 第二周期被要求维护该事件的批次，但页面根本不提供入口，永远过不去 | 不再要求，校验只认事件真正关联的组合 |\n'
        '| 未逐个点开所有组-周期 Tab | 没点开过的 Tab 即使已配置，下一步照样误报，被迫逐个 Tab 点一遍 | 进入步骤即全量加载数据，只看第一个 Tab 也能正常通过 |\n'
        '| 某组×周期无任何关联事件（空 Tab） | 落在这种 Tab 直接点下一步会误报 | 正常显示无卡片的空状态，不影响校验 |'),
    I('bug：从 AE 详情新增/关联 CM 时，关联 AE 选择框需同时显示 termName（当前仅显示 aeNo）', ty='bug',
      st=T_FIXED, d='提出/跟进：周斌。'),
    I('bug：重新模拟的数据清理遗漏了多人采集任务表', ty='bug', st=T_FIXED, d='跟进：童晓。'),
    I('bug：样本管理 - 样本任务 - 接收节点的任务状态应显示为已接收', ty='bug', st=T_FIXED, d='跟进：童晓。'),
    I('bug：配置字段选了文本显示，但 PDA 没有显示出来', ty='bug', d='提出/跟进：周斌。'),
    I('受试者管理筛选结果加"未判断"枚举', tg=['采集完善'],
      d='原文：如未判断，就是现在只有通过和未通过，还是需要有一个没有判断的。',
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('受试者管理 - 撤销评估结果的操作（需求待确认）',
      d='原文：【？没太明白】是不是需要一个撤销评估结果的操作？'),
    I('试验参与者筛选评估弹框中显示参与者基本信息', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('药品分装、药品留样的记录支持修改',
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('样本操作需要在 PC 端可以修改，主要是时间', u='urgent', tg=['采集完善'],
      ck=[('童晓侧（已经支持，无需改动）', P, True), ('周斌侧', Z, False)]),
    I('样本核对权限可配置 - 是否需要核对人', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('PC 和 PDA 的操作人都写成对应的人（如转运人、离心人）', u='urgent', tg=['采集完善'],
      d='提出/跟进：周斌。'),
    I('NCS 线索可以批量操作', tg=['采集完善'],
      d='（原语雀条目附截图：AE 线索列表）',
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('更好地展示 v1 采集的列表', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('采集记录可以修改（包括审计字段）', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('项目配置校验规则', tg=['智能化'], d='跟进：童晓。'),
    I('项目配置重点字段校验', tg=['智能化'],
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('PC 端可以查看设备操作记录，选择项目后自动带入项目时间', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('需要能打印采样管、冻存管条码',
      d='20260920 后新增。',
      ck=[('童晓侧（之前已经满足了）', P, True), ('周斌侧', Z, False)]),
]

# ================= PDA（PDA端） =================
PDA_ITEMS = [
    I('bug：体征采集 - 读取血压计报错：获取血压数据超时，请重新测量（偶尔时不时出现）', ty='bug', d='提出/跟进：周斌。'),
    I('核对人和登录人不能是同一个人', u='urgent', tg=['采集完善'], st=T_FIXED),
    I('内网状态下绑定血压计', tg=['其他']),
    I('逐个分样改为保存时间点（需兼容批量的时间范围）', u='urgent', tg=['采集完善'],
      d='原文：逐个分样其实不需要开始结束，这个时间段是指整个批次分样完成的时间 —— 根据分析，分样基本在 30s 之内完成，'
        '对于保存时间段的意义不大，但是代价很大，需要用户在一个试验中多点百次，甚至数千次。因此，改为逐个保存改为保存时间点。'
        '但是需要兼容批量的时间范围。',
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('接受的时候需要记录送样人', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('样本管理页面批次上加完成状态', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('核对人现在无法后面补', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('显示暂存与冻存的过程记录（加入冻存盒状态的视图）', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('分样不匹配语音提示', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('离心、分样等历史记录弹框中显示操作人', u='urgent', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('bug：样本管理 - 脱落受试者未分样未接收但冻存管计数不对', ty='bug', st=T_FIXED,
      d='跟进：童晓。原文：因为我们脱落了一个，我们也没有给他分样，也没给他接收。但它现在显示是共30个冻存管，那就是不对的。'),
    I('留样不需要与周期关联', st=T_FIXED, ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('备用药杯的分装也需要校验 RT 类型', st=T_FIXED, d='跟进：童晓。'),
    I('bug：体征修改 collectUser 不能为空', ty='bug', st=T_FIXED, d='提出/跟进：周斌。'),
    I('判读需要单独记录判断人、判断时间', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('判读的开始/结束/判断时需要记录更多字段（如结束时一般需拍照）', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('体重需记录小数点后一位，整数也不能省略（36.0 不能显示为 36）', u='urgent', tg=['采集完善'],
      d='提出/跟进：周斌。'),
    I('采集事件 PDA 端可手动判定筛选失败原因，可撤回', tg=['智能化'],
      d='原文：每个采集事件 PDA 端，可以手动判定因为什么筛选失败。可以撤回。需要原因。',
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('bug：宣教 - 签字管理 - 性别未显示（未返回该字段，可考虑直接移除不显示）', ty='bug', st=T_FIXED,
      d='提出/跟进：周斌。'),
    I('bug：basic 根据 autoEnd 配置的结束时间未到但事件已显示出来', ty='bug', st=T_FIXED,
      d='方案：后端直接隐藏或前端根据配置显示【将于 xxx 自动结束】。',
      ck=[('周斌侧（同时需处理下批次表单默认值覆盖事件级配置）', Z, True),
          ('童晓侧（批次配置需要提供下）', P, True)]),
    I('bug：体征或基础事件配置了 AE 自动线索规则，PDA 端命中规则的受试者记录未显示 CS 标记', ty='bug',
      st=T_FIXED, ck=[('童晓侧', P, True), ('周斌侧', Z, True)]),
    I('逐个分样弹框中分样成功后不需要关闭弹框', st=T_FIXED,
      d='原文：因为一般操作时候会不断逐个进行分样操作，所以分样成功后不需要关闭弹框。提出/跟进：周斌。'),
    I('转运页面详情不需要显示货架信息', st=T_FIXED, d='跟进：童晓。'),
    I('转运页面详情"尚未放置于冰箱中"改成"已转运"', st=T_FIXED),
    I('受试者视图里已退出的受试者需要标识', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('受试者视图可按筛选号、随机号排序', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('basic 判读事件取消切换受试者时的切换提醒弹框', st=T_FIXED, d='提出/跟进：周斌。'),
    I('bug：basic 编辑页切换卡顿', ty='bug', st=T_FIXED, d='提出/跟进：周斌。'),
    I('修订记录变更内容中字段需显示字段名而不是字段 code', u='urgent', tg=['采集完善'], st=T_FIXED),
    I('bug：知情同意页面未签约参与者点进去变成修改', ty='bug',
      d='原文：有一个参与者，他没有签过，但是点进去那个页面变成了修改（需要拿到该受试者的数据）'
        '—— 当时 PDA 里面，每个都这样。（备注：看看能不能重现，不能就先放放）提出/跟进：周斌。'),
    I('知情同意签字时间 - 受试者与研究人员需要有时间差', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('筛败受试者在名单上显示红色标记', tg=['智能化'],
      d='原文：后续如果有筛败的，可以所有的名字上都显示红色下。',
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('bug：多台机器一起上传图片就会很卡（疑似机器/网络问题）', ty='bug',
      d='原文：可能是 3 号机器的问题，今天更新的时候下载 wgt 超级慢；也可能就是网络问题，第一个项目的时候没那么卡。'),
    I('紧急联系人页面也显示受试者自己的信息', u='urgent', tg=['采集完善'], st=T_FIXED),
    I('bug：照片重新拍了一张但仍一直显示原来的照片', ty='bug', st=T_FIXED),
    I('bug：扫码枪扫描事件结果确认，扫的是 S042 但保存的数据变成了 S047', ty='bug', st=T_FIXED),
    I('bug：扫码后页面不跟随定位，需退出重进才能定位到人', ty='bug', st=T_FIXED,
      d='与上一条同场景。原文：就停在这个页面，这个筛选号也在里面，然后扫那个 S047，'
        '这个页面一直不动，要把这个页面退出，再进入扫了，才能定位到那个人。'),
    I('subject-list 扫码或读卡定位后将受试者滚动到可见位置', st=T_FIXED, d='提出/跟进：周斌。'),
    I('bug：实验室检查（basic 事件）第一次未出弹框直接保存未成功，到第 3 遍才行', ty='bug', st=T_FIXED,
      d='提出/跟进：周斌。'),
    I('身份证读卡偶尔多次读取失败，看能否优化插件', ty='bug', tg=['其他'], d='提出/跟进：周斌。'),
    I('basic 多人操作优化', u='urgent', tg=['采集完善'],
      ck=[('开始和结束等操作有二次确认，需点两次导致实际时间有误差（在采集记录支持修改时间之后，移除二次确认）', Z, False),
          ('页面加一个下一组，直接把页面清空掉，就不用退出再进来一遍', Z, False),
          ('退出多人操作时刷新 basic 页面（现在需要手动刷新才能看到最新数据）', Z, True)]),
    I('修订记录弹框中图片更改需显示图片而不是链接', u='urgent', tg=['采集完善'], st=T_FIXED,
      d='提出/跟进：周斌。'),
    I('尿检试纸作废后支持重新开始-结束-判读（作为修改的一种，需输入理由）', u='urgent', tg=['采集完善'],
      d='原文：尿检的时候已经记录了，但是试纸废了，需要重新开始-结束-判读'
        '（点击修改之后，选择重新开始，也算是一种修改，需要输入理由。）提出/跟进：周斌。'),
    I('多人判读事件采用"按受试者记录状态驱动"的操作模式', u='urgent', tg=['采集完善'],
      d='原文：多人判读事件采用"按受试者记录状态驱动"的操作模式，不再依赖跨阶段的进行中任务。',
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('采集记录支持批量修改时间（批量操作/多人操作后的记录）', u='urgent', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('bug：basic 页面极限情况下图片未上传完成就能提交导致图片未带上', ty='bug', d='提出/跟进：周斌。'),
    I('bug：PDA 实测 basic 表单图片上传未完成时仍可点击保存', ty='bug',
      d='与上一条同场景。原文：再分析下。提出/跟进：周斌。'),
    I('读秒倒计时加入语音播报', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('分装等非采集事件的页面补按钮权限控制', u='urgent', tg=['采集完善'],
      ck=[('童晓侧（通过按钮级别权限控制，后端暂时不需要改造）', P, True), ('周斌侧', Z, False)]),
    I('bug：按批次的采集计划在模拟时修改后，正式开始时丢失计划', ty='bug', st=T_FIXED, d='跟进：童晓。'),
    I('设备记录做成分页（太多会卡死，如冰箱开关门记录）', ty='opt', tg=['其他'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('bug：体征采集记录应判断为 CS 但判断为 NCS', ty='bug', st=T_FIXED, d='跟进：童晓。'),
    I('体征事件 - 体温字段仅开放弹框输入，禁用原输入框输入', tg=['采集完善'], d='提出/跟进：周斌。'),
    I('签到需要显示签到时候登录的用户', tg=['采集完善'],
      ck=[('童晓侧', P, True), ('周斌侧', Z, False)]),
    I('bug：紧急联系人信息修改后仍显示旧的', ty='bug', st=T_FIXED, d='跟进：童晓。'),
    I('bug：紧急联系人状态不对', ty='bug', st=T_FIXED, d='跟进：童晓。'),
]

# ================= 其他（无端标签） =================
OTHER_ITEMS = [
    I('采集的数据记录对应设备，设备维护对应字典',
      d='20260805 记录。',
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('CRA 只读查看采集数据（采样事件加过滤按钮，默认仅 PC 端采集）',
      d='原文：CRA 相关的功能，对于采集数据的只读查看（在采样事件这里加一个过滤按钮，仅 PC 端采集，默认选中。'
        '取消勾选以后就是全部可以看到）。子项：按钮级别控制（周斌）。'),
    I('【仅测试】受试者可以在任何时刻选择退出', tg=['仅测试'], d='跟进：童晓。'),
    I('实施前培训：梳理哪些环节需要新增人手、哪些可以节约人手', tg=['实施前培训'],
      d='原文：哪些环节需要新增人手，哪些可以节约人手。避免项目开始后来不及。'
        '多花时间如配置人员、分样、采血等。节约时间如 CRC 导出导入 EDC。纸质手写等。'),
    I('SOP 里写明体重秤检查：每次项目开始时检查设备是否连接',
      d='原文：在 SOP 里需要写一下体重秤，每次项目开始的时候都需要检查一下设备有没有连接上。'),
    I('试验开始后部分配置支持修改（如新增事件不能删除、修改默认值）',
      d='原文（疑问）：试验开始后的一些配置也是可以修改的？比如新增一个事件，但是不能删除，比如说修改下默认值？',
      ck=[('童晓侧', P, False), ('周斌侧', Z, False)]),
    I('数据定时备份 / 后备系统',
      d='原文：【？】数据定时备份，后备系统 - 周雨吉。'),
    I('充电底座型号（待确认的设备事项）',
      d='原文：【？】充电底座型号。'),
]

ITEMS = ([(x, 'PC端') for x in PC_ITEMS]
         + [(x, 'PDA端') for x in PDA_ITEMS]
         + [(x, '') for x in OTHER_ITEMS])


def main():
    dry = '--dry-run' in sys.argv
    n_fixed = sum(1 for x, _ in ITEMS if x['st'] == T_FIXED)
    ck_total = sum(len(x['ck']) for x, _ in ITEMS)
    print('条目 %d 条（fixed %d / confirmed %d），工作项 %d 项' % (len(ITEMS), n_fixed, len(ITEMS) - n_fixed, ck_total))
    if dry:
        for x, sec in ITEMS:
            print('[%s] %s | %-5s | %-14s | %s' % (
                x['st'], '紧急' if x['u'] else '    ', sec or '-',
                '/'.join(x['tg']) or '-', x['t']))
        return

    password = open(PASS_FILE).read().strip()
    s, h, raw = http('POST', '/api/login', {'username': XIAO, 'password': password})
    if s != 200:
        print('登录失败 HTTP %s: %s' % (s, raw[:200]));  sys.exit(1)
    m = re.search(COOKIE_NAME + '=([^;]+)', h.get('Set-Cookie', ''))
    if not m:
        print('登录响应无 cookie');  sys.exit(1)
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

    for x, sec in ITEMS:
        title = x['t']
        tags = ['v1.5'] + x['tg'] + ([sec] if sec else [])
        st = state.get(title)
        if st and st.get('ck', 0) >= len(x['ck']):
            skip_cnt += 1
            continue
        try:
            if not st:
                s, _h, raw = http('POST', '/api/requirements', {
                    'project_id': proj['id'], 'title': title,
                    'description': x['d'], 'type': x['ty'],
                    'urgency': x['u'] or 'normal', 'tags': tags}, cookie)
                if s != 200:
                    print('!! 创建失败 HTTP %s：%s | %s' % (s, title, raw[:120]))
                    break
                rid = json.loads(raw)['id']
                s, _h, raw = http('PATCH', '/api/requirements/%d' % rid,
                                  {'op': 'status', 'status': x['st'],
                                   'note': '导入自语雀 v1.5 清单（20260831）'}, cookie)
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
        if ok_cnt % 10 == 0:
            json.dump(state, open(STATE_FILE, 'w'), ensure_ascii=False, indent=1)
            print('... 已导入 %d 条' % ok_cnt)
        time.sleep(0.12)

    json.dump(state, open(STATE_FILE, 'w'), ensure_ascii=False, indent=1)
    print('\n本轮导入 %d 条，续传跳过 %d 条；状态文件：%s' % (ok_cnt, skip_cnt, STATE_FILE))


if __name__ == '__main__':
    main()
