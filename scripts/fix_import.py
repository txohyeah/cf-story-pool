#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入后修复：比对 ITEMS 期望 vs 线上实际，补状态流转、补缺失工作项、补 done。
幂等，可反复跑到收敛。用法：python3 scripts/fix_import.py"""
import json
import re
import sys
import time

import import_yuque_v15 as base

BASE_URL = base.BASE
ITEMS = [x for x, _ in base.ITEMS]


def main():
    password = open(base.PASS_FILE).read().strip()
    s, h, raw = base.http('POST', '/api/login', {'username': base.XIAO, 'password': password})
    if s != 200:
        print('登录失败 %s' % s);  sys.exit(1)
    m = re.search(base.COOKIE_NAME + '=([^;]+)', h.get('Set-Cookie', ''))
    cookie = base.COOKIE_NAME + '=' + m.group(1)

    state = json.load(open(base.STATE_FILE))
    fixed_status = patched_ck_done = added_ck = 0

    # 以库为准：拉全量需求建 title→id 映射（state 的 id 可能指向已被清理的重复副本）
    s, _h, raw = base.http('GET', '/api/requirements?project=1&page_size=50&page=1&status=all', cookie=cookie)
    # 分页拉全
    b = json.loads(raw)
    total_pages = b['pages']
    tmap = {r['title']: r['id'] for r in b['items']}
    for p in range(2, total_pages + 1):
        s, _h, raw = base.http('GET', '/api/requirements?project=1&page_size=50&page=%d&status=all' % p, cookie=cookie)
        for r in json.loads(raw)['items']:
            tmap.setdefault(r['title'], r['id'])
    print('库中需求 %d 条，title 映射 %d 个' % (b['total'], len(tmap)))

    for x in ITEMS:
        rid = tmap.get(x['t']) or (state.get(x['t']) or {}).get('id')
        if not rid:
            print('!! 库中找不到：%s' % x['t']);  continue
        try:
            s, _h, raw = base.http('GET', '/api/requirements/%d' % rid, cookie=cookie)
        except RuntimeError as e:
            print('!! 网络异常，中断：%s | %s' % (x['t'], e));  break
        if s != 200:
            print('!! 详情失败 %s #%s' % (s, rid));  continue
        d = json.loads(raw)
        # 1) 状态补流转
        if d['req']['status'] != x['st']:
            s, _h, raw = base.http('PATCH', '/api/requirements/%d' % rid,
                                   {'op': 'status', 'status': x['st'],
                                    'note': '导入修复：补状态流转'}, cookie)
            if s == 200:
                fixed_status += 1
                print('补状态 #%s %s -> %s' % (rid, d['req']['status'], x['st']))
            else:
                print('!! 补状态失败 %s：#%s' % (s, rid))
        # 2) 工作项补建/补勾
        want = x['ck']
        have = {}
        for c in d.get('checklist', []):
            have.setdefault(c['content'], []).append(c)
        for content, assignee, done in want:
            lst = have.get(content[:200])
            if not lst:
                body = {'content': content[:200]}
                if assignee:
                    body['assignee_id'] = uid_map[assignee]
                try:
                    s, _h, raw = base.http('POST', '/api/requirements/%d/checklist' % rid, body, cookie)
                except RuntimeError as e:
                    print('!! 网络异常，中断：%s | %s' % (x['t'], e));  sys.exit(2)
                if s != 200:
                    print('!! 补建工作项失败 %s：#%s %s' % (s, rid, content[:30]));  continue
                cid = json.loads(raw)['id']
                added_ck += 1
                print('补工作项 #%s: %s' % (rid, content[:30]))
                if done:
                    base.http('PATCH', '/api/checklist/%d' % cid, {'status': 'done'}, cookie)
                    patched_ck_done += 1
            else:
                cur = lst[0]
                if done and cur['status'] != 'done':
                    s2, _h, _r = base.http('PATCH', '/api/checklist/%d' % cur['id'],
                                           {'status': 'done'}, cookie)
                    if s2 == 200:
                        patched_ck_done += 1
                        print('补勾选 #%s ck%s: %s' % (rid, cur['id'], content[:30]))
        time.sleep(0.08)

    print('\n修复完成：补状态 %d，补工作项 %d，补勾选 %d' % (fixed_status, added_ck, patched_ck_done))


if __name__ == '__main__':
    # bootstrap 拿用户 id（供补建指派）
    _pw = open(base.PASS_FILE).read().strip()
    _s, _h, _raw = base.http('POST', '/api/login', {'username': base.XIAO, 'password': _pw})
    _m = re.search(base.COOKIE_NAME + '=([^;]+)', _h.get('Set-Cookie', ''))
    _ck = base.COOKIE_NAME + '=' + _m.group(1)
    _s2, _h2, _raw2 = base.http('GET', '/api/bootstrap', cookie=_ck)
    _b = json.loads(_raw2)
    uid_map = {u['username']: u['id'] for u in _b['users']}
    main()
