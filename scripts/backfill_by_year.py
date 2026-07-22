"""按年补全 base_data_daily，只考虑当时已上市的股票"""
import time
from datetime import datetime as _dt, timedelta
from app.data.db import get_db
from pymongo import UpdateOne

db = get_db()

# 找出缺失数据的日期
all_dates_cursor = db['base_data_daily'].find({}, {'_id': 0, 'date': 1})
all_dates_map = {d['date']: 1 for d in all_dates_cursor}

# 获取stock_daily中所有交易日
date_pipeline = [
    {'$match': {'close': {'$gt': 0}}},
    {'$group': {'_id': '$trade_date'}},
    {'$sort': {'_id': 1}}
]
all_trade_dates = [r['_id'] for r in db['stock_daily'].aggregate(date_pipeline)]

# 获取stock_basics中的上市日期
list_date_map = {}
for b in db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1, 'list_date': 1}):
    ld = b.get('list_date')
    if ld:
        list_date_map[b['stock_code']] = str(ld)

print(f'总交易日: {len(all_trade_dates)}, 已有base_data: {len(all_dates_map)}')

# 找出缺失的日期
need_dates = [d for d in all_trade_dates if d not in all_dates_map]
print(f'待补全: {len(need_dates)}天')

if not need_dates:
    print('数据已完整')
    exit()

# 按年分组处理
from collections import defaultdict
by_year = defaultdict(list)
for d in need_dates:
    by_year[d[:4]].append(d)

for year in sorted(by_year.keys(), reverse=True):
    dates = by_year[year]
    print(f'\n=== {year}年: {len(dates)}天 ===')

    # 获取该年之前上市的股票列表
    year_start = f'{year}0101'
    listed_codes = set()
    for code, ld in list_date_map.items():
        if ld < year_start:
            listed_codes.add(code)

    print(f'  已上市股票: {len(listed_codes)}只')

    # 分批处理
    batch_size = 50
    for i in range(0, len(dates), batch_size):
        batch = dates[i:i+batch_size]

        # CR5（个股，从stock_daily）
        cr5_pipeline = [
            {'$match': {'trade_date': {'$in': batch}, 'stock_code': {'$in': list(listed_codes)}, 'amount': {'$gt': 0}}},
            {'$group': {'_id': '$trade_date', 'amounts': {'$push': '$amount'}}}
        ]
        cr5_results = list(db['stock_daily'].aggregate(cr5_pipeline))
        cr_map = {}
        for r in cr5_results:
            amounts = sorted(r['amounts'], reverse=True)
            if len(amounts) < 50:
                continue
            n5 = max(1, int(len(amounts) * 0.05))
            cr_map[r['_id']] = {
                'cr5_pct': round(sum(amounts[:n5]) / sum(amounts) * 100, 4),
            }

        # CR10（板块，从sector_daily）
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
                cr_map[r['_id']] = {
                    'cr5_pct': 0,
                    'cr10_pct': round(sum(amounts[:n10]) / sum(amounts) * 100, 4),
                }

        # MA50/MA20（只用当时已上市的股票）
        ma_pipeline = [
            {'$match': {
                'trade_date': {'$in': batch},
                'stock_code': {'$in': list(listed_codes)},
                'close': {'$gt': 0}, 'ma50': {'$gt': 0}
            }},
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

# 最终验证
total = db['base_data_daily'].count_documents({})
cr_count = db['base_data_daily'].count_documents({'cr5_pct': {'$exists': True}})
ma_count = db['base_data_daily'].count_documents({'ma50_pct': {'$exists': True}})
first = db['base_data_daily'].find_one(sort=[('date', 1)], projection={'_id': 0, 'date': 1})
last = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0, 'date': 1})
print(f'\n=== 完成! ===')
print(f'base_data_daily: {total}天')
print(f'CR5/CR10: {cr_count}天')
print(f'MA50/MA20: {ma_count}天')
print(f'范围: {first["date"]} ~ {last["date"]}')
