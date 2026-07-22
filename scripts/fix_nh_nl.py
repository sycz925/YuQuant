"""高效修复 base_data_daily 中的 nh/nl 数据"""
from app.data.db import get_db
from datetime import datetime as _dt, timedelta
from pymongo import UpdateOne
import time

db = get_db()

# 找出异常日期
docs = list(db.base_data_daily.find({}, {'_id': 0, 'date': 1, 'nh': 1, 'nl': 1}))
issues = [d['date'] for d in docs if d.get('nl', 0) == 0 or d.get('nh', 0) == 0]
print(f'需修复: {len(issues)}天')

if not issues:
    print('无需修复')
    exit()

# 批量加载所有股票历史数据
earliest = issues[0]
hist_start = (_dt.strptime(earliest, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')
pipeline = [
    {'$match': {'trade_date': {'$gte': hist_start}, 'close': {'$gt': 0}}},
    {'$group': {'_id': {'code': '$stock_code', 'date': '$trade_date'}, 'close': {'$first': '$close'}}}
]
stock_closes = {}
for r in db.stock_daily.aggregate(pipeline):
    code = r['_id']['code']
    date = r['_id']['date']
    if code not in stock_closes:
        stock_closes[code] = {}
    stock_closes[code][date] = r['close']
print(f'加载{len(stock_closes)}只股票数据')

# 获取上市日期
list_date_map = {}
for b in db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1, 'list_date': 1}):
    ld = b.get('list_date')
    if ld:
        list_date_map[b['stock_code']] = str(ld)

# 批量计算（每100天写入一次）
start = time.time()
bulk_ops = []
for i, target_date in enumerate(issues):
    try:
        target_dt = _dt.strptime(target_date, '%Y%m%d')
        hist_start_d = (target_dt - timedelta(days=365)).strftime('%Y%m%d')
        prev_date_obj = target_dt - timedelta(days=1)
        end_date = prev_date_obj.strftime('%Y%m%d')
    except:
        continue

    nh, nl = 0, 0
    for code, dates_map in stock_closes.items():
        ld = list_date_map.get(code, '')
        if ld and len(ld) >= 8:
            try:
                days_listed = (target_dt - _dt.strptime(ld, '%Y%m%d')).days
                if days_listed < 365:
                    continue
            except:
                pass
        window_dates = [d for d in dates_map.keys() if hist_start_d <= d <= end_date]
        if len(window_dates) < 50:
            continue
        recent = sorted(window_dates)[-250:]
        max_high = max(dates_map[d] for d in recent)
        min_low = min(dates_map[d] for d in recent)
        close = dates_map.get(target_date, 0)
        if close >= max_high:
            nh += 1
        elif close <= min_low:
            nl += 1

    bulk_ops.append(UpdateOne({'date': target_date}, {'$set': {'nh': nh, 'nl': nl}}))

    if (i + 1) % 100 == 0:
        db.base_data_daily.bulk_write(bulk_ops, ordered=False)
        bulk_ops = []
        print(f'  进度: {i+1}/{len(issues)}, 耗时{time.time()-start:.0f}秒')

if bulk_ops:
    db.base_data_daily.bulk_write(bulk_ops, ordered=False)
print(f'修复完成: {len(issues)}天, 总耗时{time.time()-start:.0f}秒')
