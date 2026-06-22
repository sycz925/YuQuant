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


def save_rps_to_database(rps_df: pd.DataFrame, db=None):
    """
    将 RPS 结果保存到数据库
    
    Args:
        rps_df: 包含 RPS 数据的 DataFrame
        db: MongoDB 数据库连接（可选，如果不提供则自动获取）
    """
    if rps_df.empty:
        logger.warning("没有 RPS 数据需要保存")
        return 0
    
    from app.data.db import get_db, get_stock_basics
    from pymongo import UpdateOne
    
    if db is None:
        db = get_db()
    
    # 准备数据
    operations = []
    update_time = datetime.utcnow()
    
    logger.info(f"准备保存 {len(rps_df)} 条 RPS 数据...")
    
    for _, row in rps_df.iterrows():
        # 构建更新文档
        doc = {
            'update_time': update_time
        }
        
        # 添加各周期 RPS 值
        rps_columns = ['rps_10', 'rps_20', 'rps_50', 'rps_120', 'rps_250']
        for col in rps_columns:
            if col in row.index and pd.notna(row[col]):
                doc[col] = int(row[col])
        
        # 使用 UpdateOne 进行更新或插入
        operations.append(
            UpdateOne(
                {'stock_code': row['code'], 'trade_date': str(row['date'])},
                {'$set': doc},
                upsert=True
            )
        )
    
    # 批量执行
    if operations:
        try:
            result = db['daily_data'].bulk_write(operations, ordered=False)
            logger.info(f"RPS 保存完成: 插入 {result.upserted_count}, 更新 {result.modified_count}")
            return len(operations)
        except Exception as e:
            logger.error(f"批量保存 RPS 失败: {e}")
            return 0
    
    return 0


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
    
    # 构建查询（只查个股，排除指数）
    query = {'data_type': 'stock'}
    if start_date or end_date:
        query['trade_date'] = {}
        if start_date:
            query['trade_date']['$gte'] = start_date
        if end_date:
            query['trade_date']['$lte'] = end_date
    
    # 查询数据
    logger.info(f"从数据库加载日线数据，查询条件: {query}")
    cursor = db['daily_data'].find(
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
