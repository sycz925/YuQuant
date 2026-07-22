"""快速补全 base_data_daily 近3年 - 小批次"""
import time
from datetime import datetime as _dt, timedelta
from app.data.db import get_db
from pymongo import UpdateOne

db = get_db()
start_3y = (_dt.now() - timedelta(days=365*3)).strftime('%Y%m%d')

# 获取3年交易日
date_pipeline = [
    {'$match': {'close': {'$gt': 0}, 'trade_date': {'$gte': start_3y}}},
    {'$group': {'_id': '$trade_date'}},
    {'$sort': {'_id': 1}}
]
all_trade_dates = [r['_id'] for r in db['stock_daily'].aggregate(date_pipeline)]

# 找出缺MA50的日期
need_fix = []
for d in all_trade_dates:
    doc = db.base_data_daily.find_one({'date': d}, {'_id': 0, 'ma50_pct': 1})
    if not doc or not doc.get('ma50_pct'):
        need_fix.append(d)

print(f'需修复MA50: {len(need_fix)}天')

if not need_fix:
    print('MA50数据已完整')
    exit()

# 小批次处理
batch_size = 30
total_ops = 0
for i in range(0, len(need_fix), batch_size):
    batch = need_fix[i:i+batch_size]

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

    bulk_ops = []
    for r in ma_results:
        if r['total'] > 0:
            bulk_ops.append(UpdateOne(
                {'date': r['_id']},
                {'$set': {
                    'ma50_pct': round(r['above_ma50'] / r['total'] * 100, 1),
                    'ma20_pct': round(r['above_ma20'] / r['total'] * 100, 1),
                }},
                upsert=True
            ))

    if bulk_ops:
        db['base_data_daily'].bulk_write(bulk_ops, ordered=False)
        total_ops += len(bulk_ops)

    print(f'  批次{i//batch_size+1}: {len(batch)}天, 写入{len(bulk_ops)}条')

print(f'\n共写入{total_ops}条')

# 验证
docs = list(db.base_data_daily.find(
    {'date': {'$gte': start_3y}},
    {'_id': 0, 'date': 1, 'cr5_pct': 1, 'cr10_pct': 1, 'ma50_pct': 1, 'ma20_pct': 1}
))
complete = sum(1 for d in docs if d.get('cr5_pct') and d.get('cr10_pct') and d.get('ma50_pct') and d.get('ma20_pct'))
print(f'近3年: {len(docs)}天, 字段齐全: {complete}天')
