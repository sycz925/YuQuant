"""
数据迁移脚本：为 daily_data 集合中所有文档添加 data_type 字段
- 指数数据（sh/sz 前缀代码）：data_type = 'index'
- 个股数据（纯数字6位代码）：data_type = 'stock'

同时修复 index_basics 集合格式，统一为 code/name/tdx_code/market 字段。
"""
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

load_dotenv()
mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
db_name = os.getenv('MONGODB_DB_NAME', 'yuquant')
client = MongoClient(mongodb_uri)
db = client[db_name]


def step1_migrate_daily_data():
    """批量为 daily_data 添加 data_type 字段（分批次执行）"""
    print(f"[{datetime.now()}] Step 1: 迁移 daily_data data_type 字段...")

    total = db['daily_data'].count_documents({})
    to_update = db['daily_data'].count_documents({'data_type': {'$exists': False}})
    print(f"  总记录数: {total}, 需要更新: {to_update}")

    if to_update == 0:
        print("  所有记录已更新，跳过")
        return

    # 策略：先用代码前缀判断
    # sh/sz 开头 → index，其余 → stock
    all_codes = db['daily_data'].distinct('stock_code')
    index_codes = [c for c in all_codes if isinstance(c, str) and (c.startswith('sh') or c.startswith('sz'))]
    stock_codes = [c for c in all_codes if c not in index_codes]

    print(f"  指数代码数: {len(index_codes)}")
    print(f"  个股代码数: {len(stock_codes)}")

    update_time = datetime.utcnow()
    batch_size = 50000  # 每批5万条

    # 更新指数数据
    if index_codes:
        idx_cnt = db['daily_data'].count_documents({'stock_code': {'$in': index_codes}})
        print(f"  指数记录数: {idx_cnt}, 开始批量更新 data_type='index' ...")

        updated = 0
        for i in range(0, len(index_codes), 50):
            batch_codes = index_codes[i:i+50]
            result = db['daily_data'].update_many(
                {'stock_code': {'$in': batch_codes}, 'data_type': {'$exists': False}},
                {'$set': {'data_type': 'index', 'update_time': update_time}}
            )
            updated += result.modified_count
            print(f"    进度: {min(i+50, len(index_codes))}/{len(index_codes)} 个指数代码, 已更新 {updated} 条")

        print(f"  指数更新完成: {updated} 条")

    # 更新个股数据
    if stock_codes:
        stk_cnt = db['daily_data'].count_documents({'stock_code': {'$in': stock_codes}})
        print(f"  个股记录数: {stk_cnt}, 开始批量更新 data_type='stock' ...")

        updated = 0
        # 分批处理股票代码
        for i in range(0, len(stock_codes), 200):
            batch_codes = stock_codes[i:i+200]
            result = db['daily_data'].update_many(
                {'stock_code': {'$in': batch_codes}, 'data_type': {'$exists': False}},
                {'$set': {'data_type': 'stock', 'update_time': update_time}}
            )
            updated += result.modified_count
            if (i // 200 + 1) % 10 == 0:
                print(f"    进度: {min(i+200, len(stock_codes))}/{len(stock_codes)} 个个股代码, 已更新 {updated} 条")

        print(f"  个股更新完成: {updated} 条")

    # 最终检查
    remaining = db['daily_data'].count_documents({'data_type': {'$exists': False}})
    print(f"  Step 1 完成，剩余未标记: {remaining}")


def step2_fix_index_basics():
    """修复 index_basics 集合：统一为 code/name/tdx_code/market 字段"""
    print(f"\n[{datetime.now()}] Step 2: 修复 index_basics 集合格式...")

    # 旧格式: index_code, index_name, market
    # 新格式: code, name, tdx_code, market
    old_docs = list(db['index_basics'].find({}))
    print(f"  现有记录: {len(old_docs)} 条")

    # 定义完整的指数配置（从 daily_data 中实际有的 sh/sz 前缀代码推断）
    # 先从 daily_data 中获取所有 sh/sz 前缀代码
    all_codes = db['daily_data'].distinct('stock_code')
    index_prefix_codes = [c for c in all_codes if isinstance(c, str) and (c.startswith('sh') or c.startswith('sz'))]
    print(f"  daily_data 中实际的指数代码: {index_prefix_codes}")

    # 标准指数配置映射
    index_config_map = {
        'sh000001': {'code': 'sh000001', 'name': '上证指数', 'tdx_code': '000001', 'market': 1},
        'sh000688': {'code': 'sh000688', 'name': '科创50', 'tdx_code': '000688', 'market': 1},
        'sh000905': {'code': 'sh000905', 'name': '中证500', 'tdx_code': '000905', 'market': 1},
        'sz399006': {'code': 'sz399006', 'name': '创业板指', 'tdx_code': '399006', 'market': 0},
        'sz399106': {'code': 'sz399106', 'name': '深圳综指', 'tdx_code': '399106', 'market': 0},
    }

    # 清空并重新插入
    db['index_basics'].delete_many({})
    inserted = 0
    for code in index_prefix_codes:
        if code in index_config_map:
            cfg = index_config_map[code]
            cfg['update_time'] = datetime.utcnow()
            db['index_basics'].insert_one(cfg)
            inserted += 1
            print(f"  插入: {cfg['code']} - {cfg['name']}")

    print(f"  Step 2 完成，共 {inserted} 条指数配置")


def step3_verify():
    """验证迁移结果"""
    print(f"\n[{datetime.now()}] Step 3: 验证迁移结果...")

    total = db['daily_data'].count_documents({})
    stock_cnt = db['daily_data'].count_documents({'data_type': 'stock'})
    index_cnt = db['daily_data'].count_documents({'data_type': 'index'})
    no_type = db['daily_data'].count_documents({'data_type': {'$exists': False}})

    print(f"  总数: {total}")
    print(f"  stock: {stock_cnt}")
    print(f"  index: {index_cnt}")
    print(f"  未标记: {no_type}")
    print(f"  校验: stock + index + 未标记 = {stock_cnt + index_cnt + no_type} {'✓' if stock_cnt + index_cnt + no_type == total else '✗'}")

    # 检查 index_basics
    ib_count = db['index_basics'].count_documents({})
    print(f"\n  index_basics: {ib_count} 条")
    for doc in db['index_basics'].find({}, {'_id': 0}):
        print(f"    {doc}")

    print(f"\n[{datetime.now()}] 迁移完成!")


if __name__ == '__main__':
    step1_migrate_daily_data()
    step2_fix_index_basics()
    step3_verify()
