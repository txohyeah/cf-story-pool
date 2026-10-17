#!/usr/bin/env python3
"""R10 图片存储体积月度统计（月度例会输入件；超 3GB 告警 exit 1）。
用法：python3 scripts/blob_stats.py
数据源：cf-story-pool-db 的 attachment_blobs（D1 BLOB 正式方案）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_d1  # noqa: E402

THRESHOLD_BYTES = 3 * 1024 * 1024 * 1024  # 3GB 定案阈值


def main():
    db = cf_d1.find_db()
    res = cf_d1.execute_sql(db, (
        "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes, "
        "COALESCE(MAX(size), 0) AS max_bytes, "
        "COALESCE(SUM(CASE WHEN size > 300 * 1024 THEN 1 ELSE 0 END), 0) AS over_300k "
        "FROM attachment_blobs"))
    row = (res[0].get('results') or [{}])[0] if res and isinstance(res, list) else {}
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
    print('阈值：3GB → 当前使用 %.1f%%' % (gb / 3 * 100))
    if total > THRESHOLD_BYTES:
        print('⚠️ 超过 3GB 阈值：触发迁移评估（storage 抽象层已就位，可切 OSS/R2 后端）')
        raise SystemExit(1)
    print('未超阈值，无需迁移。')


if __name__ == '__main__':
    main()
