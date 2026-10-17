#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R8 docgen：从 cf-story-pool 取数生成 CSV 合规文档草稿（md）。

子命令：
  csv14   --project 3 --out DIR      CSV-14 问题登记与定期审查表（bug/需求台账+五维度统计）
  report  --project 3 --release 1 --out DIR   版本测试报告（执行记录+统计+用例全文）
  rtm     --project 3 --out DIR      需求追溯矩阵片段（需求↔用例双向）

输出 md 文件落 DIR（默认 projects/cf-story-pool/reports/），供润色/归档/转 docx。
凭据从 .secrets/story_pool_pass_xiao_custom 读取，不回显。
"""
import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.dirname(os.path.dirname(ROOT))
BASE = 'https://cf-story-pool.pages.dev'
OUT_DEFAULT = os.path.join(WS, 'projects', 'cf-story-pool', 'reports')

ST_CN = {'submitted': '待复现确认', 'confirmed': '已确认', 'scheduled': '已排期', 'fixed': '已修复',
         'verified': '已验证', 'closed': '关闭', 'dup_closed': '重复关闭'}
SEV_CN = {'critical': '关键', 'major': '重大', 'general': '一般', 'watch': '观察', '': '未定级'}
RC_CN = {'config': '配置', 'defect': '缺陷', 'usage': '使用', 'external': '外部依赖',
         'data': '数据', 'requirement': '需求有误', '': '未填'}
RES_CN = {'pass': '通过', 'fail': '未通过', 'deviation': '偏差', '': '未执行'}


def retry(fn, n=6):
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            if i == n - 1:
                raise
            time.sleep(5)


def login():
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0'
    pw = open(os.path.join(WS, '.secrets', 'story_pool_pass_xiao_custom')).read().strip()
    retry(lambda: s.post(BASE + '/api/login', json={'username': 'xiao', 'password': pw}, timeout=25))
    return s


def fetch(s, path):
    return retry(lambda: s.get(BASE + path, timeout=25)).json()


def md_table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    for r in rows:
        out.append('| ' + ' | '.join(str(c).replace('|', '\\|').replace('\n', ' ') for c in r) + ' |')
    return '\n'.join(out)


def get_requirements(s, pid):
    return fetch(s, '/api/requirements?project=%d&page_size=50' % pid).get('items', [])


def get_testcases(s, pid):
    return fetch(s, '/api/testcases?project=%d' % pid).get('items', [])


def gen_csv14(s, pid, out):
    items = get_requirements(s, pid)
    bugs = [x for x in items if x['type'] == 'bug']
    rows = []
    for x in bugs:
        rows.append([('#%d' % x['id']), x['title'], ST_CN.get(x['status'], x['status']),
                     SEV_CN.get(x.get('severity', ''), x.get('severity', '')),
                     RC_CN.get(x.get('root_cause', ''), x.get('root_cause', '')),
                     x.get('ref_code') or '—', (x.get('created_at') or '')[:10]])
    # 五维度统计（CSV-14 口径：状态/级别/根因/项目/类型——项目内导出故项目维恒定）
    def cnt(key):
        m = {}
        for x in bugs:
            k = key(x)
            m[k] = m.get(k, 0) + 1
        return ' ｜ '.join('%s:%d' % (k, v) for k, v in sorted(m.items())) or '无'
    doc = ['# CSV-14 问题登记表（生成于 %s）' % time.strftime('%Y-%m-%d'),
           '',
           '> 数据源：cf-story-pool 项目 #%d（channel/提单人等全量字段见池内详情）。本表为生成快照，运行期以池内台账为准。' % pid,
           '',
           md_table(['问题号', '标题', '状态', '级别', '根因分类', '关联编号', '登记日期'], rows),
           '',
           '## 五维度统计（bug 单 %d 条）' % len(bugs),
           '',
           '- 按状态：' + cnt(lambda x: ST_CN.get(x['status'], x['status'])),
           '- 按级别：' + cnt(lambda x: SEV_CN.get(x.get('severity', ''), '未定级')),
           '- 按根因分类：' + cnt(lambda x: RC_CN.get(x.get('root_cause', ''), '未填')),
           '- 按类型：' + cnt(lambda x: x['type']),
           '',
           '## 定期审查结论（月度）',
           '',
           '（审查人填写：本月新增逐条过级 / 超期项 / 重复现象关联号 / 巡检发现）']
    path = os.path.join(out, 'CSV-14-问题登记表-项目%d-%s.md' % (pid, time.strftime('%Y%m%d')))
    open(path, 'w').write('\n'.join(doc))
    print('生成', path, '（bug %d 条）' % len(bugs))


def gen_report(s, pid, rel_id, out):
    rels = fetch(s, '/api/releases?project=%d' % pid).get('items', [])
    rel = [x for x in rels if x['id'] == rel_id][0]
    ex = fetch(s, '/api/releases/%d/executions' % rel_id)
    items, stat = ex.get('items', []), ex.get('stat', {})
    tc_detail = {}
    for e in items:
        d = fetch(s, '/api/testcases/%d' % e['tc_id'])
        tc_detail[e['tc_id']] = d.get('steps_md', '')
    rows = []
    for e in items:
        rows.append([e['tc_code'], e['tc_title'], RES_CN.get(e['result'], e['result']),
                     e.get('conclusion') or '—', e.get('dev_ref') or '—', e.get('ev_ref') or '—',
                     e.get('executor') or '—'])
    doc = ['# %s 版本测试报告（%s 生成）' % (rel['version'], time.strftime('%Y-%m-%d')),
           '',
           '**变更范围**：%s' % (rel.get('change_scope') or '—'),
           '',
           '**再验证范围**：%s' % (rel.get('retest_scope') or '—'),
           '',
           '## 一、执行统计',
           '',
           '| 通过 | 未通过 | 偏差 | 未执行 |',
           '|---|---|---|---|',
           '| %d | %d | %d | %d |' % (stat.get('pass', 0), stat.get('fail', 0),
                                      stat.get('deviation', 0), stat.get('empty', 0)),
           '',
           '## 二、执行明细',
           '',
           md_table(['用例', '标题', '结果', '结论', 'DEV号', 'EV号', '执行人'], rows),
           '',
           '## 三、用例步骤与预期（全文）',
           '']
    for e in items:
        doc.append('### %s %s（%s）' % (e['tc_code'], e['tc_title'], RES_CN.get(e['result'], e['result'])))
        doc.append('')
        doc.append(tc_detail.get(e['tc_id'], '（无）'))
        doc.append('')
    doc.append('## 四、未解决偏差与已知问题')
    doc.append('')
    doc.append('（按执行结果填写：deviation 项的关闭条件与责任方复核结论）')
    doc.append('')
    doc.append('## 五、发布建议')
    doc.append('')
    doc.append('（由执行统计与偏差评估得出：通过 / 有条件通过 / 不通过）')
    path = os.path.join(out, '版本测试报告-%s-%s.md' % (rel['version'], time.strftime('%Y%m%d')))
    open(path, 'w').write('\n'.join(doc))
    print('生成', path, '（执行 %d 条：pass %d / fail %d / dev %d）' % (
        len(items), stat.get('pass', 0), stat.get('fail', 0), stat.get('deviation', 0)))


def gen_rtm(s, pid, out):
    reqs = get_requirements(s, pid)
    tcs = get_testcases(s, pid)
    by_req = {}
    for t in tcs:
        by_req.setdefault(t.get('related_req'), []).append(t)
    rows = []
    for x in reqs:
        tcs_of = by_req.get(x['id'], [])
        rows.append(['#%d' % x['id'], x['title'],
                     ST_CN.get(x['status'], x['status']),
                     '、'.join(t['tc_code'] for t in tcs_of) or '〔无用例〕',
                     len(tcs_of)])
    orphan = [t['tc_code'] for t in tcs if not t.get('related_req')]
    doc = ['# 需求追溯矩阵片段（RTM，生成于 %s）' % time.strftime('%Y-%m-%d'),
           '',
           '> 正向不缺：需求应有用例；反向不野：用例应可溯需求。对账数字随池内数据变化。',
           '',
           md_table(['需求', '标题', '状态', '关联用例', '用例数'], rows),
           '',
           '## 对账结果',
           '',
           '- 需求总数：%d ｜ 用例总数：%d' % (len(reqs), len(tcs)),
           '- 正向缺口（无用例覆盖的需求）：%d' % len([r for r in rows if r[3] == '〔无用例〕']),
           '- 反向缺口（未关联需求的孤儿用例）：%d（%s）' % (len(orphan), '、'.join(orphan) or '无')]
    path = os.path.join(out, 'RTM-需求追溯-项目%d-%s.md' % (pid, time.strftime('%Y%m%d')))
    open(path, 'w').write('\n'.join(doc))
    print('生成', path, '（需求 %d / 用例 %d）' % (len(reqs), len(tcs)))


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ('csv14', 'report', 'rtm'):
        print(__doc__)
        raise SystemExit(1)
    cmd = a[0]
    pid = int(a[a.index('--project') + 1]) if '--project' in a else 3
    rel = int(a[a.index('--release') + 1]) if '--release' in a else None
    out = a[a.index('--out') + 1] if '--out' in a else OUT_DEFAULT
    os.makedirs(out, exist_ok=True)
    s = login()
    if cmd == 'csv14':
        gen_csv14(s, pid, out)
    elif cmd == 'report':
        if not rel:
            print('report 需要 --release')
            raise SystemExit(1)
        gen_report(s, pid, rel, out)
    elif cmd == 'rtm':
        gen_rtm(s, pid, out)


if __name__ == '__main__':
    main()
