-- 用户种子（哈希含随机盐；重跑会使这些账号的所有会话失效）
DELETE FROM users WHERE username IN ('xiao', 'zhoubin', 'chenhaiyan', 'qwenpaw');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('xiao', 'pbkdf2$100000$BqP2uVbc6ic1bYtzPsSF3w==$h2KO9RDKgxLDwbJ55WpH/mreh1dF91xx0+qIXtvtrtE=', 'member', '晓', 1, '2026-10-08T00:00:00Z');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('zhoubin', 'pbkdf2$100000$QGoRC9WL7LhBgCfYcoB0uQ==$ymnMlxmNGxCJ+p87c4HkY2Swds27MfwhH1at3rm5v0k=', 'member', '周斌', 1, '2026-10-08T00:00:00Z');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('chenhaiyan', 'pbkdf2$100000$pTAnHY4X2qjDr5uMSTNmow==$sZ0RzZaGbOM0uerd681+OKoA8uF0csaG7QUN33P5XF4=', 'member', '陈海燕', 1, '2026-10-08T00:00:00Z');
INSERT INTO users (username, pw_hash, role, display_name, active, created_at) VALUES ('qwenpaw', 'pbkdf2$100000$kXbHywFT3AdigXcgShQr7Q==$nWIBLY8lqSUgb8vzE+PmMsHT29kT+tIoZNGMgquuuPI=', 'member', '助理', 1, '2026-10-08T00:00:00Z');
