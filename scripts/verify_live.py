#!/usr/bin/env python3
"""cf-story-pool 线上功能自检（qwenpaw 测试账号，不碰真实用户）。
覆盖：健康检查/匿名门禁/登录失败/登录/建单/去重提示/状态流转/工作项清单(我的工作项)/
评论/标签替换/附件上传下载/重复关闭/删除清理。
结尾把新会话 cookie 写入 .secrets/verify-cookie-cf-story-pool.txt（pw.py 部署核对用，600）。
用法：python3 scripts/verify_live.py [--base https://cf-story-pool.pages.dev]
"""
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

import requests

try:
    import certifi
    import ssl
    _CAFILE = certifi.where()
except Exception:
    _CAFILE = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))
BASE = 'https://cf-story-pool.pages.dev'
if '--base' in sys.argv:
    BASE = sys.argv[sys.argv.index('--base') + 1].rstrip('/')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
PASS_FILE = os.path.join(WORKSPACE, '.secrets', 'story_pool_qwenpaw')
COOKIE_FILE = os.path.join(WORKSPACE, '.secrets', 'verify-cookie-cf-story-pool.txt')
COOKIE_NAME = 'storypool_auth'

_results = []


def check(name, ok, extra=''):
    _results.append((name, ok))
    print(('[PASS] ' if ok else '[FAIL] ') + name + ((' — ' + extra) if extra else ''))
    return ok


def make_png():
    """1x1 红色 PNG。"""
    def chunk(typ, data):
        c = typ + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00'))
    return b'\x89PNG\r\n\x1a\n' + ihdr + idat + chunk(b'IEND', b'')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


import ssl as _ssl
_SESSION = requests.Session()
if _CAFILE:
    _SESSION.verify = _CAFILE
# requests 默认 UA 会被 CF Bot 防御拦（403），必须带浏览器 UA
_SESSION.headers['User-Agent'] = UA


def http(method, path, data=None, headers=None):
    """返回 (status, resp_headers, body_bytes)。不跟随重定向。

    Session 连接复用：pages.dev 链路抖动期每请求重握手易连环超时（坑册既定方案），
    全套自检只握 1~2 次手；20s 超时 × 5 次重试 + 退避。
    """
    for attempt in range(5):
        try:
            r = _SESSION.request(method, BASE + path, data=data, headers=headers,
                                 timeout=20, allow_redirects=False)
            return r.status_code, dict(r.headers), r.content
        except requests.RequestException as e:
            if attempt == 4:
                raise
            print('  (网络重试 %d: %s)' % (attempt + 1, e))
            import time as _time
            _time.sleep(3 * (attempt + 1))


def jreq(method, path, body=None, cookie=None):
    headers = {'Content-Type': 'application/json'}
    if cookie:
        headers['Cookie'] = cookie
    data = None
    if body is not None:
        import json as _json
        data = _json.dumps(body).encode()
    status, _h, raw = http(method, path, data, headers)
    try:
        import json as _json
        return status, _json.loads(raw.decode())
    except Exception:
        return status, {}


def main():
    import json as _json
    password = open(PASS_FILE).read().strip()

    # 1. 健康检查
    s, _h, raw = http('GET', '/api/health')
    check('health 200', s == 200 and _json.loads(raw).get('ok') is True)

    # 1b. 匿名静态资源：style.css 必须匿名可达（否则登录页裸奔）
    s, h, _raw = http('GET', '/style.css')
    check('匿名 /style.css 200', s == 200 and 'text/css' in h.get('Content-Type', ''))

    # 2. 匿名门禁：302 → /login
    s, h, _raw = http('GET', '/')
    loc = h.get('Location', '')
    check('匿名访问 / 302→/login', s == 302 and '/login' in loc, 'loc=%s' % loc)

    # 3. 错误密码 401
    s, d = jreq('POST', '/api/login', {'username': 'qwenpaw', 'password': 'wrong-pass'})
    check('错误密码 401', s == 401)

    # 4. 正确登录，拿 cookie
    s, h, raw = http('POST', '/api/login',
                     _json.dumps({'username': 'qwenpaw', 'password': password}).encode(),
                     {'Content-Type': 'application/json'})
    setc = h.get('Set-Cookie', '')
    m = re.search(COOKIE_NAME + '=([^;]+)', setc)
    check('登录 200 + cookie', s == 200 and bool(m))
    cookie = COOKIE_NAME + '=' + (m.group(1) if m else '')

    # 5. me
    s, d = jreq('GET', '/api/me', cookie=cookie)
    check('me 返回 qwenpaw', s == 200 and d.get('authed') and d.get('username') == 'qwenpaw')

    # 6. bootstrap 字典
    s, d = jreq('GET', '/api/bootstrap', cookie=cookie)
    projects = {p['name']: p['id'] for p in d.get('projects', [])}
    users = {u['username']: u['id'] for u in d.get('users', [])}
    check('bootstrap 含 be-trial/oncology', 'be-trial' in projects and 'oncology' in projects)
    check('bootstrap 含预置标签', any(t['name'] == 'AI整理' for t in d.get('tags', [])))

    # 6b. 自愈清场：删掉历史中断运行泄漏的 [verify] 测试单（qwenpaw 保留地，按 title 前缀精准匹配）
    s, d = jreq('GET', '/api/requirements?q=' + urllib.request.quote('[verify]') + '&page_size=50',
                cookie=cookie)
    stale = [x for x in d.get('items', []) if x['title'].startswith('[verify]')]
    if stale:
        print('  (清场: 删除历史残留 %s)' % [x['id'] for x in stale])
        for x in stale:
            jreq('DELETE', '/api/requirements/%d' % x['id'], cookie=cookie)

    # 7. 建单 A
    s, d = jreq('POST', '/api/requirements', {
        'project_id': projects['be-trial'], 'title': '[verify] 自检测试需求 storypool',
        'description': 'verify_live 自动建单', 'type': 'bug', 'urgency': 'urgent',
        'tags': ['verify自检']}, cookie=cookie)
    ok = s == 200 and d.get('ok') and d.get('id')
    check('建单 A', ok)
    aid = d.get('id')

    # 8. 去重提示命中 A（带一次重试，防网络抖动假阴性）
    hit = False
    for _ in range(2):
        s, d = jreq('GET', '/api/dedup-suggest?q=' + urllib.request.quote('自检测试需求'), cookie=cookie)
        if any(x['id'] == aid for x in d.get('items', [])):
            hit = True
            break
    check('dedup-suggest 命中 A', hit)

    # 9. 状态流转 submitted→confirmed
    s, d = jreq('PATCH', '/api/requirements/%d' % aid, {'op': 'status', 'status': 'confirmed'}, cookie=cookie)
    s2, d2 = jreq('GET', '/api/requirements/%d' % aid, cookie=cookie)
    check('状态流转 confirmed + 事件留痕',
          d.get('ok') and d2['req']['status'] == 'confirmed'
          and any(e['action'] == 'status' for e in d2['events']))

    # 10. 清单：加工作项指派给 qwenpaw → my-work 出现 → 完成 → 消失
    s, d = jreq('POST', '/api/requirements/%d/checklist' % aid,
                {'content': '后端开发', 'assignee_id': users['qwenpaw']}, cookie=cookie)
    cid = d.get('id')
    s, d = jreq('GET', '/api/my-work', cookie=cookie)
    in_my = any(c['req_id'] == aid for c in d.get('items', []))
    s, d = jreq('PATCH', '/api/checklist/%d' % cid, {'status': 'done'}, cookie=cookie)
    s, d = jreq('GET', '/api/my-work', cookie=cookie)
    out_my = not any(c['req_id'] == aid for c in d.get('items', []))
    check('工作项清单 + 我的工作项', bool(cid) and in_my and out_my)

    # 10b. my-work 同步过滤：project/type/tag/status/q 全链路（自包含：建 D + 给 A 加工作项 → 断言 → 清理）
    s, d = jreq('POST', '/api/requirements/%d/checklist' % aid,
                {'content': '前端联调', 'assignee_id': users['qwenpaw']}, cookie=cookie)
    aid2_cid = d.get('id')
    s, d = jreq('POST', '/api/requirements', {
        'project_id': projects['oncology'], 'title': '[verify] mywork过滤探针',
        'description': 'verify_live my-work 过滤测试', 'type': 'req',
        'tags': ['verify自检', 'mywork探针标签']}, cookie=cookie)
    did = d.get('id')
    s, d = jreq('POST', '/api/requirements/%d/checklist' % did,
                {'content': '[verify] mywork探针独特词zzq', 'assignee_id': users['qwenpaw']}, cookie=cookie)
    did_cid = d.get('id')
    s, d = jreq('GET', '/api/my-work', cookie=cookie)
    mw_ids = {c['req_id'] for c in d.get('items', [])}
    check('mywork过滤: 探针数据就绪(A+D)',
          bool(aid2_cid) and bool(did) and bool(did_cid) and aid in mw_ids and did in mw_ids)

    def mw_has(qs, want, notwant=()):
        s, d = jreq('GET', '/api/my-work' + qs, cookie=cookie)
        ids = {c['req_id'] for c in d.get('items', [])}
        return set(want) <= ids and not (set(notwant) & ids)

    check('mywork过滤: project=oncology 只剩D',
          mw_has('?project=%d' % projects['oncology'], {did}, {aid}))
    check('mywork过滤: type=bug 只剩A', mw_has('?type=bug', {aid}, {did}))
    check('mywork过滤: type=req 只剩D', mw_has('?type=req', {did}, {aid}))
    check('mywork过滤: tag=mywork探针标签 只剩D',
          mw_has('?tag=' + urllib.request.quote('mywork探针标签'), {did}, {aid}))
    check('mywork过滤: tag=verify自检 A+D 都在',
          mw_has('?tag=' + urllib.request.quote('verify自检'), {aid, did}))
    check('mywork过滤: status=confirmed 只剩A', mw_has('?status=confirmed', {aid}, {did}))
    check('mywork过滤: urgency=urgent 只剩A', mw_has('?urgency=urgent', {aid}, {did}))
    s, d = jreq('GET', '/api/requirements?urgency=urgent&page_size=50', cookie=cookie)
    lst_ids = {x['id'] for x in d.get('items', [])}
    check('列表过滤: urgency=urgent 含A不含D', aid in lst_ids and did not in lst_ids)
    check('mywork过滤: q 命中工作项内容(D)',
          mw_has('?q=' + urllib.request.quote('mywork探针独特词zzq'), {did}))
    check('mywork过滤: q 命中需求标题(A)',
          mw_has('?q=' + urllib.request.quote('自检测试需求'), {aid}))
    check('mywork过滤: 组合 project+type',
          mw_has('?project=%d&type=bug' % projects['be-trial'], {aid}, {did}))
    # 清理：D 删除（工作项级联删），A 的探针工作项标 done
    s, d = jreq('DELETE', '/api/requirements/%d' % did, cookie=cookie)
    s, d = jreq('PATCH', '/api/checklist/%d' % aid2_cid, {'status': 'done'}, cookie=cookie)
    s, d = jreq('GET', '/api/my-work', cookie=cookie)
    mw_ids = {c['req_id'] for c in d.get('items', [])}
    check('mywork过滤: 清理闭环', d.get('ok') and did not in mw_ids and aid not in mw_ids)

    # 11. 评论
    s, d = jreq('POST', '/api/requirements/%d/comment' % aid, {'text': 'verify 评论'}, cookie=cookie)
    s2, d2 = jreq('GET', '/api/requirements/%d' % aid, cookie=cookie)
    check('评论入流水', d.get('ok') and any(e['action'] == 'comment' for e in d2['events']))

    # 12. 标签替换
    s, d = jreq('PATCH', '/api/requirements/%d' % aid, {'op': 'tags', 'tags': ['verify自检', 'AI整理']},
                cookie=cookie)
    s2, d2 = jreq('GET', '/api/requirements/%d' % aid, cookie=cookie)
    names = sorted(t['name'] for t in d2['tags'])
    check('标签替换为 2 个', d.get('ok') and names == ['AI整理', 'verify自检'], str(names))

    # 13. 附件上传 + 门禁读取
    png = make_png()
    boundary = '----verify%s' % os.urandom(8).hex()
    part = (('--%s\r\nContent-Disposition: form-data; name="file"; filename="v.png"\r\n'
             'Content-Type: image/png\r\n\r\n' % boundary).encode()
            + png + ('\r\n--%s--\r\n' % boundary).encode())
    s, _h, raw = http('POST', '/api/upload', part,
                      {'Content-Type': 'multipart/form-data; boundary=%s' % boundary, 'Cookie': cookie})
    up = _json.loads(raw)
    check('附件上传', s == 200 and up.get('ok') and re.fullmatch(r'[A-Za-z0-9-]{8,64}', up.get('key', '')) is not None)
    s, _h, raw = http('GET', '/api/files/' + up['key'], None, {'Cookie': cookie})
    check('附件门禁内读取 PNG', s == 200 and raw[:4] == b'\x89PNG')

    # 14. 建单 C 带附件 → 详情含附件 → 删除 C → 附件 404
    s, d = jreq('POST', '/api/requirements', {
        'project_id': projects['be-trial'], 'title': '[verify] 附件单',
        'tags': ['verify自检'], 'attachments': [{'key': up['key'], 'name': 'v.png', 'size': len(png)}]},
        cookie=cookie)
    cid2 = d.get('id')
    s2, d2 = jreq('GET', '/api/requirements/%d' % cid2, cookie=cookie)
    has_att = len(d2.get('attachments', [])) == 1
    s3, d3 = jreq('DELETE', '/api/requirements/%d' % cid2, cookie=cookie)
    s4, _h2, _raw2 = http('GET', '/api/files/' + up['key'], None, {'Cookie': cookie})
    check('附件单建/查/删 + R2 对象清理', has_att and d3.get('ok') and s4 == 404)

    # 15. 重复关闭：B → A；删除 A 前先删 B（解除引用）
    s, d = jreq('POST', '/api/requirements', {
        'project_id': projects['oncology'], 'title': '[verify] 重复单测试',
        'tags': ['verify自检']}, cookie=cookie)
    bid = d.get('id')
    s, d = jreq('PATCH', '/api/requirements/%d' % bid,
                {'op': 'status', 'status': 'dup_closed', 'duplicate_of': aid}, cookie=cookie)
    s2, d2 = jreq('GET', '/api/requirements/%d' % bid, cookie=cookie)
    check('重复关闭指向 A', d.get('ok') and d2['req']['status'] == 'dup_closed'
          and d2['req']['duplicate_of'] == aid and d2.get('dup_of', {}).get('id') == aid)

    # 16. 清理测试单
    s1, d1 = jreq('DELETE', '/api/requirements/%d' % bid, cookie=cookie)
    s2, d2 = jreq('DELETE', '/api/requirements/%d' % aid, cookie=cookie)
    s3, d3 = jreq('GET', '/api/requirements/%d' % aid, cookie=cookie)
    check('测试单清理', d1.get('ok') and d2.get('ok') and s3 == 404)

    # 17. 项目统计接口（首页项目卡片数据源）
    s, d = jreq('GET', '/api/projects', cookie=cookie)
    pj = {p['name']: p for p in d.get('projects', [])}
    check('项目统计接口含 be-trial 且带 total/open',
          'be-trial' in pj and isinstance(pj['be-trial'].get('total'), int)
          and isinstance(pj['be-trial'].get('open'), int))

    # 18. 项目创建 + 有需求项目禁删 + 空项目可删（闭环不留脏数据）
    s, d = jreq('POST', '/api/projects', {'name': '[verify] 自检项目'}, cookie=cookie)
    vpid = d.get('id')
    if not (s == 200 and d.get('ok')):
        # 网络抖动下 POST 可能「服务端已成功但响应读超时」，兜底按名字查回
        s2, d2 = jreq('GET', '/api/projects', cookie=cookie)
        found = [p for p in d2.get('projects', []) if p['name'] == '[verify] 自检项目']
        vpid = found[0]['id'] if found else None
    check('项目创建', bool(vpid))
    s, d = jreq('POST', '/api/projects', {'name': '[verify] 自检项目'}, cookie=cookie)
    check('项目重名拦截', s == 400)
    if vpid:
        s, d = jreq('POST', '/api/requirements', {
            'project_id': vpid, 'title': '[verify] 项目禁删探针', 'tags': ['verify自检']}, cookie=cookie)
        probe_id = d.get('id')
        s, d = jreq('DELETE', '/api/projects/%d' % vpid, cookie=cookie)
        check('有需求项目禁删', s == 400)
        if probe_id:
            s, d = jreq('DELETE', '/api/requirements/%d' % probe_id, cookie=cookie)
        s, d = jreq('DELETE', '/api/projects/%d' % vpid, cookie=cookie)
        s2, d2 = jreq('GET', '/api/projects', cookie=cookie)
        gone = not any(p['id'] == vpid for p in d2.get('projects', []))
        check('空项目删除闭环', d.get('ok') and gone)
    else:
        check('有需求项目禁删', False, 'vpid 缺失，无法执行')
        check('空项目删除闭环', False, 'vpid 缺失，无法执行')

    # 18.5 文档页闭环（v2 P0）——独立临时项目自建自清，避免依赖上方已删除的自检项目
    s, d = jreq('POST', '/api/projects', {'name': '[verify] 文档项目'}, cookie=cookie)
    dpid = d.get('id')
    if not dpid:
        # 重名残留或网络抖动兜底：按名查回复用
        s2, d2 = jreq('GET', '/api/projects', cookie=cookie)
        found = [p for p in d2.get('projects', []) if p['name'] == '[verify] 文档项目']
        dpid = found[0]['id'] if found else None
    check('文档测试项目就绪', bool(dpid))
    if dpid:
        s, d = jreq('POST', '/api/docs', {
            'project_id': dpid, 'title': '[verify] 自检文档',
            'content_md': '# v1 内容\n\n| 列A | 列B |\n|---|---|\n| 1 | 2 |'}, cookie=cookie)
        doc_id = d.get('id')
        if not doc_id:
            # 网络抖动兜底：POST 可能服务端已成功但响应丢失，按名查回（非幂等 POST 不盲重试）
            s2, d2 = jreq('GET', '/api/docs?project_id=%d' % dpid, cookie=cookie)
            found = [x for x in d2.get('items', []) if x['title'] == '[verify] 自检文档']
            doc_id = found[0]['id'] if found else None
        check('文档创建', bool(doc_id))
        if doc_id:
            s, d = jreq('GET', '/api/docs/%d' % doc_id, cookie=cookie)
            check('文档详情与首版内容', s == 200 and d.get('content_md', '').startswith('# v1')
                  and d.get('doc', {}).get('current_version') == 1)
            s, d = jreq('PATCH', '/api/docs/%d' % doc_id,
                        {'content_md': '# v2 内容', 'change_summary': '自检升版'}, cookie=cookie)
            check('文档编辑升版 v2', d.get('ok') and d.get('version') == 2)
            s, d = jreq('POST', '/api/docs/%d/comment' % doc_id, {'content': '[verify] 评审意见'}, cookie=cookie)
            s, d = jreq('GET', '/api/docs/%d' % doc_id, cookie=cookie)
            cms = d.get('comments', [])
            check('文档评论绑版本', d.get('ok') and len(cms) == 1 and cms[0].get('doc_version') == 2)
            s, d = jreq('PATCH', '/api/docs/%d' % doc_id, {'status': 'review'}, cookie=cookie)
            s, d = jreq('PATCH', '/api/docs/%d' % doc_id, {'status': 'approved'}, cookie=cookie)
            s, d = jreq('GET', '/api/docs/%d' % doc_id, cookie=cookie)
            check('文档批准落 approved_by', d.get('doc', {}).get('status') == 'approved' and d['doc'].get('approved_by'))
            s, d = jreq('PATCH', '/api/docs/%d' % doc_id, {'content_md': '# v3 批准后编辑'}, cookie=cookie)
            s, d = jreq('GET', '/api/docs/%d' % doc_id, cookie=cookie)
            check('批准后编辑回草稿', d.get('doc', {}).get('status') == 'draft' and d['doc']['current_version'] == 3)
            s, d = jreq('GET', '/api/docs/%d/versions/1' % doc_id, cookie=cookie)
            check('历史版本回看 v1', s == 200 and d.get('content_md', '').startswith('# v1'))
            s, d = jreq('GET', '/api/docs?project_id=%d' % dpid, cookie=cookie)
            check('文档列表含自检文档', any(x['id'] == doc_id for x in d.get('items', [])))
            s, d = jreq('DELETE', '/api/docs/%d' % doc_id, cookie=cookie)
            check('测试文档清理', d.get('ok'))
        # ---- R3/R2：单据字段增强 + 筛选导出 ----
        if dpid:
            png3 = make_png()
            bnd3 = '----r3%s' % os.urandom(8).hex()
            part3 = (('--%s\r\nContent-Disposition: form-data; name="file"; filename="r.png"\r\n'
                      'Content-Type: image/png\r\n\r\n' % bnd3).encode()
                     + png3 + ('\r\n--%s--\r\n' % bnd3).encode())
            s, _h, raw3 = http('POST', '/api/upload', part3,
                               {'Content-Type': 'multipart/form-data; boundary=%s' % bnd3, 'Cookie': cookie})
            up3 = _json.loads(raw3) if raw3 else {}
            up_key = up3.get('key') if up3.get('ok') else None
            body_r3 = {'project_id': dpid, 'title': '[verify] Bug探针', 'type': 'bug',
                       'severity': 'major', 'root_cause': 'defect', 'ref_code': 'ISS-2099-001',
                       'description': 'R3验证'}
            if up_key: body_r3['attachments'] = [{'key': up_key, 'name': 'r.png', 'size': len(png3)}]
            s, d = jreq('POST', '/api/requirements', body_r3, cookie=cookie)
            bid = d.get('id')
            if not bid:
                s2, d2 = jreq('GET', '/api/requirements?project=%d&type=bug' % dpid, cookie=cookie)
                found = [x for x in d2.get('items', []) if x['title'] == '[verify] Bug探针']
                bid = found[0]['id'] if found else None
            check('R3 bug建单带字段', bool(bid))
            if bid:
                s, d = jreq('GET', '/api/requirements/%d' % bid, cookie=cookie)
                rq = d.get('req', {})
                check('R3 字段回读', rq.get('severity') == 'major' and rq.get('root_cause') == 'defect'
                      and rq.get('ref_code') == 'ISS-2099-001')
                # 附件缩略图字段回归（2026-10-17 破图 bug：detail 曾缺 r2_key 别名致前端 /api/files/undefined）
                atts = d.get('attachments', [])
                check('附件缩略图字段 r2_key 别名', bool(atts) and atts[0].get('r2_key') == atts[0].get('store_key'))
                s, d = jreq('PATCH', '/api/requirements/%d' % bid, {'op': 'edit', 'severity': 'critical'}, cookie=cookie)
                s, d = jreq('GET', '/api/requirements/%d' % bid, cookie=cookie)
                check('R3 PATCH severity', d.get('req', {}).get('severity') == 'critical')
                s, d = jreq('GET', '/api/requirements?project=%d&severity=critical' % dpid, cookie=cookie)
                check('R3 severity筛选', any(x['id'] == bid for x in d.get('items', [])))
                s, d = jreq('GET', '/api/requirements?ref=ISS-2099-001', cookie=cookie)
                check('R3 ref_code精确查询', any(x['id'] == bid for x in d.get('items', [])))
                s2, _h, raw = http('GET', '/api/export?project=%d' % dpid, headers={'Cookie': cookie})
                txt = raw.decode('utf-8-sig', errors='replace')
                check('R2 导出CSV（BOM+探针+表头+统计）', s2 == 200 and raw.startswith(b'\xef\xbb\xbf')
                      and '[verify] Bug探针' in txt and '验收标准汇总' in txt and '== 统计汇总 ==' in txt)
                s, d = jreq('DELETE', '/api/requirements/%d' % bid, cookie=cookie)
                check('R3 探针清理', d.get('ok'))
            # ---- R4：releases 版本发布单 ----
            s, d = jreq('POST', '/api/releases', {'project_id': dpid, 'version': 'v0.0-verify',
                'change_scope': '[verify] 变更范围', 'retest_scope': '[verify] 再验证范围'}, cookie=cookie)
            rel_id = d.get('id')
            check('R4 版本创建', bool(rel_id))
            if rel_id:
                s, d = jreq('POST', '/api/requirements', {
                    'project_id': dpid, 'title': '[verify] R4关联探针', 'type': 'bug'}, cookie=cookie)
                rb = d.get('id')
                if rb:
                    s, d = jreq('PATCH', '/api/requirements/%d' % rb, {'op': 'edit', 'release_id': rel_id}, cookie=cookie)
                    s, d = jreq('GET', '/api/releases?project=%d' % dpid, cookie=cookie)
                    hit = [x for x in d.get('items', []) if x['id'] == rel_id]
                    check('R4 bug关联+计数', hit and hit[0].get('bug_count') == 1)
                    s, d = jreq('PATCH', '/api/releases/%d' % rel_id, {'op': 'status', 'status': 'published'}, cookie=cookie)
                    check('R4 发布确认人≠实施人拦截', s == 400)
                    s, d = jreq('DELETE', '/api/requirements/%d' % rb, cookie=cookie)
                else:
                    check('R4 bug关联+计数', False, '关联探针缺失')
                    check('R4 发布确认人≠实施人拦截', False, '关联探针缺失')
                s, d = jreq('DELETE', '/api/releases/%d' % rel_id, cookie=cookie)
                check('R4 版本清理', d.get('ok'))
            else:
                check('R4 bug关联+计数', False, 'rel_id 缺失')
                check('R4 发布确认人≠实施人拦截', False, 'rel_id 缺失')
                check('R4 版本清理', False, 'rel_id 缺失')
            s2, _h, _b = http('GET', '/releases.html', headers={'Cookie': cookie})
            check('R4 版本页 200', s2 == 200)
            # ---- R5+R6：用例库 + 执行记录 ----
            s, d = jreq('POST', '/api/releases', {'project_id': dpid, 'version': 'v0.0-tc'}, cookie=cookie)
            rel2 = d.get('id')
            s, d = jreq('POST', '/api/testcases', {'project_id': dpid, 'title': '[verify] 登录正向用例',
                'steps_md': '前置：无\n步骤：正确账密登录\n预期：进入工作台', 'risk': 'high',
                'ctype': 'positive'}, cookie=cookie)
            tc_id = d.get('id')
            tc_code = d.get('tc_code')
            check('R5 用例创建+自动编号', bool(tc_id) and bool(tc_code) and tc_code.startswith('TC-'))
            if tc_id:
                s, d = jreq('GET', '/api/testcases/%d' % tc_id, cookie=cookie)
                check('R5 用例回读', d.get('tc', {}).get('status') == 'draft' and '正确账密登录' in d.get('steps_md', ''))
                s, d = jreq('PATCH', '/api/testcases/%d' % tc_id,
                            {'steps_md': '前置：无\n步骤：正确账密登录（改）\n预期：进入工作台', 'change_summary': '自检升版'}, cookie=cookie)
                check('R5 编辑升版 v2', d.get('ok') and d.get('version') == 2)
                s, d = jreq('PATCH', '/api/testcases/%d' % tc_id, {'op': 'status', 'status': 'approved'}, cookie=cookie)
                s, d = jreq('GET', '/api/testcases/%d' % tc_id, cookie=cookie)
                check('R5 批准落 approved_by', d.get('tc', {}).get('status') == 'approved' and d['tc'].get('approved_by'))
                s, d = jreq('PATCH', '/api/testcases/%d' % tc_id, {'steps_md': '批准后改动'}, cookie=cookie)
                s, d = jreq('GET', '/api/testcases/%d' % tc_id, cookie=cookie)
                check('R5 批准后编辑回草稿', d.get('tc', {}).get('status') == 'draft')
                # 抽屉↔用例库联动：需求详情 related_cases
                s, d = jreq('POST', '/api/requirements', {'project_id': dpid, 'title': '[verify] 用例联动探针'}, cookie=cookie)
                link_req = d.get('id')
                s, d = jreq('PATCH', '/api/testcases/%d' % tc_id, {'related_req': link_req}, cookie=cookie)
                s, d = jreq('GET', '/api/requirements/%d' % link_req, cookie=cookie)
                rcs = d.get('related_cases', [])
                check('抽屉联动 related_cases', bool(rcs) and any(c.get('id') == tc_id for c in rcs)
                      and rcs[0].get('tc_code', '').startswith('TC-'))
                if link_req:
                    s, d = jreq('DELETE', '/api/requirements/%d' % link_req, cookie=cookie)
                s, d = jreq('PUT', '/api/testcases/%d/execution' % tc_id,
                            {'release_id': rel2, 'result': 'pass', 'conclusion': '自检执行',
                             'dev_ref': '', 'ev_ref': 'EV-TEST'}, cookie=cookie)
                check('R6 执行记录录入', d.get('ok'))
                s, d = jreq('PUT', '/api/testcases/%d/execution' % tc_id,
                            {'release_id': rel2, 'result': 'fail', 'conclusion': '复测改判',
                             'dev_ref': 'DEV-1', 'ev_ref': ''}, cookie=cookie)
                s, d = jreq('GET', '/api/releases/%d/executions' % rel2, cookie=cookie)
                check('R6 按版本清单+upsert统计', d.get('ok') and len(d.get('items', [])) == 1
                      and d['items'][0].get('result') == 'fail' and d.get('stat', {}).get('fail') == 1)
                s, d = jreq('DELETE', '/api/testcases/%d' % tc_id, cookie=cookie)
                check('R5 用例清理', d.get('ok'))
            else:
                for nm in ('R5 用例回读', 'R5 编辑升版 v2', 'R5 批准后编辑回草稿', 'R6 执行记录录入',
                           'R6 按版本清单+upsert统计', 'R5 用例清理'):
                    check(nm, False, 'tc_id 缺失')
            if rel2:
                s, d = jreq('DELETE', '/api/releases/%d' % rel2, cookie=cookie)
            s2, _h, _b = http('GET', '/testcases.html', headers={'Cookie': cookie})
            check('R5 用例页 200', s2 == 200)
            # ---- #199 幂等键：同 client_token 两次创建返回同单 ----
            tok = 'verify-idem-' + os.urandom(8).hex()
            b1 = {'project_id': dpid, 'title': '[verify] 幂等探针', 'client_token': tok}
            s, d = jreq('POST', '/api/requirements', b1, cookie=cookie)
            idem_id = d.get('id')
            s, d = jreq('POST', '/api/requirements', b1, cookie=cookie)
            check('#199 幂等键去重', bool(idem_id) and d.get('dedup') and d.get('id') == idem_id)
            if idem_id:
                s, d = jreq('DELETE', '/api/requirements/%d' % idem_id, cookie=cookie)
            # ---- R7：评论类型（普通/验收标准；"测试用例"类型已移除防与用例库漂移）----
            s, d = jreq('POST', '/api/requirements', {'project_id': dpid, 'title': '[verify] R7探针', 'type': 'req'}, cookie=cookie)
            r7 = d.get('id')
            if r7:
                s, d = jreq('POST', '/api/requirements/%d/comment' % r7, {'text': '导出应含此条', 'ctype': 'ac'}, cookie=cookie)
                s, d = jreq('POST', '/api/requirements/%d/comment' % r7, {'text': '枚举外类型应回退普通', 'ctype': 'testcase'}, cookie=cookie)
                s, d = jreq('GET', '/api/requirements/%d' % r7, cookie=cookie)
                cms = [e for e in d.get('events', []) if e.get('action') == 'comment']
                check('R7 评论类型入库(枚举外回退normal)', len(cms) == 2
                      and {c.get('ctype') for c in cms} == {'ac', 'normal'})
                s2, _h, raw = http('GET', '/api/export?project=%d' % dpid, headers={'Cookie': cookie})
                txt = raw.decode('utf-8-sig', errors='replace')
                check('R7 导出验收标准汇总(ctype=ac口径)', '导出应含此条' in txt)
                s, d = jreq('DELETE', '/api/requirements/%d' % r7, cookie=cookie)
            else:
                for nm in ('R7 评论类型入库', 'R7 导出验收标准汇总(ctype=ac口径)'):
                    check(nm, False, 'r7 缺失')
        s, d = jreq('DELETE', '/api/projects/%d' % dpid, cookie=cookie)
        # 删除确认容忍 D1 读副本滞后：still 时延迟重查最多 3 次
        still = None
        for _ in range(4):
            s2, d2 = jreq('GET', '/api/projects', cookie=cookie)
            still = [p for p in d2.get('projects', []) if p['id'] == dpid]
            if not still:
                break
            time.sleep(2)
        if still:
            # 抖动兜底：删除未生效则按 id 再删一次（非幂等删除不盲重试，先查回确认）
            s, d = jreq('DELETE', '/api/projects/%d' % dpid, cookie=cookie)
            still = None
            for _ in range(3):
                s2, d2 = jreq('GET', '/api/projects', cookie=cookie)
                still = [p for p in d2.get('projects', []) if p['id'] == dpid]
                if not still:
                    break
                time.sleep(2)
        check('文档测试项目清理闭环', not still)
        # ---- #196 级联删除：带 docs/releases/test_cases 的项目可直接删 ----
        s, d = jreq('POST', '/api/projects', {'name': '[verify] 级联项目'}, cookie=cookie)
        cid = d.get('id')
        if cid:
            s, d = jreq('POST', '/api/docs', {'project_id': cid, 'title': '[verify] 级联doc', 'content_md': 'x'}, cookie=cookie)
            s, d = jreq('POST', '/api/releases', {'project_id': cid, 'version': 'v0.0-cascade'}, cookie=cookie)
            s, d = jreq('POST', '/api/testcases', {'project_id': cid, 'title': '[verify] 级联tc'}, cookie=cookie)
            s, d = jreq('DELETE', '/api/projects/%d' % cid, cookie=cookie)
            ok_del = bool(d) and d.get('ok')
            s2, d2 = jreq('GET', '/api/projects', cookie=cookie)
            gone = not any(p['id'] == cid for p in d2.get('projects', []))
            check('#196 级联删除（含doc/release/tc项目）', ok_del and gone)
    else:
        check('文档创建', False, 'dpid 缺失，无法执行')
    for path, name in [('/docs.html', '文档列表页 200'), ('/doc.html', '文档详情页 200'),
                       ('/marked.min.js', 'md 渲染库 200'), ('/purify.min.js', 'XSS 消毒库 200')]:
        s, _h, _b = http('GET', path, headers={'Cookie': cookie})
        check(name, s == 200)

    # 19. cookie 文件（pw.py 核对用）
    fd = os.open(COOKIE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, ('%s=%s' % (COOKIE_NAME, cookie.split('=', 1)[1])).encode())
    os.close(fd)
    check('核对 cookie 已更新', True, os.path.basename(COOKIE_FILE))

    fails = [n for n, ok in _results if not ok]
    print('\n== 自检完成：%d 项，失败 %d ==' % (len(_results), len(fails)))
    if fails:
        for n in fails:
            print('  FAIL:', n)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
