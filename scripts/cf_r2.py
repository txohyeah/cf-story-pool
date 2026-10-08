#!/usr/bin/env python3
"""R2 桶创建 + 绑定到 Pages 项目（cf-story-pool）。token: .secrets/cf_api_token（不回显）。
用法：
  python3 scripts/cf_r2.py create-bound   # 建桶 + 绑定到 Pages 项目（production & preview）
  python3 scripts/cf_r2.py info           # 查看桶与绑定状态
"""
import json
import os
import sys
import urllib.request
import urllib.error
import ssl
try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))
CONFIG = json.load(open(os.path.join(WORKSPACE, 'tools', 'publish-web', 'config.json')))
ACCOUNT_ID = CONFIG['account_id']
TOKEN = open(os.path.join(WORKSPACE, '.secrets', 'cf_api_token')).read().strip()
API = 'https://api.cloudflare.com/client/v4'
BUCKET = 'story-pool-assets'
PROJECT = 'cf-story-pool'
BINDING = 'BUCKET'


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header('Authorization', 'Bearer ' + TOKEN)
    req.add_header('Content-Type', 'application/json')
    data = json.dumps(body).encode() if body is not None else None
    try:
        if _CTX is not None:
            with urllib.request.urlopen(req, data=data, context=_CTX) as r:
                return json.loads(r.read().decode())
        else:
            with urllib.request.urlopen(req, data=data) as r:
                return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {'success': False, 'errors': [{'message': 'HTTP %d' % e.code}]}


def find_bucket():
    d = call('GET', f'/accounts/{ACCOUNT_ID}/r2/buckets')
    if d.get('success'):
        for b in (d.get('result', {}) or {}).get('buckets', []):
            if b.get('name') == BUCKET:
                return b
    return None


def create_bucket():
    existing = find_bucket()
    if existing:
        print('R2 桶已存在:', BUCKET)
        return existing
    d = call('POST', f'/accounts/{ACCOUNT_ID}/r2/buckets', {'name': BUCKET})
    if not d.get('success'):
        raise SystemExit('创建 R2 桶失败: ' + json.dumps(d.get('errors'), ensure_ascii=False))
    print('R2 桶已创建:', BUCKET)
    return d['result']


def bind_bucket():
    r2_cfg = {BINDING: {'name': BUCKET}}
    d = call('PATCH', f'/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}', {
        'deployment_configs': {
            'production': {'r2_buckets': r2_cfg},
            'preview': {'r2_buckets': r2_cfg}
        }
    })
    if not d.get('success'):
        raise SystemExit('绑定 R2 失败: ' + json.dumps(d.get('errors'), ensure_ascii=False))
    print('绑定成功: binding=' + BINDING, '→', BUCKET, '（production & preview）')
    return d


def project_bindings():
    d = call('GET', f'/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}')
    if not d.get('success'):
        return None
    prod = d['result'].get('deployment_configs', {}).get('production', {})
    return {'d1': prod.get('d1_databases'), 'r2': prod.get('r2_buckets')}


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'info'
    if cmd == 'create-bound':
        create_bucket()
        bind_bucket()
    elif cmd == 'info':
        b = find_bucket()
        print('bucket:', b.get('name') if b else None)
        print('bindings:', json.dumps(project_bindings(), ensure_ascii=False))
    else:
        raise SystemExit('未知命令')
