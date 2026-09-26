#!/usr/bin/env python3
"""
修正 ETF 588710（科创半导体设备ETF华泰柏瑞）的前复权数据

问题：20260814→20260817 发生份额拆分，但前复权未生效
原因：ETF 同步使用 gap-based 检测，单日同步时无法检测到除权事件

修正方案：
1. 从 PyTdX 拉取原始数据（adjusted=False）
2. 获取 xdxr 事件（份额拆分）
3. 用 apply_forward_adjust 计算前复权
4. 保存原始价格到 close_raw/open_raw/high_raw/low_raw
5. 覆盖写入 etf_daily
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from app.data.sources.pytdx_source import PytdxSource, MARKET_SH, _get_connection, _return_connection
from app.data.db import get_db, bulk_upsert_daily_data
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

STOCK_CODE = '588710'


def fix_etf_588710():
    """修正 588710 的前复权数据"""
    logger.info(f"开始修正 ETF {STOCK_CODE} 前复权数据")

    # 1. 获取 xdxr 事件（先获取事件，再拉取数据）
    logger.info("步骤1: 获取 xdxr 事件...")
    api = _get_connection()
    if not api:
        logger.error("无法获取 PyTdX 连接，尝试初始化连接池...")
        # 尝试手动初始化
        from app.data.sources.pytdx_source import _init_connection_pool
        _init_connection_pool()
        api = _get_connection()
        if not api:
            logger.error("仍然无法获取 PyTdX 连接，请检查网络和 PyTdX 服务器")
            return False

    try:
        xdxr_raw = api.get_xdxr_info(MARKET_SH, STOCK_CODE)
        if not xdxr_raw:
            logger.warning("未找到 xdxr 事件，数据可能无需调整")
            return False

        logger.info(f"  获取到 {len(xdxr_raw)} 个 xdxr 事件")
        for evt in xdxr_raw:
            date_str = f"{int(evt.get('year', 0)):04d}{int(evt.get('month', 0)):02d}{int(evt.get('day', 0)):02d}"
            logger.info(f"    {date_str}: category={evt.get('category')} name={evt.get('name')} "
                       f"fenhong={evt.get('fenhong')} songzhuangu={evt.get('songzhuangu')} "
                       f"peigu={evt.get('peigu')} suogu={evt.get('suogu')} fenshu={evt.get('fenshu')}")

        # 处理扩缩股事件（category=11）
        xdxr_events = []
        for evt in xdxr_raw:
            if evt.get('category') == 11:  # 扩缩股
                suogu = evt.get('suogu') or 0
                fenshu = evt.get('fenshu') or 0
                if suogu > 0:
                    # suogu > 1 表示缩股（如3表示3股缩为1股），复权因子 = suogu
                    # suogu < 1 表示扩股（如0.5表示1股扩为2股），复权因子 = suogu
                    date_str = f"{int(evt['year']):04d}{int(evt['month']):02d}{int(evt['day']):02d}"
                    xdxr_events.append({
                        'date': date_str,
                        'type': 'split',
                        'factor': suogu,  # 缩股因子
                    })
                    logger.info(f"    识别扩缩股事件: {date_str} suogu={suogu}")

        if not xdxr_events:
            logger.warning("未找到有效的扩缩股事件")
            return False

        logger.info(f"  过滤后 {len(xdxr_events)} 个有效事件")
    finally:
        _return_connection(api)

    # 2. 拉取原始数据（不复权）
    logger.info("步骤2: 从 PyTdX 拉取原始数据...")
    df_raw = PytdxSource.get_stock_daily(STOCK_CODE, '20200101', adjusted=False)
    if df_raw is None or df_raw.empty:
        logger.error("无法获取原始数据")
        return False
    logger.info(f"  获取到 {len(df_raw)} 条记录，日期范围: {df_raw['trade_date'].min()} ~ {df_raw['trade_date'].max()}")

    # 3. 保存原始价格
    logger.info("步骤3: 保存原始价格...")
    df_raw_save = df_raw.copy()

    # 4. 应用前复权（扩缩股事件）
    logger.info("步骤4: 应用前复权...")
    df_adjusted = df_raw.copy()
    df_adjusted = df_adjusted.sort_values('trade_date').reset_index(drop=True)

    # 对每个扩缩股事件应用前复权
    for evt in xdxr_events:
        evt_date = evt['date']
        factor = evt['factor']

        # 找到事件日期的索引
        evt_idx = None
        for i, d in enumerate(df_adjusted['trade_date']):
            if d == evt_date:
                evt_idx = i
                break

        if evt_idx is None or evt_idx == 0:
            logger.warning(f"  无法找到事件日期 {evt_date} 或其前一天")
            continue

        # 获取事件前一天的收盘价
        prev_close = df_adjusted.iloc[evt_idx - 1]['close']
        if prev_close <= 0:
            logger.warning(f"  事件日期 {evt_date} 前一天收盘价无效: {prev_close}")
            continue

        # 计算复权因子：事件日之前的收盘价需要除以因子
        # 对于缩股：factor > 1，历史价格需要除以 factor
        # 对于扩股：factor < 1，历史价格需要除以 factor
        adj_factor = 1.0 / factor  # 例如：3股缩1股，factor=3，adj_factor=1/3

        logger.info(f"  处理事件 {evt_date}: factor={factor}, adj_factor={adj_factor:.6f}")

        # 对事件日之前的所有价格应用前复权
        for f in ['close', 'open', 'high', 'low']:
            df_adjusted.loc[:evt_idx-1, f] = (df_adjusted.loc[:evt_idx-1, f] * adj_factor).round(4)

    # 5. 添加 close_raw 等字段
    logger.info("步骤5: 添加原始价格字段...")
    df_adjusted['close_raw'] = df_raw_save['close'].values
    df_adjusted['open_raw'] = df_raw_save['open'].values
    df_adjusted['high_raw'] = df_raw_save['high'].values
    df_adjusted['low_raw'] = df_raw_save['low'].values

    # 添加 code 字段
    df_adjusted['code'] = STOCK_CODE

    # 6. 验证修正效果
    logger.info("步骤6: 验证修正效果...")
    # 找到除权事件前后数据
    for i in range(1, len(df_adjusted)):
        prev = df_adjusted.iloc[i-1]
        curr = df_adjusted.iloc[i]
        if prev['close'] > 0 and curr['close'] > 0:
            ratio = curr['close'] / prev['close']
            if ratio < 0.6:
                logger.info(f"  除权事件验证:")
                logger.info(f"    {prev['trade_date']}: close={prev['close']:.4f} (原始: {prev['close_raw']:.4f})")
                logger.info(f"    {curr['trade_date']}: close={curr['close']:.4f} (原始: {curr['close_raw']:.4f})")
                logger.info(f"    复权后比率: {ratio:.4f}")

    # 7. 写入数据库
    logger.info("步骤7: 写入数据库...")
    records = df_adjusted.to_dict('records')
    bulk_upsert_daily_data(STOCK_CODE, records, 'pytdx', 'etf')

    logger.info(f"修正完成！共写入 {len(records)} 条记录")
    return True


def verify_fix():
    """验证修正结果"""
    logger.info("=" * 50)
    logger.info("验证修正结果")
    logger.info("=" * 50)

    db = get_db()

    # 查询除权前后数据
    docs = list(db['etf_daily'].find(
        {'stock_code': STOCK_CODE, 'trade_date': {'$gte': '20260810', '$lte': '20260820'}},
        {'_id': 0}
    ).sort('trade_date', 1))

    logger.info(f"{STOCK_CODE} 除权前后数据:")
    for doc in docs:
        close_raw = doc.get('close_raw', 'N/A')
        if close_raw != 'N/A':
            close_raw = f"{close_raw:.4f}"
        logger.info(f"  {doc['trade_date']}: close={doc['close']:.4f} close_raw={close_raw}")

    # 检查是否还有未修正的数据（close_raw 不存在）
    count_no_raw = db['etf_daily'].count_documents({
        'stock_code': STOCK_CODE,
        'close_raw': {'$exists': False}
    })
    logger.info(f"无 close_raw 字段的记录数: {count_no_raw}")

    # 检查 close_raw == close 的记录（说明未调整）
    cursor = db['etf_daily'].find({
        'stock_code': STOCK_CODE,
        'close_raw': {'$exists': True}
    }, {'_id': 0, 'trade_date': 1, 'close': 1, 'close_raw': 1})

    diff_count = 0
    same_count = 0
    for doc in cursor:
        if doc['close'] == doc['close_raw']:
            same_count += 1
        else:
            diff_count += 1

    logger.info(f"close_raw 存在的记录中: 已调整={diff_count}, 未调整={same_count}")

    return diff_count > 0


if __name__ == '__main__':
    success = fix_etf_588710()
    if success:
        verify_fix()
    else:
        logger.error("修正失败")
        sys.exit(1)
