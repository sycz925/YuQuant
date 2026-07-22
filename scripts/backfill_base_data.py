"""高效补全 base_data_daily（分批处理）"""
import time
from datetime import datetime as _dt, timedelta
from app.data.db import get_db
from pymongo import UpdateOne

db = get_db()

# 计算需要补全的日期范围
start_date = (_dt.now() - timedelta(days=365*10)).strftime('%Y%m%d')
existing = set(d['date'] for d in db['base_data_daily'].find({}, {'_id': 0, 'date': 1}))

# 从stock_daily取日期（用聚合避免distinct超时）
date_pipeline = [
    {'$match': {'close': {'$gt': 0}, 'trade_date': {'$gte': start_date}}},
    {'$group': {'_id': '$trade_date'}},
    {'$sort': {'_id': 1}}
]
all_target_dates = [r['_id'] for r in db['stock_daily'].aggregate(date_pipeline)]
need_dates = [d for d in all_target_dates if d not in existing]
print(f'总交易日: {len(all_target_dates)}, 已有: {len(existing)}, 待补: {len(need_dates)}')

if not need_dates:
    print('数据已完整')
    exit()

# 分批处理（每批100天）
batch_size = 100
for i in range(0, len(need_dates), batch_size):
    batch = need_dates[i:i+batch_size]
    batch_start = time.time()
    print(f'\n--- 批次 {i//batch_size + 1}: {batch[0]} ~ {batch[-1]} ({len(batch)}天) ---')

    # 1. CR5/CR10 批量计算
    pipeline = [
        {'$match': {'trade_date': {'$in': batch}, 'amount': {'$gt': 0}}},
        {'$group': {'_id': '$trade_date', 'amounts': {'$push': '$amount'}}}
    ]
    cr_results = list(db['stock_daily'].aggregate(pipeline))
    cr_map = {}
    for r in cr_results:
        amounts = sorted(r['amounts'], reverse=True)
        if len(amounts) < 100:
            continue
        n5 = max(1, int(len(amounts) * 0.05))
        n10 = max(1, int(len(amounts) * 0.10))
        cr_map[r['_id']] = {
            'cr5_pct': round(sum(amounts[:n5]) / sum(amounts) * 100, 4),
            'cr10_pct': round(sum(amounts[:n10]) / sum(amounts) * 100, 4),
        }

    # 2. MA50/MA20 批量计算
    ma_pipeline = [
        {'$match': {'trade_date': {'$in': batch}, 'close': {'$gt': 0}, 'ma50': {'$gt': 0}}},
        {'$group': {
            '_id': '$trade_date',
            'total': {'$sum': 1},
            'above_ma50': {'$sum': {'$cond': [{'$gt': ['$close', '$ma50']}, 1, 0]}},
            'above_ma20': {'$sum': {'$cond': [{'$gt': ['$close', '$ma20']}, 1, 0]}}
        }}
    ]
    ma_results = list(db['stock_daily'].aggregate(ma_pipeline))
    ma_map = {}
    for r in ma_results:
        if r['total'] > 0:
            ma_map[r['_id']] = {
                'ma50_pct': round(r['above_ma50'] / r['total'] * 100, 1),
                'ma20_pct': round(r['above_ma20'] / r['total'] * 100, 1),
            }

    # 3. 合并写入
    bulk_ops = []
    for date in batch:
        fields = {}
        if date in ma_map:
            fields['ma50_pct'] = ma_map[date]['ma50_pct']
            fields['ma20_pct'] = ma_map[date]['ma20_pct']
        if date in cr_map:
            fields['cr5_pct'] = cr_map[date]['cr5_pct']
            fields['cr10_pct'] = cr_map[date]['cr10_pct']
        if fields:
            bulk_ops.append(UpdateOne({'date': date}, {'$set': fields}, upsert=True))

    if bulk_ops:
        db['base_data_daily'].bulk_write(bulk_ops, ordered=False)

    elapsed = time.time() - batch_start
    print(f'  CR: {len(cr_map)}天, MA: {len(ma_map)}天, 写入: {len(bulk_ops)}条, 耗时: {elapsed:.1f}秒')

total = db['base_data_daily'].count_documents({})
print(f'\n=== 完成! base_data_daily: {total}天 ===')
first = db['base_data_daily'].find_one(sort=[('date', 1)], projection={'_id': 0, 'date': 1})
last = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0, 'date': 1})
print(f'范围: {first["date"]} ~ {last["date"]}')
