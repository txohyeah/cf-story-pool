#!/usr/bin/env python3
"""R10 图片存储体积月度统计（月度例会输入件；超 300MB 告警 exit 1）。
用法：python3 scripts/blob_stats.py
数据源：cf-story-pool-db 的 attachment_blobs（D1 BLOB 正式方案）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_d1  # noqa: E402

DB_LIMIT_BYTES = 500 * 1024 * 1024
THRESHOLD_BYTES = 300 * 1024 * 1024  # Free 单库 500MB 的 60%


def main():
    db = cf_d1.find_db()
    if not db:
        raise SystemExit('D1 数据库不存在，无法统计')
    success, rows, _meta, errors = cf_d1.execute_sql(db, (
        "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes, "
        "COALESCE(MAX(size), 0) AS max_bytes, "
        "COALESCE(SUM(CASE WHEN size > 300 * 1024 THEN 1 ELSE 0 END), 0) AS over_300k "
        "FROM attachment_blobs"))
    if not success or not rows:
        raise SystemExit('D1 容量查询失败：%s' % errors)
    row = rows[0]
    n = int(row.get('n') or 0)
    total = int(row.get('bytes') or 0)
    mx = int(row.get('max_bytes') or 0)
    over = int(row.get('over_300k') or 0)
    gb = total / 1024 / 1024 / 1024
    print('== 附件 BLOB 体积月度统计（%s）==' % cf_d1.DB_NAME)
    print('BLOB 数量：%d' % n)
    print('总体积：%.2f GB（%d bytes）' % (gb, total))
    print('最大单张：%.1f KB' % (mx / 1024))
    print('>300KB 未压缩嫌疑：%d 张' % over)
    print('占库上限百分比：%.1f%%（Free 单库上限 500MB；告警阈值 300MB / 60%%）' % (total / DB_LIMIT_BYTES * 100))
    if total > THRESHOLD_BYTES:
        print('⚠️ 超过 300MB 阈值：触发迁移评估（storage 抽象层已就位，可切 OSS/R2 后端）')
        raise SystemExit(1)
    print('未超阈值，无需迁移。')


if __name__ == '__main__':
    main()
