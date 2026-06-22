#!/usr/bin/env python3
"""最简单高效方案: 逐股票numpy计算 + 批量写入"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from datetime import datetime
from pymongo import UpdateOne
from app.data.db import get_db, get_collection

MA_PERIODS = [10, 20, 50, 120]
VOL_MA_PERIODS = [5, 10, 20, 50]
CHG_PERIODS = [5, 10, 20, 50, 120, 250]


def backfill_stock(coll):
    print("[stock] 获取股票列表...")
    codes = sorted(coll.distinct('stock_code', {'close': {'$gt': 0}}))
    print(f"[stock] 共 {len(codes)} 只，开始逐只计算...")
    update_time = datetime.utcnow()
    total_ops = 0
    t0 = time.time()

    for idx, code in enumerate(codes):
        rows = list(coll.find(
            {'stock_code': code, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'vol': 1, 'amount': 1,
             'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
        ).sort('trade_date', 1))

        if len(rows) < 2:
            continue

        n = len(rows)
        close = np.array([r['close'] for r in rows], dtype=np.float64)
        vol = np.array([r.get('vol', 0) or 0 for r in rows], dtype=np.float64)
        dates = [r['trade_date'] for r in rows]

        ops = []
        for i in range(1, n):
            set_doc = {'update_time': update_time}

            # chg_pct
            if close[i-1] > 0:
                set_doc['chg_pct'] = round(float((close[i] - close[i-1]) / close[i-1] * 100), 2)

            # MA
            for p in MA_PERIODS:
                if i >= p - 1:
                    set_doc[f'ma{p}'] = round(float(np.mean(close[i-p+1:i+1])), 2)

            # VOL_MA
            for p in VOL_MA_PERIODS:
                if i >= p - 1 and vol[i] > 0:
                    set_doc[f'vol_ma{p}'] = round(float(np.mean(vol[i-p+1:i+1])), 2)

            # 区间涨幅
            for p in CHG_PERIODS:
                if i >= p and close[i-p] > 0:
                    set_doc[f'chg_{p}d'] = round(float((close[i] - close[i-p]) / close[i-p] * 100), 2)

            # RPS衍生
            r = rows[i]
            rps20 = r.get('rps_20')
            rps50 = r.get('rps_50')
            rps120 = r.get('rps_120') or 0
            rps250 = r.get('rps_250') or 0
            if rps20 and rps20 > 0 and rps50 and rps50 > 0:
                rps_sum = rps20 + rps50 + max(rps120, rps250)
                set_doc['rps_sum'] = int(rps_sum)
                chg_pct = set_doc.get('chg_pct', 0) or 0
                set_doc['is_active'] = bool(rps_sum > 270 and chg_pct > 5)

            ops.append(UpdateOne(
                {'stock_code': code, 'trade_date': dates[i]},
                {'$set': set_doc}
            ))

        if ops:
            coll.bulk_write(ops, ordered=False)
            total_ops += len(ops)

        if (idx + 1) % 200 == 0:
            elapsed = time.time() - t0
            speed = total_ops / elapsed if elapsed > 0 else 0
            print(f"  [{idx+1}/{len(codes)}] {total_ops}条更新, {speed:.0f}条/秒")

    elapsed = time.time() - t0
    print(f"[stock] 完成: {total_ops} 条更新, 耗时 {elapsed:.1f}秒")


def backfill_stock_percentile(coll):
    print("[stock percentile] 开始...")
    update_time = datetime.utcnow()
    dates = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}, 'amount': {'$gt': 0}}))
    print(f"  共 {len(dates)} 天")
    total = 0

    for i, d in enumerate(dates):
        rows = list(coll.find(
            {'trade_date': d, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1}
        ))
        if len(rows) < 10:
            continue
        closes = np.array([r['close'] for r in rows])
        amounts = np.array([r['amount'] for r in rows])
        close_ranks = np.searchsorted(np.sort(closes), closes) / len(closes) * 100
        amount_ranks = np.searchsorted(np.sort(amounts), amounts) / len(amounts) * 100

        ops = [UpdateOne(
            {'stock_code': rows[j]['stock_code'], 'trade_date': d},
            {'$set': {'close_pct': int(round(close_ranks[j])),
                      'amount_pct': int(round(amount_ranks[j])),
                      'update_time': update_time}}
        ) for j in range(len(rows))]
        coll.bulk_write(ops, ordered=False)
        total += len(ops)

        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(dates)}] {total} 条")

    print(f"[stock percentile] 完成: {total} 条")


def backfill_sector(coll):
    print("[sector] 获取板块列表...")
    codes = sorted(coll.distinct('stock_code', {'close': {'$gt': 0}}))
    print(f"[sector] 共 {len(codes)} 个，开始计算...")
    update_time = datetime.utcnow()
    total_ops = 0
    t0 = time.time()

    for idx, code in enumerate(codes):
        rows = list(coll.find(
            {'stock_code': code, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'volume': 1}
        ).sort('trade_date', 1))

        if len(rows) < 2:
            continue

        n = len(rows)
        close = np.array([r['close'] for r in rows], dtype=np.float64)
        vol = np.array([r.get('volume', 0) or 0 for r in rows], dtype=np.float64)
        dates = [r['trade_date'] for r in rows]

        ops = []
        for i in range(1, n):
            set_doc = {'update_time': update_time}
            if close[i-1] > 0:
                set_doc['chg_pct'] = round(float((close[i] - close[i-1]) / close[i-1] * 100), 2)
            for p in [10, 20, 50]:
                if i >= p - 1:
                    set_doc[f'ma{p}'] = round(float(np.mean(close[i-p+1:i+1])), 2)
            for p in [5, 10, 20]:
                if i >= p - 1:
                    set_doc[f'vol_ma{p}'] = round(float(np.mean(vol[i-p+1:i+1])), 2)
            for p in CHG_PERIODS:
                if i >= p and close[i-p] > 0:
                    set_doc[f'chg_{p}d'] = round(float((close[i] - close[i-p]) / close[i-p] * 100), 2)

            ops.append(UpdateOne(
                {'stock_code': code, 'trade_date': dates[i]}, {'$set': set_doc}
            ))

        if ops:
            coll.bulk_write(ops, ordered=False)
            total_ops += len(ops)

        if (idx + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  [{idx+1}/{len(codes)}] {total_ops}条, {total_ops/max(elapsed,1):.0f}条/秒")

    elapsed = time.time() - t0
    print(f"[sector] 完成: {total_ops} 条, 耗时 {elapsed:.1f}秒")


def backfill_sector_percentile(coll):
    print("[sector percentile] 开始...")
    update_time = datetime.utcnow()
    dates = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}, 'amount': {'$gt': 0}}))
    total = 0

    for d in dates:
        rows = list(coll.find(
            {'trade_date': d, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1}
        ))
        if len(rows) < 5:
            continue
        closes = np.array([r['close'] for r in rows])
        amounts = np.array([r['amount'] for r in rows])
        close_ranks = np.searchsorted(np.sort(closes), closes) / len(closes) * 100
        amount_ranks = np.searchsorted(np.sort(amounts), amounts) / len(amounts) * 100

        ops = [UpdateOne(
            {'stock_code': rows[j]['stock_code'], 'trade_date': d},
            {'$set': {'close_pct': int(round(close_ranks[j])),
                      'amount_pct': int(round(amount_ranks[j])),
                      'update_time': update_time}}
        ) for j in range(len(rows))]
        coll.bulk_write(ops, ordered=False)
        total += len(ops)

    print(f"[sector percentile] 完成: {total} 条")


if __name__ == '__main__':
    print("=" * 60)
    print("高效回刷冗余字段 (逐股票numpy计算)")
    print("=" * 60)
    t0 = time.time()

    print("\n【1/4】个股冗余字段")
    backfill_stock(get_collection('stock'))

    print("\n【2/4】个股百分位")
    backfill_stock_percentile(get_collection('stock'))

    print("\n【3/4】板块冗余字段")
    backfill_sector(get_collection('sector'))

    print("\n【4/4】板块百分位")
    backfill_sector_percentile(get_collection('sector'))

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"全部完成! 耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")
    print("=" * 60)
