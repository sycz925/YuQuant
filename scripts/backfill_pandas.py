#!/usr/bin/env python3
"""极速回刷: 全量加载 + pandas向量化计算 + 批量写入"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pymongo import UpdateOne
from app.data.db import get_collection

MA_PERIODS = [10, 20, 50, 120]
VOL_MA_PERIODS = [5, 10, 20, 50]
CHG_PERIODS = [5, 10, 20, 50, 120, 250]
BATCH = 50000


def process_stock():
    coll = get_collection('stock')
    t0 = time.time()
    print("[stock] 加载全部数据...")
    cursor = coll.find(
        {'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'vol': 1, 'rps_20': 1,
         'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
    )
    df = pd.DataFrame(list(cursor))
    print(f"  加载 {len(df)} 条, {time.time()-t0:.1f}秒")

    df = df.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)
    g = df.groupby('stock_code')

    # 向量化计算: 涨跌幅
    print("[stock] 计算 chg_pct...")
    df['prev_close'] = g['close'].shift(1)
    df['chg_pct'] = ((df['close'] - df['prev_close']) / df['prev_close'] * 100).round(2)
    df.loc[df['prev_close'].isna() | (df['prev_close'] <= 0), 'chg_pct'] = None

    # 向量化计算: MA
    print("[stock] 计算 MA...")
    for p in MA_PERIODS:
        df[f'ma{p}'] = g['close'].transform(lambda x: x.rolling(p, min_periods=p).mean()).round(2)

    # 向量化计算: VOL_MA
    print("[stock] 计算 VOL_MA...")
    for p in VOL_MA_PERIODS:
        df[f'vol_ma{p}'] = g['vol'].transform(lambda x: x.rolling(p, min_periods=p).mean()).round(2)

    # 向量化计算: 区间涨幅
    print("[stock] 计算 区间涨幅...")
    for p in CHG_PERIODS:
        df[f'chg_{p}d'] = g['close'].transform(lambda x: (x / x.shift(p) - 1) * 100).round(2)

    # RPS衍生
    print("[stock] 计算 rps_sum/is_active...")
    rps_max = df[['rps_120', 'rps_250']].max(axis=1).fillna(0)
    rps_sum_raw = df['rps_20'].fillna(0) + df['rps_50'].fillna(0) + rps_max
    has_rps = df['rps_20'].notna() & df['rps_50'].notna() & (df['rps_20'] > 0) & (df['rps_50'] > 0)
    df['rps_sum'] = pd.array([int(v) if h else None for h, v in zip(has_rps, rps_sum_raw)], dtype=object)
    df['is_active'] = pd.array([True if h and v > 270 and (df.loc[i, 'chg_pct'] or 0) > 5 else None if not h else False
                                for i, (h, v) in enumerate(zip(has_rps, rps_sum_raw))], dtype=object)

    # 百分位
    print("[stock] 计算 百分位...")
    df['close_pct'] = df.groupby('trade_date')['close'].rank(pct=True) * 100

    # 批量写入
    print("[stock] 写入数据库...")
    fields = ['chg_pct', 'ma10', 'ma20', 'ma50', 'ma120', 'vol_ma5', 'vol_ma10', 'vol_ma20', 'vol_ma50',
              'chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'chg_250d',
              'rps_sum', 'is_active', 'close_pct']

    # 用itertuples比iterrows快很多
    ops = []
    total = 0
    for row in df.itertuples(index=False):
        set_doc = {}
        for f in fields:
            v = getattr(row, f, None)
            if v is None:
                continue
            if isinstance(v, float) and np.isnan(v):
                continue
            if isinstance(v, (np.bool_,)):
                v = bool(v)
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = float(v)
            set_doc[f] = v
        if set_doc:
            ops.append(UpdateOne(
                {'stock_code': row.stock_code, 'trade_date': row.trade_date},
                {'$set': set_doc}
            ))
        if len(ops) >= BATCH:
            coll.bulk_write(ops, ordered=False)
            total += len(ops)
            ops = []
    if ops:
        coll.bulk_write(ops, ordered=False)
        total += len(ops)

    print(f"[stock] 完成: {total} 条, 耗时 {time.time()-t0:.1f}秒")


def process_sector():
    coll = get_collection('sector')
    t0 = time.time()
    print("\n[sector] 加载全部数据...")
    cursor = coll.find(
        {'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'volume': 1, 'amount': 1}
    )
    df = pd.DataFrame(list(cursor))
    print(f"  加载 {len(df)} 条, {time.time()-t0:.1f}秒")

    df = df.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)
    g = df.groupby('stock_code')

    df['prev_close'] = g['close'].shift(1)
    df['chg_pct'] = ((df['close'] - df['prev_close']) / df['prev_close'] * 100).round(2)
    df.loc[df['prev_close'].isna() | (df['prev_close'] <= 0), 'chg_pct'] = None

    for p in [10, 20, 50]:
        df[f'ma{p}'] = g['close'].transform(lambda x: x.rolling(p, min_periods=p).mean()).round(2)
    for p in [5, 10, 20]:
        df[f'vol_ma{p}'] = g['volume'].transform(lambda x: x.rolling(p, min_periods=p).mean()).round(2)
    for p in CHG_PERIODS:
        df[f'chg_{p}d'] = g['close'].transform(lambda x: (x / x.shift(p) - 1) * 100).round(2)

    df['close_pct'] = df.groupby('trade_date')['close'].rank(pct=True) * 100
    if 'amount' in df.columns:
        df['amount_pct'] = df.groupby('trade_date')['amount'].rank(pct=True) * 100
    else:
        df['amount_pct'] = None

    fields = ['chg_pct', 'ma10', 'ma20', 'ma50', 'vol_ma5', 'vol_ma10', 'vol_ma20',
              'chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'chg_250d', 'close_pct']

    print("[sector] 写入数据库...")
    ops = []
    total = 0
    for _, row in df.iterrows():
        set_doc = {}
        for f in fields:
            v = row.get(f)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            if isinstance(v, (np.bool_,)):
                v = bool(v)
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = float(v)
            set_doc[f] = v
        if set_doc:
            ops.append(UpdateOne(
                {'stock_code': row['stock_code'], 'trade_date': row['trade_date']},
                {'$set': set_doc}
            ))
        if len(ops) >= BATCH:
            coll.bulk_write(ops, ordered=False)
            total += len(ops)
            ops = []
    if ops:
        coll.bulk_write(ops, ordered=False)
        total += len(ops)

    print(f"[sector] 完成: {total} 条, 耗时 {time.time()-t0:.1f}秒")


if __name__ == '__main__':
    t_total = time.time()
    print("=" * 60)
    print("极速回刷 (pandas向量化)")
    print("=" * 60)

    process_stock()
    process_sector()

    print(f"\n{'=' * 60}")
    print(f"全部完成! 总耗时: {time.time()-t_total:.1f}秒")
    print("=" * 60)
