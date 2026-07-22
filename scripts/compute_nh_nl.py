"""计算NH-NL并落库"""
import pandas as pd
from app.data.db import get_db
import time

db = get_db()
print('加载数据...')
start = time.time()

all_dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}}), reverse=True)
target_dates = all_dates[:260]
target_dates.reverse()

from datetime import datetime as _dt, timedelta
date_obj = _dt.strptime(target_dates[0], '%Y%m%d')
pre_start = (date_obj - timedelta(days=350)).strftime('%Y%m%d')

cursor = db['stock_daily'].find(
    {'trade_date': {'$gte': pre_start, '$lte': target_dates[-1]}, 'close': {'$gt': 0}},
    {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
)
rows = list(cursor)
print(f'加载{len(rows)}条记录, 耗时{time.time()-start:.1f}秒')

df = pd.DataFrame(rows)
pivot = df.pivot_table(index='trade_date', columns='stock_code', values='close')
pivot = pivot.sort_index()
print(f'矩阵: {pivot.shape[0]}天 x {pivot.shape[1]}只')

start2 = time.time()
result = []
all_pivot_dates = list(pivot.index)
days = 250

for target_date in target_dates:
    if target_date not in pivot.index:
        continue
    idx = all_pivot_dates.index(target_date)
    if idx < days:
        continue
    window = pivot.iloc[idx-days+1:idx+1]
    today_prices = pivot.iloc[idx]
    max_prices = window.max()
    min_prices = window.min()
    nh = ((today_prices >= max_prices) & today_prices.notna()).sum()
    nl = ((today_prices <= min_prices) & today_prices.notna()).sum()
    result.append({'date': target_date, 'nh': int(nh), 'nl': int(nl)})

print(f'计算{len(result)}天NH-NL, 耗时{time.time()-start2:.1f}秒')
print(f'总计: {time.time()-start:.1f}秒')

# 落库到独立集合
db = get_db()
db['base_data_daily'].delete_many({})
db['base_data_daily'].insert_many(result)
print(f'已落库到base_data_daily集合: {len(result)}条')

count = db['base_data_daily'].count_documents({})
latest = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0})
print(f'base_data_daily记录数: {count}, 最新: {latest}')
