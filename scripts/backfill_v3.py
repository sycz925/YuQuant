#!/usr/bin/env python3
"""逐股票计算+批量写入，不加载全量到pandas"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings('ignore')

import numpy as np
from pymongo import UpdateOne
from app.data.db import get_collection

MA_P = [10, 20, 50, 120]
VOL_MA_P = [5, 10, 20, 50]
CHG_P = [5, 10, 20, 50, 120, 250]
BATCH = 50000


def process_stock():
    coll = get_collection('stock')
    codes = sorted(coll.distinct('stock_code', {'close': {'$gt': 0}}))
    print(f"[stock] {len(codes)} 只股票")
    t0 = time.time()
    total_ops = 0
    batch_ops = []

    for idx, code in enumerate(codes):
        rows = list(coll.find(
            {'stock_code': code, 'close': {'$gt': 0}},
            {'_id': 0, 'trade_date': 1, 'close': 1, 'vol': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
        ).sort('trade_date', 1))

        n = len(rows)
        if n < 2:
            continue

        close = np.array([r['close'] for r in rows], dtype=np.float64)
        vol = np.array([r.get('vol') or 0 for r in rows], dtype=np.float64)
        dates = [r['trade_date'] for r in rows]

        # 预计算所有位置的前N日收盘价索引
        prev_idx = np.arange(n) - 1

        for i in range(1, n):
            doc = {}
            # chg_pct
            if close[i-1] > 0:
                doc['chg_pct'] = round(float((close[i] - close[i-1]) / close[i-1] * 100), 2)

            # MA (running mean)
            for p in MA_P:
                if i >= p - 1:
                    doc[f'ma{p}'] = round(float(close[i-p+1:i+1].mean()), 2)

            # VOL_MA
            for p in VOL_MA_P:
                if i >= p - 1:
                    v = vol[i-p+1:i+1]
                    if v.sum() > 0:
                        doc[f'vol_ma{p}'] = round(float(v.mean()), 2)

            # 区间涨幅
            for p in CHG_P:
                if i >= p and close[i-p] > 0:
                    doc[f'chg_{p}d'] = round(float((close[i] - close[i-p]) / close[i-p] * 100), 2)

            # RPS衍生
            r = rows[i]
            r20 = r.get('rps_20')
            r50 = r.get('rps_50')
            if r20 and r20 > 0 and r50 and r50 > 0:
                r120 = r.get('rps_120') or 0
                r250 = r.get('rps_250') or 0
                rs = r20 + r50 + max(r120, r250)
                doc['rps_sum'] = int(rs)
                chg = doc.get('chg_pct', 0) or 0
                doc['is_active'] = rs > 270 and chg > 5

            if doc:
                batch_ops.append(UpdateOne(
                    {'stock_code': code, 'trade_date': dates[i]}, {'$set': doc}
                ))

        if len(batch_ops) >= BATCH:
            coll.bulk_write(batch_ops, ordered=False)
            total_ops += len(batch_ops)
            batch_ops = []
            elapsed = time.time() - t0
            print(f"  [{idx+1}/{len(codes)}] {total_ops}条 {elapsed:.0f}s")

    if batch_ops:
        coll.bulk_write(batch_ops, ordered=False)
        total_ops += len(batch_ops)

    print(f"[stock] 完成 {total_ops} 条, {time.time()-t0:.0f}秒")


def process_percentile(coll_name='stock'):
    coll = get_collection(coll_name)
    dates = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}, 'amount': {'$gt': 0}}))
    print(f"\n[{coll_name} percentile] {len(dates)} 天")
    t0 = time.time()
    total = 0
    batch_ops = []

    for d in dates:
        rows = list(coll.find(
            {'trade_date': d, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1}
        ))
        if len(rows) < 5:
            continue
        n = len(rows)
        closes = np.array([r['close'] for r in rows])
        amounts = np.array([r['amount'] for r in rows])

        # 快速百分位计算
        sort_idx_c = np.argsort(closes)
        rank_c = np.empty(n, dtype=int)
        rank_c[sort_idx_c] = np.arange(n)
        sort_idx_a = np.argsort(amounts)
        rank_a = np.empty(n, dtype=int)
        rank_a[sort_idx_a] = np.arange(n)

        for j in range(n):
            batch_ops.append(UpdateOne(
                {'stock_code': rows[j]['stock_code'], 'trade_date': d},
                {'$set': {'close_pct': int(round(rank_c[j] / n * 100)),
                          'amount_pct': int(round(rank_a[j] / n * 100))}}
            ))

        if len(batch_ops) >= BATCH:
            coll.bulk_write(batch_ops, ordered=False)
            total += len(batch_ops)
            batch_ops = []

    if batch_ops:
        coll.bulk_write(batch_ops, ordered=False)
        total += len(batch_ops)
    print(f"[{coll_name} percentile] 完成 {total} 条, {time.time()-t0:.0f}秒")


def process_sector():
    coll = get_collection('sector')
    codes = sorted(coll.distinct('stock_code', {'close': {'$gt': 0}}))
    print(f"\n[sector] {len(codes)} 个板块")
    t0 = time.time()
    total_ops = 0
    batch_ops = []

    for idx, code in enumerate(codes):
        rows = list(coll.find(
            {'stock_code': code, 'close': {'$gt': 0}},
            {'_id': 0, 'trade_date': 1, 'close': 1, 'volume': 1}
        ).sort('trade_date', 1))

        n = len(rows)
        if n < 2:
            continue

        close = np.array([r['close'] for r in rows], dtype=np.float64)
        vol = np.array([r.get('volume') or 0 for r in rows], dtype=np.float64)
        dates = [r['trade_date'] for r in rows]

        for i in range(1, n):
            doc = {}
            if close[i-1] > 0:
                doc['chg_pct'] = round(float((close[i] - close[i-1]) / close[i-1] * 100), 2)
            for p in [10, 20, 50]:
                if i >= p - 1:
                    doc[f'ma{p}'] = round(float(close[i-p+1:i+1].mean()), 2)
            for p in [5, 10, 20]:
                if i >= p - 1:
                    v = vol[i-p+1:i+1]
                    if v.sum() > 0:
                        doc[f'vol_ma{p}'] = round(float(v.mean()), 2)
            for p in CHG_P:
                if i >= p and close[i-p] > 0:
                    doc[f'chg_{p}d'] = round(float((close[i] - close[i-p]) / close[i-p] * 100), 2)
            if doc:
                batch_ops.append(UpdateOne(
                    {'stock_code': code, 'trade_date': dates[i]}, {'$set': doc}
                ))

        if len(batch_ops) >= BATCH:
            coll.bulk_write(batch_ops, ordered=False)
            total_ops += len(batch_ops)
            batch_ops = []
            if (idx + 1) % 50 == 0:
                print(f"  [{idx+1}/{len(codes)}] {total_ops}条")

    if batch_ops:
        coll.bulk_write(batch_ops, ordered=False)
        total_ops += len(batch_ops)
    print(f"[sector] 完成 {total_ops} 条, {time.time()-t0:.0f}秒")


if __name__ == '__main__':
    t_total = time.time()
    print("=" * 50)
    print("回刷冗余字段")
    print("=" * 50)

    process_stock()
    process_percentile('stock')
    process_sector()
    process_percentile('sector')

    print(f"\n总耗时: {time.time()-t_total:.0f}秒 ({(time.time()-t_total)/60:.1f}分钟)")
