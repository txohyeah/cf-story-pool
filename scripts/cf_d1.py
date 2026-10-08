#!/usr/bin/env python3
"""cf-story-pool 的 D1 桥接（照抄 zhixidao/scripts/cf_d1.py，改库名/项目名）。
token 从 workspace 的 .secrets/cf_api_token 读取，不回显。
用法：
  python3 scripts/cf_d1.py create-bound      # 建库+绑定
  python3 scripts/cf_d1.py exec <file.sql>   # 执行 SQL 文件（按 ';\\n' 切分）
  python3 scripts/cf_d1.py query <file.sql>  # 执行 SQL 并输出每语句结果 JSON（SELECT 用）
  python3 scripts/cf_d1.py query --one "SQL" # 直接传内联 SQL（分号分隔）
  python3 scripts/cf_d1.py info              # 打印 db id / 绑定情况
"""
import json
import os
import re
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
DB_NAME = 'cf-story-pool-db'
PROJECT = 'cf-story-pool'
BINDING = 'DB'


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
        return json.loads(e.read().decode())


def find_db():
    d = call('GET', f'/accounts/{ACCOUNT_ID}/d1/database?name={DB_NAME}')
    if d.get('success'):
        for row in d.get('result', []):
            if row.get('name') == DB_NAME:
                return row
    return None


def create_db():
    existing = find_db()
    if existing:
        print('D1 已存在:', existing['uuid'])
        return existing
    d = call('POST', f'/accounts/{ACCOUNT_ID}/d1/database', {'name': DB_NAME})
    if not d.get('success'):
        raise SystemExit('创建 D1 失败: ' + json.dumps(d.get('errors'), ensure_ascii=False))
    print('D1 已创建:', d['result']['uuid'])
    return d['result']


def bind_db(db):
    d = call('PATCH', f'/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}', {
        'deployment_configs': {
            'production': {
                'd1_databases': {
                    BINDING: {'id': db['uuid'], 'name': DB_NAME}
                }
            }
        }
    })
    if not d.get('success'):
        raise SystemExit('绑定失败: ' + json.dumps(d.get('errors'), ensure_ascii=False))
    print('绑定成功: binding=' + BINDING, '→', db['uuid'])
    return d


def project_bindings():
    d = call('GET', f'/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}')
    if not d.get('success'):
        return None
    prod = d['result'].get('deployment_configs', {}).get('production', {})
    return {'d1': prod.get('d1_databases'), 'r2': prod.get('r2_buckets')}


def execute_sql(db, sql):
    """执行单条 SQL，返回 (success, rows, meta, errors)。"""
    d = call('POST', f'/accounts/{ACCOUNT_ID}/d1/database/{db["uuid"]}/query', {'sql': sql})
    if not d.get('success'):
        return False, None, None, d.get('errors')
    res = d.get('result', [{}])[0]
    return True, res.get('results', []), res.get('meta', {}), None


def exec_sql_file(db, path):
    sql = open(path).read()
    stmts = split_statements(sql)
    for i, stmt in enumerate(stmts, 1):
        ok, _rows, meta, errors = execute_sql(db, stmt)
        if not ok:
            print(f'[FAIL] 语句 {i}: {stmt[:120]}...')
            print('  errors:', json.dumps(errors, ensure_ascii=False)[:500])
            raise SystemExit(1)
        print(f'[OK] 语句 {i} rows_changed={meta.get("rows_changed", 0)} rows_written={meta.get("rows_written", 0)} last_row_id={meta.get("last_row_id", "")}')


def split_statements(sql):
    """按 ';\\n' 切分语句。丢弃纯注释块。触发器必须单行书写。"""
    out = []
    for s in re.split(r';\s*\n', sql):
        s = s.strip()
        if not s:
            continue
        if not any(ln.strip() and not ln.strip().startswith('--') for ln in s.splitlines()):
            continue
        out.append(s)
    return out


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'info'
    if cmd == 'create-bound':
        db = create_db()
        bind_db(db)
    elif cmd == 'exec':
        db = find_db()
        if not db:
            raise SystemExit('D1 不存在，先跑 create-bound')
        exec_sql_file(db, sys.argv[2])
    elif cmd == 'query':
        db = find_db()
        if not db:
            raise SystemExit('D1 不存在，先跑 create-bound')
        if sys.argv[2] == '--one':
            stmts = [s.strip() for s in sys.argv[3].split(';') if s.strip()]
        else:
            stmts = split_statements(open(sys.argv[2]).read())
        for i, stmt in enumerate(stmts, 1):
            ok, rows, _meta, errors = execute_sql(db, stmt)
            if not ok:
                print(f'[FAIL] 语句 {i}: {stmt[:120]}...')
                print('  errors:', json.dumps(errors, ensure_ascii=False)[:500])
                raise SystemExit(1)
            print(json.dumps(rows, ensure_ascii=False))
    elif cmd == 'info':
        db = find_db()
        print('db:', db['uuid'] if db else None)
        print('bindings:', json.dumps(project_bindings(), ensure_ascii=False))
    else:
        raise SystemExit('未知命令')
