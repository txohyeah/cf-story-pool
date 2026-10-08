-- 用户种子（哈希含随机盐；重跑会使这些账号的所有会话失效）
DELETE FROM users WHERE username IN ('xiao', 'zhoubin', 'chenhaiyan', 'qwenpaw');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('xiao', 'pbkdf2$100000$s2dg8lmJijGHaaGGoJTVUg==$Sa+PFkOQR5+1lDPEg3m9cm7cQrJWX9VypszgB5TjKqk=', 'member', '晓', 1, '2026-10-08T00:00:00Z');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('zhoubin', 'pbkdf2$100000$+pYpnNsgj6v3/gBN/BpOQA==$PK9/Kck74QVDRz9DnhI5XrdGPBpVS6qy+xvFQG0tRWE=', 'member', '周斌', 1, '2026-10-08T00:00:00Z');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('chenhaiyan', 'pbkdf2$100000$64bvTmMpyyze8/v8FGU/wg==$zu9F6FID234p02zwq3BhVzuoYLZuWYPDjk0n3vUigNs=', 'member', '陈海燕', 1, '2026-10-08T00:00:00Z');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('qwenpaw', 'pbkdf2$100000$D2tG8Rilr1zQxyX3iuuT9Q==$LkXAyyIMHxD72FYqc/bfW9NBhIpa0JS3q5qlSjZidFE=', 'member', '助理', 1, '2026-10-08T00:00:00Z');
