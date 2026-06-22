#!/usr/bin/env python3
"""批量回刷冗余字段 - 分批处理"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pymongo import UpdateOne
from app.data.db import get_db, get_collection

# 配置
MA_PERIODS = [10, 20, 50, 120]
VOL_MA_PERIODS = [5, 10, 20, 50]
CHG_PERIODS = [5, 10, 20, 50, 120, 250]

def backfill_derived_fields(data_type='stock', batch_size=500):
    """分批回刷冗余字段"""
    coll = get_collection(data_type)
    vol_field = 'volume' if data_type == 'sector' else 'vol'
    
    # 获取所有日期
    all_dates = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}}))
    print(f"[{data_type}] 共 {len(all_dates)} 天需要处理")
    
    # 获取所有股票代码
    all_codes = sorted(coll.distinct('stock_code', {'close': {'$gt': 0}}))
    print(f"[{data_type}] 共 {len(all_codes)} 只股票/板块")
    
    total_updates = 0
    
    # 按股票分批处理
    for batch_start in range(0, len(all_codes), batch_size):
        batch_codes = all_codes[batch_start:batch_start + batch_size]
        print(f"\n[{data_type}] 处理批次 {batch_start//batch_size + 1}: 股票 {batch_start+1}-{min(batch_start+batch_size, len(all_codes))}")
        
        # 加载该批次股票的所有数据
        cursor = coll.find(
            {'stock_code': {'$in': batch_codes}, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, vol_field: 1, 'amount': 1,
             'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
        )
        raw_data = list(cursor)
        if not raw_data:
            continue
        
        df = pd.DataFrame(raw_data)
        df = df.sort_values(['stock_code', 'trade_date'])
        
        # 确定成交量字段
        actual_vol_field = vol_field if vol_field in df.columns else ('vol' if 'vol' in df.columns else 'volume')
        
        ops = []
        
        # 按股票计算
        for code in batch_codes:
            code_df = df[df['stock_code'] == code]
            if len(code_df) < 2:
                continue
            
            close_arr = code_df['close'].values
            vol_arr = code_df[actual_vol_field].values if actual_vol_field in code_df.columns else None
            dates_arr = code_df['trade_date'].values
            
            for i in range(1, len(dates_arr)):
                d = dates_arr[i]
                set_doc = {'update_time': datetime.utcnow()}
                
                # 1. 涨跌幅 chg_pct
                if i >= 1:
                    prev_close = close_arr[i - 1]
                    curr_close = close_arr[i]
                    if prev_close > 0:
                        set_doc['chg_pct'] = round((curr_close - prev_close) / prev_close * 100, 2)
                
                # 2. 均线 MA
                for period in MA_PERIODS:
                    if i >= period - 1:
                        ma_val = np.mean(close_arr[i - period + 1:i + 1])
                        set_doc[f'ma{period}'] = round(float(ma_val), 2)
                
                # 3. 成交量均线 VOL_MA
                if vol_arr is not None:
                    for period in VOL_MA_PERIODS:
                        if i >= period - 1:
                            vol_ma_val = np.mean(vol_arr[i - period + 1:i + 1])
                            set_doc[f'vol_ma{period}'] = round(float(vol_ma_val), 2)
                
                # 4. 区间涨幅 CHG_Xd
                for period in CHG_PERIODS:
                    if i >= period:
                        curr_close = close_arr[i]
                        prev_close = close_arr[i - period]
                        if prev_close > 0:
                            set_doc[f'chg_{period}d'] = round((curr_close - prev_close) / prev_close * 100, 2)
                
                # 5. RPS衍生指标（仅个股）
                if data_type == 'stock':
                    row = code_df.iloc[i]
                    rps_20 = row.get('rps_20')
                    rps_50 = row.get('rps_50')
                    rps_120 = row.get('rps_120')
                    rps_250 = row.get('rps_250')
                    
                    rps_vals = [v for v in [rps_20, rps_50, max(rps_120 or 0, rps_250 or 0)] if v is not None and v > 0]
                    if len(rps_vals) == 3:
                        rps_sum = rps_vals[0] + rps_vals[1] + rps_vals[2]
                        set_doc['rps_sum'] = int(rps_sum)
                        chg_pct = set_doc.get('chg_pct', 0) or 0
                        set_doc['is_active'] = bool(rps_sum > 270 and chg_pct > 5)
                
                ops.append(
                    UpdateOne(
                        {'stock_code': code, 'trade_date': d},
                        {'$set': set_doc}
                    )
                )
        
        # 批量写入
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total_updates += res.modified_count + res.upserted_count
            print(f"  写入 {len(ops)} 条，成功 {res.modified_count + res.upserted_count} 条")
    
    print(f"\n[{data_type}] 冗余字段回刷完成: {total_updates} 条更新")
    return total_updates


def backfill_percentile_fields(data_type='stock', batch_size=200):
    """分批回刷百分位字段"""
    coll = get_collection(data_type)
    
    # 获取所有日期
    all_dates = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}, 'amount': {'$gt': 0}}))
    print(f"\n[{data_type}] 百分位: 共 {len(all_dates)} 天需要处理")
    
    total_updates = 0
    
    # 按日期分批处理
    for batch_start in range(0, len(all_dates), batch_size):
        batch_dates = all_dates[batch_start:batch_start + batch_size]
        print(f"[{data_type}] 处理日期批次 {batch_start//batch_size + 1}: {batch_dates[0]} - {batch_dates[-1]}")
        
        cursor = coll.find(
            {'trade_date': {'$in': batch_dates}, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'amount': 1}
        )
        raw_data = list(cursor)
        if not raw_data:
            continue
        
        df = pd.DataFrame(raw_data)
        ops = []
        
        for calc_date in batch_dates:
            day_df = df[df['trade_date'] == calc_date]
            if len(day_df) < 10:
                continue
            
            day_df = day_df.copy()
            day_df['close_rank'] = day_df['close'].rank(pct=True) * 100
            day_df['amount_rank'] = day_df['amount'].rank(pct=True) * 100
            
            for _, row in day_df.iterrows():
                ops.append(
                    UpdateOne(
                        {'stock_code': row['stock_code'], 'trade_date': calc_date},
                        {'$set': {
                            'close_pct': int(round(row['close_rank'])),
                            'amount_pct': int(round(row['amount_rank'])),
                            'update_time': datetime.utcnow()
                        }}
                    )
                )
        
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total_updates += res.modified_count + res.upserted_count
            print(f"  写入 {len(ops)} 条，成功 {res.modified_count + res.upserted_count} 条")
    
    print(f"\n[{data_type}] 百分位回刷完成: {total_updates} 条更新")
    return total_updates


if __name__ == '__main__':
    print("=" * 60)
    print("开始批量回刷冗余字段")
    print("=" * 60)
    
    # 回刷个股
    print("\n【1/4】回刷个股冗余字段...")
    backfill_derived_fields('stock', batch_size=200)
    
    print("\n【2/4】回刷个股百分位字段...")
    backfill_percentile_fields('stock', batch_size=100)
    
    # 回刷板块
    print("\n【3/4】回刷板块冗余字段...")
    backfill_derived_fields('sector', batch_size=200)
    
    print("\n【4/4】回刷板块百分位字段...")
    backfill_percentile_fields('sector', batch_size=100)
    
    print("\n" + "=" * 60)
    print("全部回刷完成!")
    print("=" * 60)
