#!/usr/bin/env python3
"""高效批量回刷冗余字段 - 使用MongoDB聚合管道"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('PYTHONWARNINGS', 'ignore')

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pymongo import UpdateOne, ASCENDING, DESCENDING
from app.data.db import get_db, get_collection


def backfill_chg_pct(coll, data_type='stock'):
    """用聚合管道直接在MongoDB中计算涨跌幅"""
    print(f"  [chg_pct] 使用聚合管道计算...")
    update_time = datetime.utcnow()

    # 聚合管道：用$setWindowFields做窗口函数获取前一日收盘价
    pipeline = [
        {'$match': {'close': {'$gt': 0}}},
        {'$sort': {'stock_code': ASCENDING, 'trade_date': ASCENDING}},
        {'$setWindowFields': {
            'partitionBy': '$stock_code',
            'sortBy': {'trade_date': ASCENDING},
            'output': {
                'prev_close': {
                    '$shift': {'output': '$close', 'by': -1}
                }
            }
        }},
        {'$match': {'prev_close': {'$gt': 0}}},
        {'$project': {
            'stock_code': 1, 'trade_date': 1,
            'chg_pct': {'$round': [{'$multiply': [{'$divide': [
                {'$subtract': ['$close', '$prev_close']}, '$prev_close']
            }, 100]}, 2]}
        }}
    ]

    cursor = coll.aggregate(pipeline, allowDiskUse=True)
    ops = []
    total = 0
    for doc in cursor:
        ops.append(UpdateOne(
            {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
            {'$set': {'chg_pct': doc['chg_pct'], 'update_time': update_time}}
        ))
        if len(ops) >= 50000:
            res = coll.bulk_write(ops, ordered=False)
            total += res.modified_count
            print(f"    chg_pct 已写入 {total} 条")
            ops = []
    if ops:
        res = coll.bulk_write(ops, ordered=False)
        total += res.modified_count
    print(f"  [chg_pct] 完成: {total} 条")
    return total


def backfill_period_chg(coll, data_type='stock'):
    """计算区间涨幅 chg_5d/10d/20d/50d/120d/250d"""
    periods = [5, 10, 20, 50, 120, 250]
    update_time = datetime.utcnow()
    total = 0

    for period in periods:
        print(f"  [chg_{period}d] 计算中...")
        pipeline = [
            {'$match': {'close': {'$gt': 0}}},
            {'$sort': {'stock_code': ASCENDING, 'trade_date': ASCENDING}},
            {'$setWindowFields': {
                'partitionBy': '$stock_code',
                'sortBy': {'trade_date': ASCENDING},
                'output': {
                    'prev_close': {
                        '$shift': {'output': '$close', 'by': period}
                    }
                }
            }},
            {'$match': {'prev_close': {'$gt': 0}}},
            {'$project': {
                'stock_code': 1, 'trade_date': 1,
                f'chg_{period}d': {'$round': [{'$multiply': [{'$divide': [
                    {'$subtract': ['$close', '$prev_close']}, '$prev_close']
                }, 100]}, 2]}
            }}
        ]

        cursor = coll.aggregate(pipeline, allowDiskUse=True)
        ops = []
        for doc in cursor:
            field = f'chg_{period}d'
            ops.append(UpdateOne(
                {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                {'$set': {field: doc[field], 'update_time': update_time}}
            ))
            if len(ops) >= 50000:
                res = coll.bulk_write(ops, ordered=False)
                total += res.modified_count
                ops = []
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total += res.modified_count
        print(f"    chg_{period}d 完成")

    print(f"  [period_chg] 全部完成: {total} 条")
    return total


def backfill_ma(coll, data_type='stock', periods=[10, 20, 50, 120]):
    """计算移动平均线 MA"""
    update_time = datetime.utcnow()
    total = 0

    for period in periods:
        print(f"  [ma{period}] 计算中...")
        pipeline = [
            {'$match': {'close': {'$gt': 0}}},
            {'$sort': {'stock_code': ASCENDING, 'trade_date': ASCENDING}},
            {'$setWindowFields': {
                'partitionBy': '$stock_code',
                'sortBy': {'trade_date': ASCENDING},
                'output': {
                    'ma_window': {
                        '$avg': '$close',
                        'window': [{'documents': [f'{-period+1}', 'current']}]
                    }
                }
            }},
            {'$match': {'ma_window': {'$ne': None}}},
            {'$project': {
                'stock_code': 1, 'trade_date': 1,
                f'ma{period}': {'$round': ['$ma_window', 2]}
            }}
        ]

        cursor = coll.aggregate(pipeline, allowDiskUse=True)
        ops = []
        for doc in cursor:
            ops.append(UpdateOne(
                {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                {'$set': {f'ma{period}': doc[f'ma{period}'], 'update_time': update_time}}
            ))
            if len(ops) >= 50000:
                res = coll.bulk_write(ops, ordered=False)
                total += res.modified_count
                ops = []
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total += res.modified_count
        print(f"    ma{period} 完成")

    print(f"  [ma] 全部完成: {total} 条")
    return total


def backfill_vol_ma(coll, data_type='stock', periods=[5, 10, 20, 50]):
    """计算成交量均线"""
    vol_field = 'volume' if data_type == 'sector' else 'vol'
    update_time = datetime.utcnow()
    total = 0

    for period in periods:
        print(f"  [vol_ma{period}] 计算中...")
        pipeline = [
            {'$match': {vol_field: {'$gt': 0}}},
            {'$sort': {'stock_code': ASCENDING, 'trade_date': ASCENDING}},
            {'$setWindowFields': {
                'partitionBy': '$stock_code',
                'sortBy': {'trade_date': ASCENDING},
                'output': {
                    'vol_ma_window': {
                        '$avg': f'${vol_field}',
                        'window': [{'documents': [f'{-period+1}', 'current']}]
                    }
                }
            }},
            {'$match': {'vol_ma_window': {'$ne': None}}},
            {'$project': {
                'stock_code': 1, 'trade_date': 1,
                f'vol_ma{period}': {'$round': ['$vol_ma_window', 2]}
            }}
        ]

        cursor = coll.aggregate(pipeline, allowDiskUse=True)
        ops = []
        for doc in cursor:
            ops.append(UpdateOne(
                {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                {'$set': {f'vol_ma{period}': doc[f'vol_ma{period}'], 'update_time': update_time}}
            ))
            if len(ops) >= 50000:
                res = coll.bulk_write(ops, ordered=False)
                total += res.modified_count
                ops = []
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total += res.modified_count
        print(f"    vol_ma{period} 完成")

    print(f"  [vol_ma] 全部完成: {total} 条")
    return total


def backfill_rps_derived(coll):
    """计算RPS衍生字段 rps_sum, is_active"""
    update_time = datetime.utcnow()
    print(f"  [rps_sum/is_active] 计算中...")

    pipeline = [
        {'$match': {
            'rps_20': {'$gt': 0}, 'rps_50': {'$gt': 0},
            '$or': [{'rps_120': {'$gt': 0}}, {'rps_250': {'$gt': 0}}]
        }},
        {'$project': {
            'stock_code': 1, 'trade_date': 1, 'chg_pct': 1,
            'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1,
            'rps_sum': {'$add': [
                '$rps_20', '$rps_50',
                {'$max': [{'$ifNull': ['$rps_120', 0]}, {'$ifNull': ['$rps_250', 0]}]}
            ]},
            'is_active': {'$and': [
                {'$gt': [
                    {'$add': ['$rps_20', '$rps_50',
                              {'$max': [{'$ifNull': ['$rps_120', 0]}, {'$ifNull': ['$rps_250', 0]}]}]},
                    270
                ]},
                {'$gt': [{'$ifNull': ['$chg_pct', 0]}, 5]}
            ]}
        }}
    ]

    cursor = coll.aggregate(pipeline, allowDiskUse=True)
    ops = []
    total = 0
    for doc in cursor:
        ops.append(UpdateOne(
            {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
            {'$set': {
                'rps_sum': int(doc['rps_sum']),
                'is_active': bool(doc['is_active']),
                'update_time': update_time
            }}
        ))
        if len(ops) >= 50000:
            res = coll.bulk_write(ops, ordered=False)
            total += res.modified_count
            ops = []
    if ops:
        res = coll.bulk_write(ops, ordered=False)
        total += res.modified_count
    print(f"  [rps_sum/is_active] 完成: {total} 条")
    return total


def backfill_percentile(coll, data_type='stock'):
    """计算百分位 close_pct, amount_pct"""
    update_time = datetime.utcnow()
    total = 0

    all_dates = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}, 'amount': {'$gt': 0}}))
    print(f"  [percentile] 共 {len(all_dates)} 天")

    for i, calc_date in enumerate(all_dates):
        pipeline = [
            {'$match': {'trade_date': calc_date, 'close': {'$gt': 0}, 'amount': {'$gt': 0}}},
            {'$setWindowFields': {
                'output': {
                    'close_pct': {'$percentRank': {'sortBy': {'close': ASCENDING}}},
                    'amount_pct': {'$percentRank': {'sortBy': {'amount': ASCENDING}}}
                }
            }},
            {'$project': {
                'stock_code': 1,
                'close_pct': {'$round': [{'$multiply': ['$close_pct', 100]}, 0]},
                'amount_pct': {'$round': [{'$multiply': ['$amount_pct', 100]}, 0]}
            }}
        ]

        cursor = coll.aggregate(pipeline)
        ops = []
        for doc in cursor:
            ops.append(UpdateOne(
                {'stock_code': doc['stock_code'], 'trade_date': calc_date},
                {'$set': {
                    'close_pct': int(doc['close_pct']),
                    'amount_pct': int(doc['amount_pct']),
                    'update_time': update_time
                }}
            ))
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total += res.modified_count

        if (i + 1) % 100 == 0:
            print(f"    percentile 进度: {i+1}/{len(all_dates)}")

    print(f"  [percentile] 完成: {total} 条")
    return total


if __name__ == '__main__':
    print("=" * 60)
    print("高效回刷冗余字段 (MongoDB聚合管道)")
    print("=" * 60)

    db = get_db()
    t0 = time.time()

    # === 个股 ===
    print("\n【个股 stock_daily】")
    coll = get_collection('stock')

    backfill_chg_pct(coll, 'stock')
    backfill_period_chg(coll, 'stock')
    backfill_ma(coll, 'stock', [10, 20, 50, 120])
    backfill_vol_ma(coll, 'stock', [5, 10, 20, 50])
    backfill_rps_derived(coll)
    backfill_percentile(coll, 'stock')

    # === 板块 ===
    print("\n【板块 sector_daily】")
    coll2 = get_collection('sector')

    backfill_chg_pct(coll2, 'sector')
    backfill_period_chg(coll2, 'sector')
    backfill_ma(coll2, 'sector', [10, 20, 50])
    backfill_vol_ma(coll2, 'sector', [5, 10, 20])
    backfill_percentile(coll2, 'sector')

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"全部完成! 耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")
    print("=" * 60)
