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
import urllib.error
import urllib.request
import zlib

try:
    import certifi
    import ssl
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = None

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
if _CTX is not None:
    _opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_CTX))
else:
    _opener = urllib.request.build_opener(_NoRedirect)


def http(method, path, data=None, headers=None):
    """返回 (status, resp_headers, body_bytes)。不跟随重定向；带超时+重试。"""
    import json as _json
    for attempt in range(3):
        req = urllib.request.Request(BASE + path, method=method, data=data)
        req.add_header('User-Agent', UA)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with _opener.open(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
        except (urllib.error.URLError, OSError) as e:
            if attempt == 2:
                raise
            print('  (网络重试 %d: %s)' % (attempt + 1, e))


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

    # 17. cookie 文件（pw.py 核对用）
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
