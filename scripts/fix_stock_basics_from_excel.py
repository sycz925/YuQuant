#!/usr/bin/env python3
"""
一次性脚本：从通达信导出的 Excel 文件补全 stock_basics 的细分行业、地区、上市日期
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import UpdateOne
from app.data.db import get_db


def main():
    db = get_db()
    coll = db['stock_basics']

    # 1. 读取 Excel 文件（GBK Tab 分隔）
    excel_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '全部Ａ股20260718.xls')
    print(f"读取文件: {excel_path}")

    rows = []
    with open(excel_path, 'r', encoding='gbk') as f:
        header = None
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if header is None:
                header = parts
                print(f"列名: {header}")
                continue
            if len(parts) < len(header):
                continue
            row = dict(zip(header, parts))
            rows.append(row)

    print(f"解析到 {len(rows)} 条记录")

    # 2. 构建更新操作
    bulk_ops = []
    stats = {'skipped': 0}

    for row in rows:
        code_raw = row.get('代码', '').strip()
        # 清洗代码: ="000001" → 000001
        code = code_raw.replace('="', '').replace('"', '').strip()
        if not code or len(code) != 6:
            stats['skipped'] += 1
            continue

        sub_industry = row.get('细分行业', '').strip()
        region = row.get('地区', '').strip()
        list_date_raw = row.get('上市日期', '').strip()

        # 清洗上市日期
        list_date = None
        if list_date_raw and list_date_raw != '--':
            list_date = list_date_raw

        update_fields = {}
        if sub_industry:
            update_fields['sub_industry'] = sub_industry
        if region:
            update_fields['region'] = region
        if list_date:
            update_fields['list_date'] = list_date

        if not update_fields:
            stats['skipped'] += 1
            continue

        bulk_ops.append(
            UpdateOne(
                {'stock_code': code},
                {'$set': update_fields},
                upsert=False
            )
        )

    print(f"待更新: {len(bulk_ops)} 条, 跳过: {stats['skipped']} 条")

    # 3. 执行批量更新
    if bulk_ops:
        result = coll.bulk_write(bulk_ops, ordered=False)
        print(f"更新完成: matched={result.matched_count}, modified={result.modified_count}")

    # 4. 验证
    print("\n=== 验证 ===")
    total_with_sub = coll.count_documents({'sub_industry': {'$exists': True, '$ne': ''}})
    total_with_region = coll.count_documents({'region': {'$exists': True, '$ne': ''}})
    total_with_list = coll.count_documents({'list_date': {'$ne': '20260717'}})
    total = coll.count_documents({})

    print(f"stock_basics 总记录: {total}")
    print(f"有 sub_industry: {total_with_sub}")
    print(f"有 region: {total_with_region}")
    print(f"list_date 不是 20260717: {total_with_list}")

    # 抽样检查
    print("\n=== 抽样检查 ===")
    for code in ['000001', '000002', '600519', '300750']:
        doc = coll.find_one({'stock_code': code}, {'_id': 0, 'stock_code': 1, 'stock_name': 1, 'sub_industry': 1, 'region': 1, 'list_date': 1})
        if doc:
            print(f"  {code} ({doc.get('stock_name')}): 行业={doc.get('sub_industry')}, 地区={doc.get('region')}, 上市日期={doc.get('list_date')}")


if __name__ == '__main__':
    main()
