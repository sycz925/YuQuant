"""修正 base_data_daily 中的 CR10%（从 sector_daily 重新计算）"""
import time
from app.data.db import get_db
from pymongo import UpdateOne

db = get_db()
print('从 sector_daily 重新计算 CR10%...')

# 获取所有有 CR10 的日期
dates_with_cr10 = [d['date'] for d in db['base_data_daily'].find(
    {'cr10_pct': {'$exists': True}}, {'_id': 0, 'date': 1}
).sort('date', 1)]

print(f'需修正: {len(dates_with_cr10)}天')

# 批量查询 sector_daily 成交额
pipeline = [
    {'$match': {'trade_date': {'$in': dates_with_cr10}, 'amount': {'$gt': 0}}},
    {'$group': {'_id': '$trade_date', 'amounts': {'$push': '$amount'}}}
]
results = list(db['sector_daily'].aggregate(pipeline))
cr10_map = {}
for r in results:
    amounts = sorted(r['amounts'], reverse=True)
    if len(amounts) < 10:
        continue
    n10 = max(1, int(len(amounts) * 0.10))
    cr10_map[r['_id']] = round(sum(amounts[:n10]) / sum(amounts) * 100, 4)

print(f'sector_daily CR10: {len(cr10_map)}天')

# 更新
bulk_ops = []
for date, cr10 in cr10_map.items():
    bulk_ops.append(UpdateOne({'date': date}, {'$set': {'cr10_pct': cr10}}))

if bulk_ops:
    db['base_data_daily'].bulk_write(bulk_ops, ordered=False)
    print(f'已更新 {len(bulk_ops)} 条 CR10')

# 验证
sample = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0, 'date': 1, 'cr5_pct': 1, 'cr10_pct': 1})
print(f'最新: {sample}')
