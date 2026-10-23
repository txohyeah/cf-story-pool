#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R8 docgen：从 cf-story-pool 取数生成 CSV 合规文档草稿（md）。

子命令：
  csv14   --project 3 --out DIR      CSV-14 问题登记与定期审查表（bug/需求台账+五维度统计）
  report  --project 3 --release 1 --out DIR   版本测试报告（执行记录+统计+用例全文）
  rtm     --project 3 --out DIR      需求追溯矩阵片段（需求↔用例双向）
  export  --project 3 --out DIR      项目全量上下文数据包（JSON：需求含评论/releases/用例含步骤/
                                     执行记录/文档清单/统计——agent 拿数据包+模板骨架构建任意个性化文档）

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


def checked_json(response, context):
    if response.status_code != 200:
        raise SystemExit('%s 失败：HTTP %s' % (context, response.status_code))
    try:
        data = response.json()
    except ValueError:
        raise SystemExit('%s 失败：响应不是 JSON' % context)
    if not isinstance(data, dict) or data.get('ok') is not True:
        raise SystemExit('%s 失败：业务响应未成功' % context)
    return data


def login():
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0'
    pw = open(os.path.join(WS, '.secrets', 'story_pool_pass_xiao_custom')).read().strip()
    try:
        response = retry(lambda: s.post(BASE + '/api/login', json={'username': 'xiao', 'password': pw}, timeout=25))
    except requests.RequestException:
        raise SystemExit('登录失败：网络错误')
    checked_json(response, '登录')
    if not s.cookies.get('storypool_auth'):
        raise SystemExit('登录失败：未获得 session cookie')
    return s


def fetch(s, path):
    try:
        response = retry(lambda: s.get(BASE + path, timeout=25))
    except requests.RequestException:
        raise SystemExit('取数失败：网络错误')
    return checked_json(response, path)


def md_table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    for r in rows:
        out.append('| ' + ' | '.join(str(c).replace('|', '\\|').replace('\n', ' ') for c in r) + ' |')
    return '\n'.join(out)


def get_requirements(s, pid):
    items = []
    first = fetch(s, '/api/requirements?project=%d&page_size=50&page=1' % pid)
    total, pages = first.get('total'), first.get('pages')
    if type(total) is not int or total < 0 or type(pages) is not int or pages != max(1, (total + 49) // 50):
        raise SystemExit('需求分页元数据不合法')
    for page in range(1, pages + 1):
        data = first if page == 1 else fetch(s, '/api/requirements?project=%d&page_size=50&page=%d' % (pid, page))
        if data.get('total') != total or data.get('pages') != pages or data.get('page') != page or not isinstance(data.get('items'), list):
            raise SystemExit('需求分页数据发生变化或响应异常，请重新导出')
        items.extend(data['items'])
    if len(items) != total or len({x['id'] for x in items}) != total:
        raise SystemExit('需求分页完整性校验失败：累计条数或唯一 ID 数不等于 total')
    return items


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
        version = e.get('tc_version')
        if version is None:
            tc_detail[e['tc_id']] = d.get('steps_md', '')
        else:
            steps = e.get('executed_steps_md')
            if steps is None:
                raise SystemExit('执行记录引用的用例版本不存在：tc_id=%s version=%s' % (e['tc_id'], version))
            tc_detail[e['tc_id']] = steps
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


def gen_export(s, pid, out):
    """项目全量上下文数据包（JSON）：需求含评论/releases/用例含步骤全文/执行记录/文档清单/统计。"""
    def safe(fn_, default):
        try:
            return fn_()
        except Exception as e:
            print('  warn:', type(e).__name__)
            return default

    # 需求全量（列表+逐条评论全文）
    reqs = get_requirements(s, pid)
    reqs_full = []
    for x in reqs:
        d = safe(lambda x=x: fetch(s, '/api/requirements/%d' % x['id']), {})
        req = d.get('req', x)
        reqs_full.append({
            'id': req.get('id', x['id']), 'title': req.get('title'), 'type': req.get('type'),
            'status': req.get('status'), 'severity': req.get('severity', ''),
            'root_cause': req.get('root_cause', ''), 'ref_code': req.get('ref_code', ''),
            'release_id': req.get('release_id'), 'description': req.get('description', ''),
            'tags': d.get('tags', []), 'comments': [
                {'actor': e.get('actor_name'), 'ctype': e.get('ctype', 'normal'),
                 'text': e.get('detail'), 'at': e.get('created_at')}
                for e in d.get('events', []) if e.get('action') == 'comment'],
        })
        print('  req #%d' % req.get('id', x['id']))
    # releases + 执行记录
    rels = fetch(s, '/api/releases?project=%d' % pid).get('items', [])
    for rl in rels:
        ex = safe(lambda rl=rl: fetch(s, '/api/releases/%d/executions' % rl['id']), {})
        rl['executions'] = ex.get('items', [])
        rl['stat'] = ex.get('stat', {})
    # 用例全量（含步骤全文+版本+执行）
    tcs = fetch(s, '/api/testcases?project=%d' % pid).get('items', [])
    tcs_full = []
    for x in tcs:
        d = safe(lambda x=x: fetch(s, '/api/testcases/%d' % x['id']), {})
        if d.get('ok'):
            tcs_full.append({**d['tc'], 'steps_md': d.get('steps_md', ''),
                             'versions': d.get('versions', []), 'executions': d.get('executions', [])})
            print('  tc %s' % x['tc_code'])
        else:
            tcs_full.append({'tc_code': x['tc_code'], 'title': x['title'], '_error': True})
    # 文档清单（含当前内容+版本）
    docs = fetch(s, '/api/docs?project_id=%d' % pid).get('items', [])
    docs_full = []
    for x in docs:
        d = safe(lambda x=x: fetch(s, '/api/docs/%d' % x['id']), {})
        if d.get('ok'):
            docs_full.append({**d['doc'], 'content_md': d.get('content_md', ''),
                              'versions': d.get('versions', [])})
            print('  doc #%d' % x['id'])
    # 组装
    pkg = {
        'exported_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'project': {'id': pid},
        'requirements': reqs_full,
        'releases': rels,
        'testcases': tcs_full,
        'docs': docs_full,
        'stats': {
            'requirements': len(reqs_full),
            'releases': len(rels),
            'testcases': len(tcs_full),
            'docs': len(docs_full),
        },
    }
    path = os.path.join(out, '项目数据包-story-pool-%s.json' % time.strftime('%Y%m%d'))
    with open(path, 'w') as f:
        json.dump(pkg, f, ensure_ascii=False, indent=1)
    size = os.path.getsize(path)
    print('生成', path, '（%d 条需求 / %d 版本 / %d 用例 / %d 文档，%.0f KB）' % (
        len(reqs_full), len(rels), len(tcs_full), len(docs_full), size / 1024))

def main():
    a = sys.argv[1:]
    if not a or a[0] not in ('csv14', 'report', 'rtm', 'export'):
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
    elif cmd == 'export':
        gen_export(s, pid, out)


if __name__ == '__main__':
    main()
