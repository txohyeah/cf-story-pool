#!/usr/bin/env python3
"""需求池用户种子 SQL。
账号表（用户名/显示名/凭据文件名）从本地私有配置读取：data/local_config.json（不入库，示例见
data/local_config.example.json；环境变量 POOL_USERS 可覆盖）。密码绝不回显/落日志。
输出 data/seed_users.sql（仅含 PBKDF2 哈希，无明文）。
格式与 worker 一致：pbkdf2$100000$salt_b64$hash_b64
注意：重跑使用 UPSERT 保留用户 ID，并删除这些账号的会话。
"""
import base64
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))
ITER = 100000
KEYLEN = 32

from _localcfg import get  # 同目录模块：读本地未入库配置

USERS = get('users', [])


def hash_pass(pw: str) -> str:
    salt = os.urandom(16)
    bits = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, ITER, KEYLEN)
    return 'pbkdf2$%d$%s$%s' % (ITER, base64.b64encode(salt).decode(), base64.b64encode(bits).decode())


def sqlq(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def main():
    rows = []
    if not USERS:
        raise SystemExit('缺少用户配置：请复制 data/local_config.example.json 为 data/local_config.json 并填写')
    for u in USERS:
        who, display, secret = u['username'], u.get('display', ''), u['pass_file']
        pw = open(os.path.join(WORKSPACE, '.secrets', secret)).read().strip()
        if len(pw) < 6:
            raise SystemExit('%s 密码文件异常（<6 位）' % secret)
        rows.append((who, hash_pass(pw), display))
    names = ', '.join(sqlq(r[0]) for r in rows)
    lines = [
        '-- 用户种子（哈希含随机盐；重跑会使这些账号的所有会话失效）',
    ]
    for who, h, display in rows:
        lines.append(
            "INSERT INTO users (username, pw_hash, role, display_name, active, created_at) "
            "VALUES (%s, %s, 'member', %s, 1, '2026-10-08T00:00:00Z') ON CONFLICT(username) DO UPDATE SET pw_hash = excluded.pw_hash, display_name = excluded.display_name, active = 1;" % (sqlq(who), sqlq(h), sqlq(display))
        )
    lines.append('DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username IN (%s));' % names)
    out = os.path.join(ROOT, 'data', 'seed_users.sql')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('已生成', out, '（密码未回显）')


if __name__ == '__main__':
    main()
