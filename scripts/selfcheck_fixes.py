#!/usr/bin/env python3
"""离线修复回归：真实 Worker + SQLite :memory: D1 适配器，无网络、不读取凭据。

运行：python3 scripts/selfcheck_fixes.py
Python 驱动 Node 执行 API，SQL 经 JSON 行协议发送到内存库；batch 使用事务。
"""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    'migration_r3_fields_20261017.sql', 'migration_r4_releases_20261017.sql',
    'migration_r5r6_testcases_20261017.sql', 'migration_docs_20261017.sql',
    'migration_tc_approve_20261017.sql', 'migration_r7_ctype_20261017.sql',
    'migration_idem_20261018.sql', 'migration_counters_20261017.sql',
    'migration_tc_version_20261023.sql',
]

# 调用真实 fetch 路由；仅 D1 binding 被替换为 SQLite RPC，未复制业务算法。
NODE_TESTS = r'''
import assert from 'node:assert/strict';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { webcrypto } from 'node:crypto';
globalThis.crypto ??= webcrypto;
const worker = (await import(pathToFileURL(process.argv[1]))).default;
const pending = new Map(); let sequence = 0, binds = 0, queries = 0, barrier = null;
const input = createInterface({ input: process.stdin });
input.on('line', line => {
  const reply = JSON.parse(line), waiter = pending.get(reply.id);
  pending.delete(reply.id);
  if (reply.error) waiter.reject(new Error(reply.error)); else waiter.resolve(reply.result);
});
function rpc(op, data) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    process.stdout.write(JSON.stringify({ id, op, ...data }) + '\n');
  });
}
const DB = {
  prepare(sql) {
    return {
      sql, params: [],
      bind(...params) {
        assert.ok(params.length <= 100, 'D1 bind limit'); binds = Math.max(binds, params.length);
        this.params = params; return this;
      },
      async all() { queries++; return rpc('query', { sql: this.sql, params: this.params }); },
      async run() { return this.all(); },
      async first() {
        const result = (await this.all()).results[0] || null;
        if (barrier && /SELECT \* FROM (docs|test_cases) WHERE id/.test(sql)) {
          const current = barrier;
          if (++current.reads === 2) { barrier = null; current.release(); }
          await current.promise;
        }
        return result;
      }
    };
  },
  async batch(statements) { queries += statements.length; return rpc('batch', { statements }); }
};
const sql = async (query, ...params) => DB.prepare(query).bind(...params).all();
async function api(path, method = 'GET', body) {
  const headers = { Cookie: 'storypool_auth=test-session' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  return worker.fetch(new Request('https://selfcheck.invalid' + path, {
    method, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {})
  }), { DB });
}
async function object(response, expected = 200) {
  assert.equal(response.status, expected, await response.clone().text()); return response.json();
}
function pass(name) { process.stdout.write(JSON.stringify({ op: 'pass', name }) + '\n'); }
function concurrentReads() {
  let release; const promise = new Promise(resolve => { release = resolve; });
  barrier = { reads: 0, release, promise };
}
try {
  // #1：第二条 SQL 人为违反附件 UNIQUE，必须回滚首条主记录和 FTS。
  await sql("INSERT INTO requirements(id,project_id,title,client_token,created_by) VALUES(1,1,'seed','seed',1)");
  await sql("INSERT INTO attachments(req_id,store_key) VALUES(1,'existing-token')");
  const failed = await api('/api/requirements', 'POST', {
    project_id: 1, title: 'rollback-marker', client_token: 'must-rollback',
    attachments: [{ key: 'existing-token', name: 'test.png', size: 1 }]
  });
  await object(failed, 500);
  assert.equal((await sql("SELECT id FROM requirements WHERE client_token='must-rollback'")).results.length, 0);
  assert.equal((await sql("SELECT rowid FROM requirements_fts WHERE requirements_fts MATCH 'rollback'")).results.length, 0);
  const created = await object(await api('/api/requirements', 'POST', {
    project_id: 1, title: 'complete', client_token: 'idempotent', tags: ['test']
  }));
  const repeated = await object(await api('/api/requirements', 'POST', {
    project_id: 1, title: 'complete', client_token: 'idempotent', tags: ['test']
  }));
  assert.equal(created.id, repeated.id); assert.equal(repeated.dedup, true);
  assert.equal((await sql('SELECT id FROM events WHERE req_id=?', created.id)).results.length, 1);
  assert.equal((await sql('SELECT * FROM requirement_tags WHERE req_id=?', created.id)).results.length, 1);
  pass('#1 batch 第二语句失败不留主记录/FTS；完整提交后幂等重试');

  // #2：存在执行记录禁止删除，所有行和关联均保持。
  await sql("INSERT INTO releases(id,project_id,version) VALUES(1,1,'v1'),(2,2,'v2'),(3,1,'empty')");
  await sql('UPDATE requirements SET release_id=1 WHERE id=1');
  const tc = await object(await api('/api/testcases', 'POST', { project_id: 1, title: 'case', steps_md: 'steps-v1' }));
  await object(await api(`/api/testcases/${tc.id}/execution`, 'PUT', { release_id: 1, result: 'pass' }));
  const before = (await sql('SELECT * FROM requirements WHERE id=1')).results;
  const denied = await object(await api('/api/releases/1', 'DELETE'), 400);
  assert.match(denied.error, /执行记录/);
  assert.deepEqual((await sql('SELECT * FROM requirements WHERE id=1')).results, before);
  assert.equal((await sql('SELECT id FROM releases WHERE id=1')).results.length, 1);
  assert.equal((await sql('SELECT id FROM tc_executions WHERE release_id=1')).results.length, 1);
  await object(await api('/api/releases/3', 'DELETE'));
  pass('#2 有执行记录删版本返回400且数据无损；空版本可删除');

  // #3：让两个真实请求都读到旧版本，再依次提交 batch，验证 CAS 而非仅预检查。
  const doc = await object(await api('/api/docs', 'POST', { project_id: 1, title: 'doc', content_md: 'v1' }));
  concurrentReads();
  const edits = await Promise.all(['v2-a', 'v2-b'].map(content_md => api(`/api/docs/${doc.id}`, 'PATCH', { expected_version: 1, content_md })));
  assert.deepEqual(edits.map(r => r.status).sort(), [200, 409]);
  assert.match((await edits.find(r => r.status === 409).json()).error, /内容已被他人修改，请刷新/);
  assert.equal((await sql('SELECT current_version FROM docs WHERE id=?', doc.id)).results[0].current_version, 2);
  assert.equal((await sql('SELECT * FROM doc_versions WHERE doc_id=?', doc.id)).results.length, 2);
  concurrentReads();
  const tcEdits = await Promise.all(['steps-v2a', 'steps-v2b'].map(steps_md => api(`/api/testcases/${tc.id}`, 'PATCH', { expected_version: 1, steps_md })));
  assert.deepEqual(tcEdits.map(r => r.status).sort(), [200, 409]);
  assert.equal((await sql('SELECT * FROM test_case_versions WHERE tc_id=?', tc.id)).results.length, 2);
  pass('#3 文档和用例并发编辑一个200、一个409，无多余快照');

  // #4：从真实 CSV 响应验证公式被文本化，负数放行。
  await sql("INSERT INTO requirements(project_id,title,ref_code,created_by) VALUES(1,'=cmd','-123.5',1)");
  const csv = await (await api('/api/export?project=1')).text();
  assert.ok(csv.includes('"\'=cmd"')); assert.ok(csv.includes('"-123.5"')); assert.ok(!csv.includes('"\'-123.5"'));
  await sql("UPDATE requirements SET title='  @SUM(1)' WHERE title='=cmd'");
  assert.ok((await (await api('/api/export?project=1')).text()).includes('"\'  @SUM(1)"'));
  pass('#4 CSV =cmd及前导空白公式被防护，纯负数放行');

  // #8：三个入口均执行SQL；101个重复枚举不能产生101个绑定。
  const repeatedStatus = new URLSearchParams({ status: Array(101).fill('submitted').join(',') });
  for (const path of ['/api/requirements', '/api/my-work', '/api/export']) {
    const response = await api(path + '?' + repeatedStatus); assert.equal(response.status, 200);
  }
  assert.ok(binds <= 100);
  pass('#8 三个入口101个重复status去重，不超过D1绑定上限');

  // #9：四个搜索入口均明确400，含转义膨胀边界。
  for (const path of ['/api/requirements', '/api/my-work', '/api/dedup-suggest', '/api/export']) {
    const response = await api(path + '?' + new URLSearchParams({ q: '中'.repeat(17) }));
    assert.match((await object(response, 400)).error, /50.*UTF-8/);
  }
  await object(await api('/api/requirements?' + new URLSearchParams({ q: '%'.repeat(25) })), 400);
  await object(await api('/api/requirements?' + new URLSearchParams({ q: '中'.repeat(16) })));
  pass('#9 17个中文token/转义后超限返回400，16个中文边界可查询');

  // #5/#6：已执行版本锁定历史步骤，重测覆盖版本号，跨项目关联拒绝。
  let execs = await object(await api('/api/releases/1/executions'));
  assert.equal(execs.items[0].tc_version, 1); assert.equal(execs.items[0].executed_steps_md, 'steps-v1');
  await object(await api(`/api/testcases/${tc.id}/execution`, 'PUT', { release_id: 1, result: 'fail' }));
  execs = await object(await api('/api/releases/1/executions'));
  assert.equal(execs.items.length, 1); assert.equal(execs.items[0].tc_version, 2); assert.equal(execs.items[0].result, 'fail');
  await object(await api('/api/requirements/1', 'PATCH', { op: 'edit', release_id: 2 }), 400);
  await sql("INSERT INTO requirements(id,project_id,title) VALUES(100,2,'other project')");
  await object(await api('/api/testcases', 'POST', { project_id: 1, title: 'bad link', related_req: 100 }), 400);
  await object(await api(`/api/testcases/${tc.id}`, 'PATCH', { expected_version: 2, related_req: 100 }), 400);
  await object(await api(`/api/testcases/${tc.id}/execution`, 'PUT', { release_id: 2, result: 'pass' }), 400);
  await object(await api('/api/requirements/1', 'PATCH', { op: 'edit', project_id: 2, release_id: 1 }));
  assert.equal((await sql('SELECT release_id FROM requirements WHERE id=1')).results[0].release_id, null);
  pass('#5/#6 执行版本历史/重测覆盖及跨项目校验');

  // #7/#16：CSV筛选、验收标准JOIN、截断告警；5001条包导出仍为常量查询数。
  await sql("UPDATE requirements SET title='match-key', urgency='urgent' WHERE client_token='idempotent'");
  await sql("INSERT INTO events(req_id,actor_id,action,ctype,detail) VALUES(?,1,'comment','ac','acceptance-marker')", created.id);
  const filtered = await (await api('/api/export?project=1&urgency=urgent&q=match-key')).text();
  assert.ok(filtered.includes('match-key')); assert.ok(filtered.includes('acceptance-marker')); assert.ok(!filtered.includes('seed'));
  await sql("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<5001) INSERT INTO requirements(project_id,title) SELECT 1,'bulk-'||x FROM n");
  let start = queries;
  const bulk = await (await api('/api/export?project=1')).text();
  assert.ok(bulk.includes('警告：结果超过 5000 条')); assert.equal(queries - start, 3);
  start = queries;
  const pkg = await object(await api('/api/export-package?project=1'));
  assert.ok(pkg.requirements.length > 5000); assert.ok(queries - start <= 10);
  pass('#7/#16 JOIN导出/关键词紧急度筛选/5000条截断告警/数据包常量查询');

  // #18：非对象和错误字段类型都400，认证门禁仍有效。
  for (const body of [null, [], { title: 123 }, { tags: 'bad' }, { project_id: {} }]) {
    await object(await api('/api/requirements', 'POST', body), 400);
  }
  assert.equal((await worker.fetch(new Request('https://selfcheck.invalid/api/requirements'), { DB })).status, 401);
  const upload = new FormData(); upload.append('file', new Blob([new Uint8Array(1572865)], { type: 'image/png' }), 'too-big.png');
  const uploadResponse = await worker.fetch(new Request('https://selfcheck.invalid/api/upload', { method: 'POST', headers: { Cookie: 'storypool_auth=test-session' }, body: upload }), { DB });
  assert.match((await object(uploadResponse, 400)).error, /1.5MB/);
  pass('#10/#18 上传上限、输入类型400、匿名门禁');
  input.close();
} catch (error) {
  console.error(error); process.exitCode = 1; input.close();
}
'''


def build_db():
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript((ROOT / 'schema.sql').read_text())
    # 复用 cf_d1.py 的原始切分函数，避免 import 时读取外部配置/凭据。
    tree = ast.parse((ROOT / 'scripts/cf_d1.py').read_text())
    split_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'split_statements')
    import re
    namespace = {'re': re}
    exec(compile(ast.Module(body=[split_fn], type_ignores=[]), '<split_statements>', 'exec'), namespace)
    for name in MIGRATIONS:
        for statement in namespace['split_statements']((ROOT / 'data' / name).read_text()):
            db.execute(statement)
    db.executescript("""
      INSERT INTO users(id,username,display_name,pw_hash) VALUES(1,'selfcheck','Selfcheck','unused');
      INSERT INTO sessions(token,user_id,expires_at) VALUES('test-session',1,'2099-01-01T00:00:00.000Z');
      INSERT INTO projects(id,name) VALUES(1,'A'),(2,'B');
    """)
    return db


def execute(db, statement):
    params = statement.get('params', [])
    if len(params) > 100:
        raise ValueError('D1 bind limit exceeded')
    cursor = db.execute(statement['sql'], params)
    rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
    changes = db.execute('SELECT changes()').fetchone()[0]
    return {'results': rows, 'meta': {'changes': changes, 'last_row_id': cursor.lastrowid}, 'success': True}


def run_worker_checks():
    db = build_db()
    proc = subprocess.Popen(['node', '--input-type=module', '-e', NODE_TESTS, str(ROOT / 'worker_src/_worker.js')],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True, bufsize=1)
    try:
        for line in proc.stdout:
            message = json.loads(line)
            if message['op'] == 'pass':
                print('PASS', message['name'], flush=True)
                continue
            try:
                if message['op'] == 'batch':
                    db.execute('SAVEPOINT d1_batch')
                    try:
                        result = [execute(db, statement) for statement in message['statements']]
                        db.execute('RELEASE d1_batch')
                    except Exception:
                        db.execute('ROLLBACK TO d1_batch')
                        db.execute('RELEASE d1_batch')
                        raise
                else:
                    result = execute(db, message)
                reply = {'id': message['id'], 'result': result}
            except Exception as error:
                reply = {'id': message['id'], 'error': str(error)}
            proc.stdin.write(json.dumps(reply) + '\n')
            proc.stdin.flush()
        code = proc.wait(timeout=10)
        if code:
            raise SystemExit(code)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        db.close()


def run_script_checks():
    # docgen 导入没有网络/凭据副作用；模拟响应，验证实际分页与错误路径。
    spec = importlib.util.spec_from_file_location('docgen_selfcheck', ROOT / 'scripts/docgen.py')
    docgen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docgen)

    class Response:
        def __init__(self, status, body):
            self.status_code, self.body = status, body

        def json(self):
            return self.body

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout):
            from urllib.parse import urlparse, parse_qs
            page = int(parse_qs(urlparse(url).query)['page'][0])
            self.calls.append(page)
            return Response(200, {'ok': True, 'total': 120, 'pages': 3, 'page': page,
                                  'items': [{'id': n} for n in range((page-1)*50, min(page*50, 120))]})

    session = Session()
    assert len(docgen.get_requirements(session, 1)) == 120
    assert session.calls == [1, 2, 3]
    for response in [Response(401, {'error': '未登录'}), Response(200, {'ok': False})]:
        try:
            docgen.checked_json(response, 'test')
        except SystemExit:
            pass
        else:
            raise AssertionError('错误响应未失败退出')
    print('PASS #11/#12 docgen完整分页及HTTP/业务失败退出')

    # 提取 main 避免 blob_stats 顶层 import cf_d1 时读取凭据。
    tree = ast.parse((ROOT / 'scripts/blob_stats.py').read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')

    class D1:
        DB_NAME = 'memory'

        def find_db(self):
            return {'uuid': 'memory'}

        def execute_sql(self, *_):
            return True, [{'n': 10, 'bytes': 301*1024**2, 'max_bytes': 0, 'over_300k': 0}], {}, None

    namespace = {'cf_d1': D1(), 'THRESHOLD_BYTES': 300*1024**2, 'DB_LIMIT_BYTES': 500*1024**2}
    exec(compile(ast.Module(body=[main], type_ignores=[]), '<blob_stats>', 'exec'), namespace)
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            namespace['main']()
    except SystemExit as error:
        assert error.code == 1
    else:
        raise AssertionError('301MB未触发容量告警')
    assert '60.2%' in output.getvalue()
    print('PASS #13 正确解包容量查询，301MB告警且占库60.2%')

    # 生成器以假凭据/内存文件运行，验证输出SQL不会删除用户并保留原ID。
    spec = importlib.util.spec_from_file_location('seed_selfcheck', ROOT / 'scripts/seed_users.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    generated = io.StringIO()

    class Output(io.StringIO):
        def close(self):
            generated.write(self.getvalue())
            super().close()

    def fake_open(path, mode='r'):
        return Output() if mode == 'w' else io.StringIO('fake-test-password')

    from unittest.mock import patch
    with patch('builtins.open', fake_open), patch.object(seed.os, 'makedirs'), contextlib.redirect_stdout(io.StringIO()):
        seed.main()
    db = build_db()
    db.execute("INSERT INTO users(id,username,display_name,pw_hash) VALUES(42,'xiao','old','old')")
    db.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES('old-session',42,'2099')")
    db.executescript(generated.getvalue())
    assert db.execute("SELECT id FROM users WHERE username='xiao'").fetchone()[0] == 42
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE user_id=42").fetchone()[0] == 0
    assert 'data/seed_users.sql' in (ROOT / '.gitignore').read_text()
    db.close()
    print('PASS #14/#15 UPSERT保留用户ID、会话可撤销、生成文件已加入忽略规则')


if __name__ == '__main__':
    run_worker_checks()
    run_script_checks()
    print('PASS 全部离线修复自检通过；未访问线上D1或凭据')
