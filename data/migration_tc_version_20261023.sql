-- 执行记录绑定执行时的用例修订号；NULL 保留存量含义，不回填。
ALTER TABLE tc_executions ADD COLUMN tc_version INTEGER;
