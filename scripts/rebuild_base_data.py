"""重建 base_data_daily 宽表（date 做唯一主键，一行存所有指标）"""
import time
from app.data.db import get_db
from app.server.api.market_review import calc_ma_breadth_history, calculate_nh_nl_series

db = get_db()

# 1. 获取交易日
all_dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}}), reverse=True)

# 2. MA占比（120天）
print('计算MA占比...')
ma_data = calc_ma_breadth_history(period='day').get('data', [])
ma_map = {d['date']: d for d in ma_data}

# 3. CR5%/CR10%（120天）
print('计算CR5%/CR10%...')
target_dates = all_dates[:120]
target_dates.reverse()

cr_map = {}
for d in target_dates:
    # CR5 从 stock_daily（个股）
    pipeline = [
        {'$match': {'trade_date': d, 'amount': {'$gt': 0}}},
        {'$project': {'amount': 1, '_id': 0}},
        {'$sort': {'amount': -1}}
    ]
    amounts = [r['amount'] for r in db.stock_daily.aggregate(pipeline)]
    if len(amounts) < 100:
        continue
    n5 = max(1, int(len(amounts) * 0.05))
    cr_map[d] = {
        'cr5_pct': round(sum(amounts[:n5]) / sum(amounts) * 100, 4),
    }

    # CR10 从 sector_daily（板块）
    cr10_pipeline = [
        {'$match': {'trade_date': d, 'amount': {'$gt': 0}}},
        {'$project': {'amount': 1, '_id': 0}},
        {'$sort': {'amount': -1}}
    ]
    sector_amounts = [r['amount'] for r in db.sector_daily.aggregate(cr10_pipeline)]
    if len(sector_amounts) >= 10:
        n10 = max(1, int(len(sector_amounts) * 0.10))
        cr_map[d]['cr10_pct'] = round(sum(sector_amounts[:n10]) / sum(sector_amounts) * 100, 4)

    print(f'  {d}: CR5={cr_map[d].get("cr5_pct", 0)}% CR10={cr_map[d].get("cr10_pct", 0)}%')

# 4. NH-NL（250天）
print('计算NH-NL...')
nh_nl_data = calculate_nh_nl_series(250)
nh_nl_map = {d['date']: d for d in nh_nl_data}

# 5. 合并写入（date 做主键，upsert）
print('合并写入 base_data_daily...')
bulk_ops = []
for date in all_dates[:120]:
    update_fields = {}
    if date in ma_map:
        update_fields['ma50_pct'] = ma_map[date].get('ma50_pct')
        update_fields['ma20_pct'] = ma_map[date].get('ma20_pct')
    if date in cr_map:
        update_fields['cr5_pct'] = cr_map[date].get('cr5_pct')
        update_fields['cr10_pct'] = cr_map[date].get('cr10_pct')
    if date in nh_nl_map:
        update_fields['nh'] = nh_nl_map[date].get('nh', 0)
        update_fields['nl'] = nh_nl_map[date].get('nl', 0)

    # 涨跌家数
    stock_pipeline = [
        {'$match': {'trade_date': date, 'close': {'$gt': 0}}},
        {'$group': {
            '_id': None,
            'up_count': {'$sum': {'$cond': [{'$gt': ['$chg_pct', 0]}, 1, 0]}},
            'down_count': {'$sum': {'$cond': [{'$lt': ['$chg_pct', 0]}, 1, 0]}},
        }}
    ]
    stock_stats = list(db['stock_daily'].aggregate(stock_pipeline))
    if stock_stats:
        update_fields['up_count'] = stock_stats[0]['up_count']
        update_fields['down_count'] = stock_stats[0]['down_count']

    # 总成交额（上证+深综）
    index_amounts = list(db['index_daily'].find(
        {'trade_date': date, 'stock_code': {'$in': ['000001', '399106']}},
        {'_id': 0, 'amount': 1}
    ))
    if index_amounts:
        update_fields['total_amount'] = round(sum(d.get('amount', 0) for d in index_amounts), 2)

    if update_fields:
        from pymongo import UpdateOne
        bulk_ops.append(UpdateOne({'date': date}, {'$set': update_fields}, upsert=True))

if bulk_ops:
    db['base_data_daily'].delete_many({})
    db['base_data_daily'].create_index('date', unique=True)
    db['base_data_daily'].bulk_write(bulk_ops, ordered=False)

# 验证
count = db['base_data_daily'].count_documents({})
sample = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0})
print(f'\nbase_data_daily: {count}条')
print(f'最新样本: {sample}')
