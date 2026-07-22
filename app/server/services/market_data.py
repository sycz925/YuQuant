"""
Market Data - 市场数据计算模块
从 market_review.py 提取的数据计算函数
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def calculate_nh_nl_series(days: int = 250) -> List[Dict[str, Any]]:
    """
    计算 NH-NL 序列（新高新低）
    :param days: 计算天数
    :return: NH-NL 数据列表
    """
    from app.data.db import get_db
    db = get_db()
    
    # 获取最新交易日
    latest_doc = db['stock_daily'].find_one(
        {'close': {'$gt': 0}},
        sort=[('trade_date', -1)],
        projection={'trade_date': 1, '_id': 0}
    )
    if not latest_doc:
        return []
    
    latest_date = latest_doc['trade_date']
    
    # 获取历史交易日
    dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}}))
    if len(dates) < days:
        days = len(dates)
    
    target_dates = dates[-days:]
    
    result = []
    for date in target_dates:
        # 计算新高数
        new_high_pipeline = [
            {'$match': {'trade_date': date, 'close': {'$gt': 0}}},
            {'$group': {
                '_id': None,
                'new_high_count': {'$sum': {'$cond': [{'$gte': ['$close', '$hist_max_250d']}, 1, 0]}}
            }}
        ]
        new_high_result = list(db['stock_daily'].aggregate(new_high_pipeline))
        new_high_count = new_high_result[0]['new_high_count'] if new_high_result else 0
        
        # 计算新低数
        new_low_pipeline = [
            {'$match': {'trade_date': date, 'close': {'$gt': 0}}},
            {'$group': {
                '_id': None,
                'new_low_count': {'$sum': {'$cond': [{'$lte': ['$close', '$hist_min_250d']}, 1, 0]}}
            }}
        ]
        new_low_result = list(db['stock_daily'].aggregate(new_low_pipeline))
        new_low_count = new_low_result[0]['new_low_count'] if new_low_result else 0
        
        result.append({
            'date': date,
            'new_high': new_high_count,
            'new_low': new_low_count,
            'nh_nl': new_high_count - new_low_count
        })
    
    return result


def get_market_daily(trade_date: str = None, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    获取市场日线数据
    :param trade_date: 交易日期，None 表示最新
    :param force_refresh: 是否强制刷新
    """
    from app.data.db import get_db
    db = get_db()
    
    if trade_date is None:
        # 获取最新交易日
        latest_doc = db['stock_daily'].find_one(
            {'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        if not latest_doc:
            return None
        trade_date = latest_doc['trade_date']
    
    # 查询市场日线数据
    market_doc = db['market_daily'].find_one(
        {'trade_date': trade_date},
        {'_id': 0}
    )
    
    return market_doc


def get_latest_trade_date() -> Optional[str]:
    """获取最新交易日"""
    from app.data.db import get_db
    db = get_db()
    
    latest_doc = db['stock_daily'].find_one(
        {'close': {'$gt': 0}},
        sort=[('trade_date', -1)],
        projection={'trade_date': 1, '_id': 0}
    )
    
    return latest_doc['trade_date'] if latest_doc else None


def get_previous_trade_date(date: str) -> Optional[str]:
    """获取上一个交易日"""
    from app.data.db import get_db
    db = get_db()
    
    prev_doc = db['stock_daily'].find_one(
        {'trade_date': {'$lt': date}, 'close': {'$gt': 0}},
        sort=[('trade_date', -1)],
        projection={'trade_date': 1, '_id': 0}
    )
    
    return prev_doc['trade_date'] if prev_doc else None
