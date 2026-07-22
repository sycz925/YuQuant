"""
陶博士/欧奈尔 RPS（相对价格强度）指标计算模块
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import logging

from app.data.manager import get_data_manager
from app.data.task_manager import get_task_manager

logger = logging.getLogger(__name__)


def calculate_rps(daily_data_df: pd.DataFrame, data_type: str = 'stock', progress_callback=None) -> pd.DataFrame:
    """
    计算全市场股票的多周期 RPS 值

    Args:
        daily_data_df: 包含全市场股票日线数据的DataFrame，字段包括：
            date (日期，索引), code (股票代码), close (收盘价)
        data_type: 'stock' - 个股, 'sector' - 板块
        progress_callback: 进度回调函数，签名 callback(date, date_index, total_dates)

    Returns:
        包含 RPS 值的 DataFrame，字段：date, code, rps_10, rps_20, rps_50, rps_120, rps_250
    """
    if daily_data_df.empty:
        logger.warning("输入数据为空，无法计算 RPS")
        return pd.DataFrame()

    # 确保数据有必要的字段
    required_columns = ['code', 'close']
    for col in required_columns:
        if col not in daily_data_df.columns:
            raise ValueError(f"输入数据缺少必需字段: {col}")

    logger.info(f"开始计算 RPS[{data_type}]，数据量: {len(daily_data_df)} 条")

    # 关键过滤：股票上市不足 120 天 / 板块成立不足 20 天，不参与 RPS 计算
    MIN_LIST_DAYS = 120 if data_type == 'stock' else 20
    code_day_counts = daily_data_df.groupby('code')['close'].count()
    eligible_codes = set(code_day_counts[code_day_counts >= MIN_LIST_DAYS].index)
    before_count = daily_data_df['code'].nunique()
    daily_data_df = daily_data_df[daily_data_df['code'].isin(eligible_codes)].copy()
    after_count = daily_data_df['code'].nunique()
    filtered_count = before_count - after_count
    if filtered_count > 0:
        label = '上市' if data_type == 'stock' else '存续'
        logger.info(
            f"过滤{label}不足 {MIN_LIST_DAYS} 天的品种：排除 {filtered_count} 个，"
            f"保留 {after_count} 个"
        )

    if daily_data_df.empty:
        logger.warning("过滤后无有效数据，返回空")
        return pd.DataFrame()

    # Step 1: 将数据从长格式转换为宽格式（pivot）
    # 行：日期，列：股票代码，值：收盘价
    logger.info("正在 pivot 数据...")
    pivot_close = daily_data_df.pivot(columns='code', values='close')
    
    # 按日期排序（确保数据按时间顺序）
    pivot_close = pivot_close.sort_index()
    
    logger.info(f"pivot 完成，日期数: {len(pivot_close)}, 股票数: {len(pivot_close.columns)}")

    # Step 2: 计算各周期的涨幅（百分比变化）
    periods = {
        'rps_10': 10,
        'rps_20': 20,
        'rps_50': 50,
        'rps_120': 120,
        'rps_250': 250
    }
    
    pct_change_dict = {}
    for rps_name, period in periods.items():
        logger.info(f"计算 {period} 日涨幅...")
        # 使用 pct_change 向量化计算涨幅
        pct_change = pivot_close.pct_change(periods=period)
        pct_change_dict[rps_name] = pct_change

    # Step 3: 横向截面排名
    rps_results = []
    total_dates = len(pivot_close.index)
    
    logger.info("开始截面排名...")
    for date_idx, date in enumerate(pivot_close.index):
        # 回调报告当前计算日期
        if progress_callback:
            progress_callback(str(date), date_idx, total_dates)
        
        # 对每一个交易日进行处理
        daily_rps = {'date': date}
        
        for rps_name in periods.keys():
            # 获取当日所有股票的涨幅
            daily_pct = pct_change_dict[rps_name].loc[date]
            
            # RPS = rank百分位 * 100，范围 1~100
            # 涨幅最大 → percentile=1.0 → RPS=100（最强）
            # 涨幅最小 → percentile≈1/N → RPS≈1（最弱）
            rps_values = (daily_pct.rank(pct=True, ascending=True) * 100).round().clip(1, 100).astype('Int64')
            
            # 存储每只股票的 RPS 值
            for code in rps_values.index:
                if pd.notna(rps_values[code]):
                    if code not in daily_rps:
                        daily_rps[code] = {}
                    daily_rps[code][rps_name] = rps_values[code]
        
        # 转换为列表格式，便于后续处理
        for code in daily_rps:
            if code == 'date':
                continue
            rps_record = {
                'date': date,
                'code': code
            }
            for rps_name in periods.keys():
                rps_record[rps_name] = daily_rps[code].get(rps_name, None)
            rps_results.append(rps_record)
    
    # Step 4: 转换为 DataFrame
    result_df = pd.DataFrame(rps_results)
    
    if not result_df.empty:
        # 确保列顺序正确
        column_order = ['date', 'code'] + list(periods.keys())
        result_df = result_df[column_order]
        
        logger.info(f"RPS 计算完成，结果数: {len(result_df)}，日期范围: {result_df['date'].min()} ~ {result_df['date'].max()}")
    
    return result_df


def calculate_rps_incremental(
    daily_data_df: pd.DataFrame,
    target_dates: Optional[List[str]] = None,
    data_type: str = 'stock',
    progress_callback=None
) -> pd.DataFrame:
    """
    增量计算 RPS（只计算指定日期的 RPS 值）

    Args:
        daily_data_df: 包含全市场股票日线数据的 DataFrame
        target_dates: 指定要计算 RPS 的日期列表，如果为 None 则计算所有日期
        data_type: 'stock' - 个股, 'sector' - 板块
        progress_callback: 进度回调函数，签名 callback(date, date_index, total_dates)

    Returns:
        包含 RPS 值的 DataFrame
    """
    if daily_data_df.empty:
        return pd.DataFrame()

    # 关键过滤：股票上市不足 120 天 / 板块成立不足 20 天，不参与 RPS 计算
    MIN_LIST_DAYS = 120 if data_type == 'stock' else 20
    code_day_counts = daily_data_df.groupby('code')['close'].count()
    eligible_codes = set(code_day_counts[code_day_counts >= MIN_LIST_DAYS].index)
    daily_data_df = daily_data_df[daily_data_df['code'].isin(eligible_codes)].copy()
    if daily_data_df.empty:
        return pd.DataFrame()

    if target_dates is None:
        # 如果没有指定日期，计算所有日期
        return calculate_rps(daily_data_df, data_type=data_type, progress_callback=progress_callback)
    
    # 对于增量计算，我们需要至少 250 天的历史数据来计算最长周期
    # 确保数据范围足够
    daily_data_df = daily_data_df.sort_index()
    
    # 将数据 pivot
    pivot_close = daily_data_df.pivot(columns='code', values='close')
    pivot_close = pivot_close.sort_index()
    
    periods = {
        'rps_10': 10,
        'rps_20': 20,
        'rps_50': 50,
        'rps_120': 120,
        'rps_250': 250
    }
    
    pct_change_dict = {}
    for rps_name, period in periods.items():
        pct_change_dict[rps_name] = pivot_close.pct_change(periods=period)
    
    rps_results = []
    total_target = len(target_dates)
    
    for date_idx, date_str in enumerate(target_dates):
        if date_str not in pivot_close.index:
            logger.warning(f"目标日期 {date_str} 不在数据中，跳过")
            continue
        
        # 回调报告当前计算日期
        if progress_callback:
            progress_callback(date_str, date_idx, total_target)
        
        date = date_str
        daily_rps = {'date': date}
        
        for rps_name in periods.keys():
            if date not in pct_change_dict[rps_name].index:
                continue
                
            daily_pct = pct_change_dict[rps_name].loc[date]
            rps_values = (daily_pct.rank(pct=True, ascending=True) * 100).round().clip(1, 100).astype('Int64')
            
            for code in rps_values.index:
                if pd.notna(rps_values[code]):
                    if code not in daily_rps:
                        daily_rps[code] = {}
                    daily_rps[code][rps_name] = rps_values[code]
        
        for code in daily_rps:
            if code == 'date':
                continue
            rps_record = {
                'date': date,
                'code': code
            }
            for rps_name in periods.keys():
                rps_record[rps_name] = daily_rps[code].get(rps_name, None)
            rps_results.append(rps_record)
    
    result_df = pd.DataFrame(rps_results)
    return result_df


def load_all_daily_data_for_rps(db=None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
    """
    从数据库加载用于计算 RPS 的全市场日线数据
    
    Args:
        db: MongoDB 连接（可选）
        start_date: 开始日期（可选）
        end_date: 结束日期（可选）
    
    Returns:
        包含 date, code, close 的 DataFrame，date 作为索引
    """
    from app.data.db import get_db
    
    if db is None:
        db = get_db()
    
    # 构建查询（从stock_daily读取个股数据）
    query = {'close': {'$gt': 0}}
    if start_date or end_date:
        query['trade_date'] = {}
        if start_date:
            query['trade_date']['$gte'] = start_date
        if end_date:
            query['trade_date']['$lte'] = end_date
    
    # 查询数据
    logger.info(f"从stock_daily加载日线数据，查询条件: {query}")
    cursor = db['stock_daily'].find(
        query,
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
    )
    
    data = list(cursor)
    if not data:
        logger.warning("没有找到日线数据")
        return pd.DataFrame()
    
    # 转换为 DataFrame
    df = pd.DataFrame(data)
    
    # 重命名列以符合 RPS 计算要求
    df = df.rename(columns={
        'stock_code': 'code',
        'trade_date': 'date'
    })
    
    # 设置日期索引并排序
    df = df.set_index('date').sort_index()
    
    logger.info(f"加载完成，数据量: {len(df)}")
    return df


def load_sector_daily_data_for_rps(db=None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
    """
    从数据库加载用于计算 RPS 的板块日线数据
    
    Args:
        db: MongoDB 连接（可选）
        start_date: 开始日期（可选）
        end_date: 结束日期（可选）
    
    Returns:
        包含 date, code, close 的 DataFrame，date 作为索引
    """
    from app.data.db import get_db
    
    if db is None:
        db = get_db()
    
    # 构建查询（从sector_daily读取板块数据）
    query = {'close': {'$gt': 0}}
    if start_date or end_date:
        query['trade_date'] = {}
        if start_date:
            query['trade_date']['$gte'] = start_date
        if end_date:
            query['trade_date']['$lte'] = end_date
    
    # 查询数据
    logger.info(f"从sector_daily加载板块日线数据，查询条件: {query}")
    cursor = db['sector_daily'].find(
        query,
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
    )
    
    data = list(cursor)
    if not data:
        logger.warning("没有找到板块日线数据")
        return pd.DataFrame()
    
    # 转换为 DataFrame
    df = pd.DataFrame(data)
    
    # 重命名列以符合 RPS 计算要求
    df = df.rename(columns={
        'stock_code': 'code',
        'trade_date': 'date'
    })
    
    # 设置日期索引并排序
    df = df.set_index('date').sort_index()
    
    logger.info(f"板块日线数据加载完成，数据量: {len(df)}")
    return df


def backfill_sector_rps(db=None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> int:
    """
    回填板块 RPS 数据（RPS120, RPS250）
    
    Args:
        db: MongoDB 连接（可选）
        start_date: 开始日期（可选，默认全量）
        end_date: 结束日期（可选）
    
    Returns:
        更新的记录数
    """
    from app.data.db import get_db
    
    if db is None:
        db = get_db()
    
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")
    if not start_date:
        # RPS250需要250天数据，加载全量以确保准确
        start_date = '20230101'
    
    logger.info(f"开始回填板块 RPS 数据 ({start_date} ~ {end_date})...")
    
    # 加载板块日线数据
    sector_df = load_sector_daily_data_for_rps(db, start_date, end_date)
    if sector_df.empty:
        logger.warning("没有板块日线数据，跳过回填")
        return 0
    
    logger.info(f"加载数据: {len(sector_df)} 条, {sector_df['code'].nunique()} 个板块")
    
    # 过滤存续不足20天的板块
    MIN_LIST_DAYS = 20
    code_day_counts = sector_df.groupby('code')['close'].count()
    eligible_codes = set(code_day_counts[code_day_counts >= MIN_LIST_DAYS].index)
    sector_df = sector_df[sector_df['code'].isin(eligible_codes)].copy()
    
    # Pivot数据
    pivot_close = sector_df.pivot(columns='code', values='close')
    pivot_close = pivot_close.sort_index()
    
    # 计算120日和250日涨幅
    pct_change_120 = pivot_close.pct_change(periods=120)
    pct_change_250 = pivot_close.pct_change(periods=250)
    
    # 逐日排名并更新数据库
    updated_count = 0
    total_dates = len(pivot_close.index)
    
    for date_idx, date in enumerate(pivot_close.index):
        if date_idx % 20 == 0:
            logger.info(f"处理进度: {date_idx}/{total_dates} ({date})")
        
        update_fields = {}
        
        # RPS120
        if date in pct_change_120.index:
            daily_pct_120 = pct_change_120.loc[date]
            rps_120 = (daily_pct_120.rank(pct=True, ascending=True) * 100).round().clip(1, 100).astype('Int64')
            
            for code in rps_120.index:
                if pd.notna(rps_120[code]):
                    db['sector_daily'].update_one(
                        {'stock_code': code, 'trade_date': date},
                        {'$set': {'rps_120': int(rps_120[code])}}
                    )
                    updated_count += 1
        
        # RPS250
        if date in pct_change_250.index:
            daily_pct_250 = pct_change_250.loc[date]
            rps_250 = (daily_pct_250.rank(pct=True, ascending=True) * 100).round().clip(1, 100).astype('Int64')
            
            for code in rps_250.index:
                if pd.notna(rps_250[code]):
                    db['sector_daily'].update_one(
                        {'stock_code': code, 'trade_date': date},
                        {'$set': {'rps_250': int(rps_250[code])}}
                    )
                    updated_count += 1
    
    logger.info(f"板块 RPS 回填完成，更新 {updated_count} 条记录")
    return updated_count


def backfill_stock_rps10(db=None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> int:
    """
    回填个股 RPS10 数据（高效版本，只计算 RPS10）
    
    Args:
        db: MongoDB 连接（可选）
        start_date: 开始日期（可选，默认最近30天）
        end_date: 结束日期（可选）
    
    Returns:
        更新的记录数
    """
    from app.data.db import get_db
    
    if db is None:
        db = get_db()
    
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")
    if not start_date:
        # RPS10需要至少10天历史数据，加载最近30天确保足够
        start_date = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
    
    logger.info(f"开始回填个股 RPS10 数据 ({start_date} ~ {end_date})...")
    
    # 从stock_daily加载数据
    query = {
        'close': {'$gt': 0},
        'trade_date': {'$gte': start_date, '$lte': end_date}
    }
    cursor = db['stock_daily'].find(
        query,
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
    )
    
    data = list(cursor)
    if not data:
        logger.warning("没有个股日线数据，跳过回填")
        return 0
    
    df = pd.DataFrame(data)
    df = df.rename(columns={'stock_code': 'code', 'trade_date': 'date'})
    df = df.set_index('date').sort_index()
    
    logger.info(f"加载数据: {len(df)} 条, {df['code'].nunique()} 只股票, {len(df.index.unique())} 个交易日")
    
    # 过滤上市不足10天的股票
    MIN_LIST_DAYS = 10
    code_day_counts = df.groupby('code')['close'].count()
    eligible_codes = set(code_day_counts[code_day_counts >= MIN_LIST_DAYS].index)
    df = df[df['code'].isin(eligible_codes)].copy()
    logger.info(f"过滤后: {len(eligible_codes)} 只股票")
    
    if df.empty:
        return 0
    
    # Pivot数据
    pivot_close = df.pivot(columns='code', values='close')
    pivot_close = pivot_close.sort_index()
    
    # 计算10日涨幅
    pct_change_10 = pivot_close.pct_change(periods=10)
    
    # 逐日排名并更新数据库
    updated_count = 0
    total_dates = len(pivot_close.index)
    
    for date_idx, date in enumerate(pivot_close.index):
        if date_idx % 10 == 0:
            logger.info(f"处理进度: {date_idx}/{total_dates} ({date})")
        
        if date not in pct_change_10.index:
            continue
            
        daily_pct = pct_change_10.loc[date]
        rps_values = (daily_pct.rank(pct=True, ascending=True) * 100).round().clip(1, 100).astype('Int64')
        
        # 批量更新
        bulk_ops = []
        for code in rps_values.index:
            if pd.notna(rps_values[code]):
                bulk_ops.append(
                    db['stock_daily'].update_one(
                        {'stock_code': code, 'trade_date': date},
                        {'$set': {'rps_10': int(rps_values[code])}}
                    )
                )
        
        if bulk_ops:
            updated_count += len(bulk_ops)
    
    logger.info(f"个股 RPS10 回填完成，更新 {updated_count} 条记录")
    return updated_count
