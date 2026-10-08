#!/usr/bin/env python3
"""需求池用户种子 SQL（xiao + zhoubin + chenhaiyan + qwenpaw）。
密码来源：workspace/.secrets/story_pool_pass_xiao / _zhoubin / _chenhaiyan / story_pool_qwenpaw
（绝不回显/落日志）。输出 data/seed_users.sql（仅含 PBKDF2 哈希，无明文）。
格式与 worker 一致：pbkdf2$100000$salt_b64$hash_b64
注意：重跑会先删同名单再插，会使这些账号的所有会话失效。
"""
import base64
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))
ITER = 100000
KEYLEN = 32

USERS = [
    ('xiao', '晓', 'story_pool_pass_xiao'),
    ('zhoubin', '周斌', 'story_pool_pass_zhoubin'),
    ('chenhaiyan', '陈海燕', 'story_pool_pass_chenhaiyan'),
    ('qwenpaw', '助理', 'story_pool_qwenpaw'),
]


def hash_pass(pw: str) -> str:
    salt = os.urandom(16)
    bits = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, ITER, KEYLEN)
    return 'pbkdf2$%d$%s$%s' % (ITER, base64.b64encode(salt).decode(), base64.b64encode(bits).decode())


def sqlq(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def main():
    rows = []
    for who, display, secret in USERS:
        pw = open(os.path.join(WORKSPACE, '.secrets', secret)).read().strip()
        if len(pw) < 6:
            raise SystemExit('%s 密码文件异常（<6 位）' % secret)
        rows.append((who, hash_pass(pw), display))
    names = ', '.join(sqlq(r[0]) for r in rows)
    lines = [
        '-- 用户种子（哈希含随机盐；重跑会使这些账号的所有会话失效）',
        'DELETE FROM users WHERE username IN (%s);' % names,
    ]
    for who, h, display in rows:
        lines.append(
            "INSERT INTO users (username, pw_hash, role, display_name, active, created_at) "
            "VALUES (%s, %s, 'member', %s, 1, '2026-10-08T00:00:00Z');" % (sqlq(who), sqlq(h), sqlq(display))
        )
    out = os.path.join(ROOT, 'data', 'seed_users.sql')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('已生成', out, '（密码未回显）')


if __name__ == '__main__':
    main()
