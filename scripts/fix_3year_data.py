"""补全 base_data_daily 近3年所有字段"""
import time
from datetime import datetime as _dt, timedelta
from app.data.db import get_db
from pymongo import UpdateOne

db = get_db()

# 近3年范围
start_3y = (_dt.now() - timedelta(days=365*3)).strftime('%Y%m%d')

# 获取3年所有交易日
date_pipeline = [
    {'$match': {'close': {'$gt': 0}, 'trade_date': {'$gte': start_3y}}},
    {'$group': {'_id': '$trade_date'}},
    {'$sort': {'_id': 1}}
]
all_trade_dates = [r['_id'] for r in db['stock_daily'].aggregate(date_pipeline)]
print(f'近3年交易日: {len(all_trade_dates)}天')

# 检查哪些日期数据不全
need_fix = []
for d in all_trade_dates:
    doc = db.base_data_daily.find_one({'date': d}, {'_id': 0, 'cr5_pct': 1, 'cr10_pct': 1, 'ma50_pct': 1, 'ma20_pct': 1})
    if not doc or not all([doc.get('cr5_pct'), doc.get('cr10_pct'), doc.get('ma50_pct'), doc.get('ma20_pct')]):
        need_fix.append(d)

print(f'需修复: {len(need_fix)}天')

if not need_fix:
    print('数据已完整')
    exit()

# 获取上市日期映射
list_date_map = {}
for b in db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1, 'list_date': 1}):
    ld = b.get('list_date')
    if ld:
        list_date_map[b['stock_code']] = str(ld)

    # 分批处理
    batch_size = 50
    for i in range(0, len(need_fix), batch_size):
        batch = need_fix[i:i+batch_size]
        batch_start = time.time()

        # CR5（个股，全量）
        cr5_pipeline = [
            {'$match': {'trade_date': {'$in': batch}, 'amount': {'$gt': 0}}},
            {'$group': {'_id': '$trade_date', 'amounts': {'$push': '$amount'}}}
        ]
        cr5_results = list(db['stock_daily'].aggregate(cr5_pipeline))
        cr_map = {}
        for r in cr5_results:
            amounts = sorted(r['amounts'], reverse=True)
            if len(amounts) < 50:
                continue
            n5 = max(1, int(len(amounts) * 0.05))
            cr_map[r['_id']] = {'cr5_pct': round(sum(amounts[:n5]) / sum(amounts) * 100, 4)}

        # CR10（板块）
        cr10_pipeline = [
            {'$match': {'trade_date': {'$in': batch}, 'amount': {'$gt': 0}}},
            {'$group': {'_id': '$trade_date', 'amounts': {'$push': '$amount'}}}
        ]
        cr10_results = list(db['sector_daily'].aggregate(cr10_pipeline))
        for r in cr10_results:
            amounts = sorted(r['amounts'], reverse=True)
            if len(amounts) < 10:
                continue
            n10 = max(1, int(len(amounts) * 0.10))
            if r['_id'] in cr_map:
                cr_map[r['_id']]['cr10_pct'] = round(sum(amounts[:n10]) / sum(amounts) * 100, 4)
            else:
                cr_map[r['_id']] = {'cr5_pct': 0, 'cr10_pct': round(sum(amounts[:n10]) / sum(amounts) * 100, 4)}

        # MA50/MA20（全量，有ma50值的股票）
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

    # 写入
    bulk_ops = []
    for date in batch:
        fields = {}
        if date in cr_map:
            fields['cr5_pct'] = cr_map[date].get('cr5_pct', 0)
            fields['cr10_pct'] = cr_map[date].get('cr10_pct', 0)
        if date in ma_map:
            fields['ma50_pct'] = ma_map[date]['ma50_pct']
            fields['ma20_pct'] = ma_map[date]['ma20_pct']
        if fields:
            bulk_ops.append(UpdateOne({'date': date}, {'$set': fields}, upsert=True))
    if bulk_ops:
        db['base_data_daily'].bulk_write(bulk_ops, ordered=False)

    elapsed = time.time() - batch_start
    print(f'  批次{i//batch_size+1}: {len(batch)}天, CR:{len(cr_map)}, MA:{len(ma_map)}, 耗时{elapsed:.1f}秒')

# 验证
print('\n=== 验证近3年数据 ===')
for field in ['cr5_pct', 'cr10_pct', 'ma50_pct', 'ma20_pct']:
    count = db.base_data_daily.count_documents({field: {'\$exists': True, '\$ne': 0}, 'date': {'\$gte': start_3y}})
    print(f'  {field}: {count}天')

total = db.base_data_daily.count_documents({'date': {'\$gte': start_3y}})
print(f'  总记录: {total}天')
