from app.data.db import get_db
from datetime import datetime as _dt, timedelta
db = get_db()

start_3y = (_dt.now() - timedelta(days=365*3)).strftime('%Y%m%d')
docs = list(db.base_data_daily.find({'date': {'$gte': start_3y}}, {'_id': 0, 'date': 1, 'ma50_pct': 1}))
missing = [d['date'] for d in docs if not d.get('ma50_pct')]
print(f'缺失MA50: {len(missing)}天')

if missing:
    test_date = missing[0]
    count_ma50 = db.stock_daily.count_documents({'trade_date': test_date, 'ma50': {'$gt': 0}})
    count_total = db.stock_daily.count_documents({'trade_date': test_date, 'close': {'$gt': 0}})
    print(f'{test_date}: 有ma50={count_ma50}, 总={count_total}')
