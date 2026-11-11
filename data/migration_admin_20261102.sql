-- 已执行迁移模板：把站点管理员账号升为 admin（执行时把 <ADMIN_USERNAME> 换成实际账号名）
UPDATE users SET role = 'admin' WHERE username = '<ADMIN_USERNAME>';
